import os
import shutil
import uuid
from typing import Optional, Dict
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.models.db_models import Project, ScanSession
from app.schemas.cad_schemas import ScanSessionResponse
from app.services.vision_engine import VisionEngine

router = APIRouter(prefix="/scans", tags=["Scans"])

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

    # 1. Save uploaded image files
    saved_paths: Dict[str, str] = {}
    for view_name, upload_file in views_files.items():
        if upload_file:
            ext = os.path.splitext(upload_file.filename)[1] or ".png"
            dest_file = session_upload_dir / f"{view_name}{ext}"
            with open(dest_file, "wb") as buffer:
                shutil.copyfileobj(upload_file.file, buffer)
            saved_paths[view_name] = str(dest_file)

    # If front wasn't uploaded or demo mode, create synthetic views if needed
    if not saved_paths:
        raise HTTPException(status_code=400, detail="At least one view (e.g. front or top) must be provided.")

    # 2. Check for ArUco / Scale calibration
    if has_scale_reference and "front" in saved_paths:
        scale_res = VisionEngine.calculate_scale_from_marker(saved_paths["front"], marker_size_mm)
        if scale_res:
            calculated_scale = scale_res

    # 3. Process Computer Vision Edge & Contour Detection for each view
    for view_name, file_path in saved_paths.items():
        try:
            cv_result = VisionEngine.process_orthogonal_view(
                image_path=file_path,
                output_edge_dir=str(session_edge_dir),
                view_name=view_name,
                px_per_mm=calculated_scale
            )
            # Add relative web URLs
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

    # Fill in missing views symmetrically if user provided partial (e.g. 2 or 3 views)
    for expected_view in ["front", "back", "left", "right", "top", "bottom"]:
        if expected_view not in views_data:
            fallback_source = "front" if expected_view in ["back", "left", "right"] else "top"
            if fallback_source in views_data:
                views_data[expected_view] = views_data[fallback_source].copy()
                views_data[expected_view]["view"] = expected_view

    # 4. Save ScanSession record
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
