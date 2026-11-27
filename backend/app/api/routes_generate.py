from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db, AsyncSessionLocal
from app.models.db_models import ScanSession, CadGeneration, AgentLog
from app.schemas.cad_schemas import GenerationTriggerRequest, CadGenerationResponse
from app.services.agents.orchestrator import AgentOrchestrator

router = APIRouter(prefix="/generate", tags=["Generation"])

async def run_pipeline_task(
    generation_id: str,
    scan_session_id: str,
    engine_type: str,
    refinement_prompt: str | None = None,
):
    """Background task to run multi-agent LangGraph pipeline with WebSocket broadcasting."""
    from app.main import broadcast_scan_event, ws_manager

    async with AsyncSessionLocal() as db:
        session = await db.get(ScanSession, scan_session_id)
        if not session:
            return

        async def ws_cb(msg: dict) -> None:
            await ws_manager.broadcast_to_generation(generation_id, msg)
            await broadcast_scan_event(scan_session_id, msg)

        orchestrator = AgentOrchestrator(db=db, ws_broadcast=ws_cb)
        await orchestrator.run_pipeline(
            generation_id=generation_id,
            views_data=session.views_data or {},
            scale_ratio=session.scale_px_to_mm or 1.0,
            engine_type=engine_type,
            scan_session_id=session.id,
            geometry_report_json=session.geometry_report_json,
            refinement_prompt=refinement_prompt,
        )


@router.post("/trigger", response_model=CadGenerationResponse)
async def trigger_cad_generation(
    req: GenerationTriggerRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(ScanSession, req.scan_session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")

    result = await db.execute(
        select(CadGeneration)
        .where(CadGeneration.scan_session_id == req.scan_session_id)
        .order_by(CadGeneration.version.desc())
    )
    latest = result.scalars().first()
    new_version = (latest.version + 1) if latest else 1

    generation = CadGeneration(
        scan_session_id=req.scan_session_id,
        version=new_version,
        status="pending",
    )
    db.add(generation)
    await db.commit()
    await db.refresh(generation)

    background_tasks.add_task(
        run_pipeline_task,
        generation.id,
        req.scan_session_id,
        req.target_engine,
        req.refinement_prompt,
    )

    return CadGenerationResponse(
        id=generation.id,
        scan_session_id=generation.scan_session_id,
        version=generation.version,
        status=generation.status,
        code=generation.code,
        step_file=generation.step_file,
        dxf_file=generation.dxf_file,
        stl_file=generation.stl_file,
        dimensions_mm=generation.dimensions_mm,
        error_log=generation.error_log,
        created_at=generation.created_at,
        agent_logs=[],
    )


@router.get("/{generation_id}", response_model=CadGenerationResponse)
async def get_generation_status(generation_id: str, db: AsyncSession = Depends(get_db)):
    generation = await db.get(CadGeneration, generation_id)
    if not generation:
        raise HTTPException(status_code=404, detail="Generation not found")

    log_results = await db.execute(
        select(AgentLog)
        .where(AgentLog.generation_id == generation_id)
        .order_by(AgentLog.created_at.asc())
    )
    logs = list(log_results.scalars().all())
    return CadGenerationResponse(
        id=generation.id,
        scan_session_id=generation.scan_session_id,
        version=generation.version,
        status=generation.status,
        code=generation.code,
        step_file=generation.step_file,
        dxf_file=generation.dxf_file,
        stl_file=generation.stl_file,
        dimensions_mm=generation.dimensions_mm,
        error_log=generation.error_log,
        created_at=generation.created_at,
        agent_logs=logs,
    )
