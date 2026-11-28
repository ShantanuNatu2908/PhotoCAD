import os
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cloud_auth import (
    detect_active_pipeline_engines,
    is_modal_configured,
    is_valid_secret,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_tenant
from app.core.tenancy import apply_tenant, find_owned, get_owned, scoped
from app.models.db_models import AgentLog, CadGeneration, Project, ScanSession
from app.schemas.adt import CalibrationSpec, CaptureSide
from app.schemas.cad_schemas import ScanSessionResponse
from app.services.cv_pipeline_service import CVPipelineError, CVPipelineService
from app.services.r2_storage import r2_storage

router = APIRouter(prefix="/scans", tags=["Scans"], dependencies=[Depends(get_current_tenant)])

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
    manual_override: bool = False


@router.get("")
async def list_scan_sessions(db: AsyncSession = Depends(get_db)):
    """Lists all saved scan sessions and their latest CAD generation summary for the Projects & Scans dashboard."""
    from sqlalchemy.future import select

    scans_res = await db.execute(scoped(
        select(ScanSession).order_by(ScanSession.created_at.desc()), ScanSession
    ))
    scans = list(scans_res.scalars().all())
    proj_res = await db.execute(scoped(select(Project), Project))
    proj_map = {p.id: p for p in proj_res.scalars().all()}
    gen_res = await db.execute(scoped(
        select(CadGeneration).order_by(CadGeneration.version.desc()), CadGeneration
    ))
    latest_gen_map: Dict[str, CadGeneration] = {}
    for g in gen_res.scalars().all():
        if g.scan_session_id not in latest_gen_map:
            latest_gen_map[g.scan_session_id] = g

    items = []
    for s in scans:
        views = s.views_data or {}
        confirmed_sides = [
            side.value
            for side in CaptureSide
            if isinstance(views.get(side.value), dict) and views[side.value].get("status") == "confirmed"
        ]
        thumb_url = None
        for side in ("front", "left", "top", "right", "back", "bottom"):
            if isinstance(views.get(side), dict) and views[side].get("image_url"):
                thumb_url = views[side].get("masked_url") or views[side].get("image_url")
                break
        proj = proj_map.get(s.project_id)
        lg = latest_gen_map.get(s.id)
        items.append({
            "scan_id": s.id,
            "project_id": s.project_id,
            "project_name": proj.name if proj else "PhotoCAD Scan",
            "status": s.status,
            "confirmed_sides": confirmed_sides,
            "views_count": len(confirmed_sides),
            "ply_url": s.ply_file,
            "thumbnail_url": thumb_url,
            "geometry_report": s.geometry_report_json,
            "calibration": s.calibration_json,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "latest_generation": (
                {
                    "id": lg.id,
                    "scan_session_id": lg.scan_session_id,
                    "version": lg.version,
                    "status": lg.status,
                    "code": lg.code,
                    "step_file": lg.step_file,
                    "stl_file": lg.stl_file,
                    "dxf_file": lg.dxf_file,
                    "dimensions_mm": lg.dimensions_mm,
                    "created_at": lg.created_at.isoformat() if lg.created_at else None,
                }
                if lg
                else None
            ),
        })
    return items

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
    project = await find_owned(db, Project, payload.project_id)
    if not project:
        # Auto-create fallback project if not found in dev mode
        project = apply_tenant(Project(id=payload.project_id, name=payload.title, unit="mm"))
        db.add(project)
        await db.commit()

    scan_id = str(uuid.uuid4())
    session_upload_dir = settings.UPLOADS_DIR / scan_id
    session_upload_dir.mkdir(parents=True, exist_ok=True)

    # In cloud mode issue SigV4 R2 PUT URLs; in local dev issue backend PUT upload URLs
    public_api_base = os.getenv("PUBLIC_API_BASE", "http://localhost:8000").rstrip("/")
    upload_urls = {
        side.value: (
            r2_storage.generate_presigned_url(f"uploads/{scan_id}/{side.value}.png", method="PUT", expires_in=900)
            if r2_storage.is_r2_configured
            else f"{public_api_base}/api/scans/{scan_id}/views/{side.value}/upload"
        )
        for side in CaptureSide
    }

    scan_session = apply_tenant(ScanSession(
        id=scan_id,
        project_id=project.id,
        status="capturing",
        has_scale_reference=0,
        scale_px_to_mm=1.0,
        views_data={side.value: {"status": "pending"} for side in CaptureSide}
    ))
    db.add(scan_session)
    await db.commit()

    return ScanCreateResponse(
        scan_id=scan_id,
        status="capturing",
        upload_urls=upload_urls,
        expires_in_seconds=900
    )


@router.put("/{scan_id}/views/{side}/upload")
async def upload_raw_keyframe_bytes(
    scan_id: str,
    side: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Dev-mode direct binary PUT endpoint mirroring Cloudflare R2 pre-signed PUT uploads.
    Persists raw uncompressed .PNG bytes under storage/uploads/{scan_id}/{side}.png.
    """
    session = await get_owned(db, ScanSession, scan_id, detail="Scan session not found")
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")

    side_lower = side.lower()
    valid_sides = [s.value for s in CaptureSide]
    if side_lower not in valid_sides:
        raise HTTPException(status_code=400, detail=f"Invalid capture side '{side}'. Must be one of {valid_sides}")

    raw_bytes = await request.body()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Empty PNG payload")

    object_key = f"uploads/{scan_id}/{side_lower}.png"
    r2_storage.save_local_bytes(object_key, raw_bytes)

    return {
        "scan_id": scan_id,
        "side": side_lower,
        "bytes_written": len(raw_bytes),
        "image_url": f"/storage/{object_key}",
    }


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
    session = await get_owned(db, ScanSession, scan_id, detail="Scan session not found")
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")

    side_lower = side.lower()
    valid_sides = [s.value for s in CaptureSide]
    if side_lower not in valid_sides:
        raise HTTPException(status_code=400, detail=f"Invalid capture side '{side}'. Must be one of {valid_sides}")

    is_sharp = bool(payload.manual_override or payload.blur_score >= 120.0)
    view_status = "confirmed" if is_sharp else "rejected_blur"

    views = dict(session.views_data or {})
    views[side_lower] = {
        "status": view_status,
        "blur_score": payload.blur_score,
        "is_sharp": is_sharp,
        "width_px": payload.width_px,
        "height_px": payload.height_px,
        "image_url": payload.image_url or f"/storage/uploads/{scan_id}/{side_lower}.png"
    }

    session.views_data = views
    await db.commit()

    completed_count = sum(
        1 for k, v in views.items()
        if not k.startswith("_") and isinstance(v, dict) and v.get("status") == "confirmed"
    )

    return ViewConfirmResponse(
        scan_id=scan_id,
        side=side_lower,
        status=view_status,
        blur_score=payload.blur_score,
        is_sharp=is_sharp,
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
    session = await get_owned(db, ScanSession, scan_id, detail="Scan session not found")
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")

    scale_factor = 1.0
    if spec.mm_per_unit and spec.mm_per_unit > 0:
        scale_factor = spec.mm_per_unit
    elif spec.point_a_px and spec.point_b_px:
        dx = spec.point_b_px[0] - spec.point_a_px[0]
        dy = spec.point_b_px[1] - spec.point_a_px[1]
        px_dist = (dx**2 + dy**2)**0.5
        if px_dist > 0:
            scale_factor = spec.known_length_mm / px_dist

    spec_dict = spec.model_dump()
    if spec_dict.get("mm_per_unit") is None:
        spec_dict["mm_per_unit"] = round(scale_factor, 5)

    session.status = "calibrated"
    session.has_scale_reference = 1
    session.scale_px_to_mm = round(scale_factor, 5)
    session.calibration_json = spec_dict

    views = dict(session.views_data or {})
    views["_calibration"] = spec_dict
    session.views_data = views

    await db.commit()

    return {
        "scan_id": scan_id,
        "status": "calibrated",
        "scale_px_to_mm": session.scale_px_to_mm,
        "calibration_spec": spec_dict
    }


class StrictCloudOptions(BaseModel):
    strict_cloud: bool = False


@router.post("/{scan_id}/fuse")
async def trigger_cv_3d_fusion(
    scan_id: str,
    payload: Optional[StrictCloudOptions] = Body(default=None),
    db: AsyncSession = Depends(get_db)
):
    """
    Phase 3 Entrypoint: Executes SAM 2.1 Masking -> Depth Anything -> Open3D Multi-View Fusion
    (via Modal L4 GPU when configured or Zero-Heat visual hull fallback in local dev).
    """
    session = await get_owned(db, ScanSession, scan_id, detail="Scan session not found")
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")

    from app.main import broadcast_scan_event

    async def ws_cb(msg: Dict[str, Any]) -> None:
        await broadcast_scan_event(scan_id, msg)

    session.status = "processing_cv"
    await db.commit()

    try:
        result = await CVPipelineService.run_cv_fusion(
            scan_id=scan_id,
            views_data=session.views_data or {},
            has_scale_reference=bool(session.has_scale_reference),
            calibration_spec=session.calibration_json,
            ws_broadcast=ws_cb,
            strict_cloud=bool(payload and payload.strict_cloud),
        )
    except CVPipelineError as exc:
        session.status = "failed"
        await db.commit()
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "request_id": f"req_{uuid.uuid4().hex[:12]}",
                }
            },
        )

    views = dict(session.views_data or {})
    for side, masked_url in (result.get("masked_urls") or {}).items():
        if side in views and isinstance(views[side], dict):
            updated_view = dict(views[side])
            updated_view["masked_url"] = masked_url
            views[side] = updated_view

    session.views_data = views
    session.geometry_report_json = result["geometry_report"]
    session.ply_file = result["ply_url"]
    session.status = "fused"
    await db.commit()

    return {
        "scan_id": scan_id,
        "status": "fused",
        "execution_mode": result["execution_mode"],
        "ply_url": result["ply_url"],
        "masked_urls": result["masked_urls"],
        "geometry_report": result["geometry_report"],
        "telemetry": result["telemetry"],
        "active_models": (result.get("telemetry") or {}).get("active_models") or detect_active_pipeline_engines(),
    }


@router.get("/{scan_id}/geometry")
async def get_scan_geometry_report(
    scan_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Returns the fused Open3DGeometryReport ADT and downloadable .PLY preview URL."""
    session = await get_owned(db, ScanSession, scan_id, detail="Scan session not found")
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")

    if not session.geometry_report_json:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "FUSION_NOT_READY",
                    "message": "3D geometry report has not been generated yet. Call POST /fuse first.",
                    "details": {"scan_id": scan_id, "status": session.status},
                    "request_id": f"req_{uuid.uuid4().hex[:12]}",
                }
            },
        )

    views = session.views_data or {}
    masked_urls = {
        side.value: views[side.value].get("masked_url")
        for side in CaptureSide
        if side.value in views and isinstance(views[side.value], dict) and views[side.value].get("masked_url")
    }

    return {
        "scan_id": scan_id,
        "status": session.status,
        "ply_url": session.ply_file,
        "masked_urls": masked_urls,
        "geometry_report": session.geometry_report_json,
    }


class RefineRequest(BaseModel):
    base_revision: int = Field(default=1, ge=1)
    instruction: str = Field(..., min_length=3, max_length=1000)


async def _run_scan_cad_generation(
    scan_id: str,
    session: ScanSession,
    db: AsyncSession,
    refinement_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Creates a new CadGeneration revision, executes the 5-node LangGraph pipeline, and returns artifacts + metrics."""
    from sqlalchemy.future import select

    from app.main import broadcast_scan_event
    from app.services.agents.orchestrator import AgentOrchestrator

    res = await db.execute(scoped(
        select(CadGeneration).where(CadGeneration.scan_session_id == scan_id).order_by(CadGeneration.version.desc()),
        CadGeneration,
    ))
    latest = res.scalars().first()
    version = (latest.version + 1) if latest else 1

    gen = apply_tenant(CadGeneration(scan_session_id=scan_id, version=version, status="pending"))
    db.add(gen)
    await db.commit()
    await db.refresh(gen)

    async def ws_cb(msg: Dict[str, Any]) -> None:
        await broadcast_scan_event(scan_id, msg)

    orchestrator = AgentOrchestrator(db=db, ws_broadcast=ws_cb)
    updated_gen = await orchestrator.run_pipeline(
        generation_id=gen.id,
        views_data=session.views_data or {},
        scale_ratio=session.scale_px_to_mm or 1.0,
        engine_type="build123d",
        scan_session_id=scan_id,
        geometry_report_json=session.geometry_report_json,
        refinement_prompt=refinement_prompt,
    )

    log_results = await db.execute(
        select(AgentLog)
        .where(AgentLog.generation_id == updated_gen.id)
        .order_by(AgentLog.created_at.asc())
    )
    logs = list(log_results.scalars().all())

    return {
        "scan_id": scan_id,
        "generation_id": updated_gen.id,
        "revision": updated_gen.version,
        "status": updated_gen.status,
        "dimensions_mm": updated_gen.dimensions_mm,
        "code": updated_gen.code,
        "artifacts": {
            "step_url": updated_gen.step_file,
            "stl_url": updated_gen.stl_file,
            "dxf_url": updated_gen.dxf_file,
            "py_url": f"/api/export/{updated_gen.id}/py",
        },
        "validation_metrics": getattr(updated_gen, "_latest_validation_metrics", None),
        "active_models": detect_active_pipeline_engines(),
        "agent_logs": [
            {
                "id": log.id,
                "agent_name": log.agent_name,
                "log_type": log.log_type,
                "message": log.message,
                "created_at": log.created_at.isoformat() if log.created_at else "",
            }
            for log in logs
        ],
    }


@router.post("/{scan_id}/generate")
async def generate_cad_from_scan(
    scan_id: str,
    payload: Optional[StrictCloudOptions] = Body(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Runs Phase 4 5-Node LangGraph B-Rep Synthesis synchronously or via scan route per PCAD-API-ADT-003."""
    if payload and payload.strict_cloud:
        gemini_ok = is_valid_secret(settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", ""))
        anthropic_ok = is_valid_secret(os.getenv("ANTHROPIC_API_KEY", ""))
        if not is_modal_configured() or not (gemini_ok or anthropic_ok):
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "CLOUD_HIGH_ACCURACY_NOT_READY",
                        "message": "Strict Cloud High-Accuracy Mode requires Modal GPU (`modal setup` or tokens) plus GEMINI_API_KEY or ANTHROPIC_API_KEY in `.env`.",
                        "details": {"active_models": detect_active_pipeline_engines()},
                    }
                },
            )

    session = await get_owned(db, ScanSession, scan_id, detail="Scan session not found")
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")
    return await _run_scan_cad_generation(scan_id=scan_id, session=session, db=db)


@router.get("/{scan_id}/revisions/{rev}/artifacts")
async def get_revision_artifacts(
    scan_id: str,
    rev: int,
    db: AsyncSession = Depends(get_db),
):
    """Retrieves .STEP, .DXF, .STL, .PLY, and editable build123d .py URLs for a CAD revision."""
    from sqlalchemy.future import select

    session = await get_owned(db, ScanSession, scan_id, detail="Scan session not found")
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")

    res = await db.execute(scoped(
        select(CadGeneration).where(
            CadGeneration.scan_session_id == scan_id,
            CadGeneration.version == rev,
        ),
        CadGeneration,
    ))
    gen = res.scalars().first()
    if not gen:
        raise HTTPException(status_code=404, detail=f"Revision {rev} not found")

    return {
        "scan_id": scan_id,
        "generation_id": gen.id,
        "revision": gen.version,
        "status": gen.status,
        "dimensions_mm": gen.dimensions_mm,
        "artifacts": {
            "step_url": f"/api/export/{gen.id}/step",
            "dxf_url": f"/api/export/{gen.id}/dxf",
            "stl_url": f"/api/export/{gen.id}/stl",
            "py_url": f"/api/export/{gen.id}/py",
            "ply_url": session.ply_file,
        },
    }


@router.post("/{scan_id}/refine")
async def refine_cad_revision(
    scan_id: str,
    payload: RefineRequest,
    db: AsyncSession = Depends(get_db),
):
    """Resumes the saved LangGraph thread checkpoint to apply parametric edits in <15s (PCAD-LG-004)."""
    session = await get_owned(db, ScanSession, scan_id, detail="Scan session not found")
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")
    return await _run_scan_cad_generation(
        scan_id=scan_id,
        session=session,
        db=db,
        refinement_prompt=payload.instruction,
    )


@router.get("/{session_id}", response_model=ScanSessionResponse)
async def get_scan_session(session_id: str, db: AsyncSession = Depends(get_db)):
    session = await get_owned(db, ScanSession, session_id, detail="Scan session not found")
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")
    return session
