from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db, AsyncSessionLocal
from app.models.db_models import ScanSession, CadGeneration, AgentLog
from app.schemas.cad_schemas import GenerationTriggerRequest, CadGenerationResponse
from app.services.agents.orchestrator import AgentOrchestrator

router = APIRouter(prefix="/generate", tags=["Generation"])

async def run_pipeline_task(generation_id: str, scan_session_id: str, engine_type: str):
    """Background task to run multi-agent pipeline with its own DB session."""
    async with AsyncSessionLocal() as db:
        session = await db.get(ScanSession, scan_session_id)
        if not session:
            return
            
        orchestrator = AgentOrchestrator(db=db)
        await orchestrator.run_pipeline(
            generation_id=generation_id,
            views_data=session.views_data or {},
            scale_ratio=session.scale_px_to_mm or 1.0,
            engine_type=engine_type
        )

@router.post("/trigger", response_model=CadGenerationResponse)
async def trigger_cad_generation(
    req: GenerationTriggerRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    session = await db.get(ScanSession, req.scan_session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")

    # Get latest version number
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
        status="pending"
    )
    db.add(generation)
    await db.commit()
    await db.refresh(generation)

    # Launch multi-agent pipeline as a background task
    background_tasks.add_task(
        run_pipeline_task,
        generation.id,
        req.scan_session_id,
        req.target_engine
    )

    return generation

@router.get("/{generation_id}", response_model=CadGenerationResponse)
async def get_generation_status(generation_id: str, db: AsyncSession = Depends(get_db)):
    generation = await db.get(CadGeneration, generation_id)
    if not generation:
        raise HTTPException(status_code=404, detail="Generation not found")
        
    # Load associated agent logs
    log_results = await db.execute(
        select(AgentLog)
        .where(AgentLog.generation_id == generation_id)
        .order_by(AgentLog.created_at.asc())
    )
    generation.agent_logs = log_results.scalars().all()
    return generation
