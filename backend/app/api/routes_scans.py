import os
import shutil
import uuid
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Body
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.models.db_models import Project, ScanSession
from app.schemas.cad_schemas import ScanSessionResponse
from app.schemas.adt import CalibrationSpec, CaptureSide
from app.services.vision_engine import VisionEngine

router = APIRouter(prefix="/scans", tags=["Scans"])

# Request / Response Schemas for v1 endpoints per PCAD-API-ADT-003
class ScanCreateRequest(BaseModel):
    project_id: str
    title: Optional[str] = "Untitled Scan"

class ScanCreateResponse(BaseModel):
    scan_id: str
    status: str
    upload_urls: Dict[str, str]
    expires_in_seconds: int

class ViewConfirmRequest(BaseModel):
    blur_score: float = Field(..., ge=0.0, description="Laplacian variance sharpness score")
    width_px: int = Field(default=1920, ge=1)
    height_px: int = Field(default=1080, ge=1)
    image_url: Optional[str] = None

class ViewConfirmResponse(BaseModel):
    scan_id: str
    side: str
    status: str
    blur_score: float
    is_sharp: bool
    views_completed: int


@router.post("", response_model=ScanCreateResponse)
@router.post("/create", response_model=ScanCreateResponse)
async def create_scan_session(
    payload: ScanCreateRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Creates a new scan session and issues pre-signed upload URLs for all 6 perspectives.
    Document ID: PCAD-API-ADT-003 Section 2.
    """
    project = await db.get(Project, payload.project_id)
    if not project:
        # Auto-create fallback project if not found in dev mode
        project = Project(id=payload.project_id, name=payload.title, unit="mm")
        db.add(project)
        await db.commit()

    scan_id = str(uuid.uuid4())
    session_upload_dir = settings.UPLOADS_DIR / scan_id
    session_upload_dir.mkdir(parents=True, exist_ok=True)

    # In dev, upload endpoints point to local storage or Cloudflare R2
    r2_public = os.getenv("CLOUDFLARE_R2_PUBLIC_URL", "http://localhost:8000/storage/uploads")
    upload_urls = {
        side.value: f"{r2_public}/{scan_id}/{side.value}.png"
        for side in CaptureSide
    }

    scan_session = ScanSession(
        id=scan_id,
        project_id=project.id,
        has_scale_reference=0,
        scale_px_to_mm=1.0,
        views_data={side.value: {"status": "pending"} for side in CaptureSide}
    )
    db.add(scan_session)
    await db.commit()

    return ScanCreateResponse(
        scan_id=scan_id,
        status="capturing",
        upload_urls=upload_urls,
        expires_in_seconds=900
    )


@router.post("/{scan_id}/views/{side}/confirm", response_model=ViewConfirmResponse)
async def confirm_view_keyframe(
    scan_id: str,
    side: str,
    payload: ViewConfirmRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Confirms uncompressed PNG upload for an individual perspective with client-side blur score.
    Document ID: PCAD-API-ADT-003 (FR-03 & FR-04).
    """
    session = await db.get(ScanSession, scan_id)
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")

    side_lower = side.lower()
    valid_sides = [s.value for s in CaptureSide]
    if side_lower not in valid_sides:
        raise HTTPException(status_code=400, detail=f"Invalid capture side '{side}'. Must be one of {valid_sides}")

    views = session.views_data or {}
    views[side_lower] = {
        "status": "confirmed",
        "blur_score": payload.blur_score,
        "is_sharp": payload.blur_score >= 120.0,
        "width_px": payload.width_px,
        "height_px": payload.height_px,
        "image_url": payload.image_url or f"/storage/uploads/{scan_id}/{side_lower}.png"
    }

    session.views_data = views
    await db.commit()

    completed_count = sum(1 for v in views.values() if v.get("status") == "confirmed")

    return ViewConfirmResponse(
        scan_id=scan_id,
        side=side_lower,
        status="confirmed",
        blur_score=payload.blur_score,
        is_sharp=payload.blur_score >= 120.0,
        views_completed=completed_count
    )


@router.post("/{scan_id}/calibrate")
async def calibrate_metric_scale(
    scan_id: str,
    spec: CalibrationSpec,
    db: AsyncSession = Depends(get_db)
):
    """
    Locks in 1:1 mm metric scale using 2-point caliper input or reference token.
    Document ID: PCAD-PRD-SRS-001 (FR-06) & PCAD-API-ADT-003.
    """
    session = await db.get(ScanSession, scan_id)
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")

    scale_factor = 1.0
    if spec.mm_per_unit and spec.mm_per_unit > 0:
        scale_factor = spec.mm_per_unit
    elif spec.point_a_px and spec.point_b_px:
        # Compute px distance and scale
        dx = spec.point_b_px[0] - spec.point_a_px[0]
        dy = spec.point_b_px[1] - spec.point_a_px[1]
        px_dist = (dx**2 + dy**2)**0.5
        if px_dist > 0:
            scale_factor = spec.known_length_mm / px_dist

    session.has_scale_reference = 1
    session.scale_px_to_mm = round(scale_factor, 5)

    views = session.views_data or {}
    views["_calibration"] = spec.model_dump()
    session.views_data = views

    await db.commit()

    return {
        "scan_id": scan_id,
        "status": "calibrated",
        "scale_px_to_mm": session.scale_px_to_mm,
        "calibration_spec": spec.model_dump()
    }


# Retain legacy upload-6-axis for direct multipart form testing
@router.post("/upload-6-axis", response_model=ScanSessionResponse)
async def upload_six_axis_scans(
    project_id: str = Form(...),
    has_scale_reference: bool = Form(False),
    marker_size_mm: float = Form(20.0),
    front: Optional[UploadFile] = File(None),
    back: Optional[UploadFile] = File(None),
    left: Optional[UploadFile] = File(None),
    right: Optional[UploadFile] = File(None),
    top: Optional[UploadFile] = File(None),
    bottom: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db)
):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(uuid.uuid4())
    session_upload_dir = settings.UPLOADS_DIR / session_id
    session_edge_dir = settings.PROCESSED_DIR / session_id
    session_upload_dir.mkdir(parents=True, exist_ok=True)
    session_edge_dir.mkdir(parents=True, exist_ok=True)

    views_files = {
        "front": front,
        "back": back,
        "left": left,
        "right": right,
        "top": top,
        "bottom": bottom
    }

    views_data: Dict[str, dict] = {}
    calculated_scale = 1.0

    saved_paths: Dict[str, str] = {}
    for view_name, upload_file in views_files.items():
        if upload_file:
            ext = os.path.splitext(upload_file.filename)[1] or ".png"
            dest_file = session_upload_dir / f"{view_name}{ext}"
            with open(dest_file, "wb") as buffer:
                shutil.copyfileobj(upload_file.file, buffer)
            saved_paths[view_name] = str(dest_file)

    if not saved_paths:
        raise HTTPException(status_code=400, detail="At least one view must be provided.")

    if has_scale_reference and "front" in saved_paths:
        scale_res = VisionEngine.calculate_scale_from_marker(saved_paths["front"], marker_size_mm)
        if scale_res:
            calculated_scale = scale_res

    for view_name, file_path in saved_paths.items():
        try:
            cv_result = VisionEngine.process_orthogonal_view(
                image_path=file_path,
                output_edge_dir=str(session_edge_dir),
                view_name=view_name,
                px_per_mm=calculated_scale
            )
            cv_result["image_url"] = f"/storage/uploads/{session_id}/{os.path.basename(file_path)}"
            cv_result["edge_url"] = f"/storage/processed_edges/{session_id}/{view_name}_edges.png"
            views_data[view_name] = cv_result
        except Exception as e:
            views_data[view_name] = {
                "view": view_name,
                "error": str(e),
                "primary_dimensions_mm": [60.0, 40.0],
                "features": []
            }

    scan_session = ScanSession(
        id=session_id,
        project_id=project_id,
        has_scale_reference=1 if has_scale_reference else 0,
        scale_px_to_mm=calculated_scale,
        views_data=views_data
    )
    db.add(scan_session)
    await db.commit()
    await db.refresh(scan_session)

    return scan_session


@router.get("/{session_id}", response_model=ScanSessionResponse)
async def get_scan_session(session_id: str, db: AsyncSession = Depends(get_db)):
    session = await db.get(ScanSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")
    return session
