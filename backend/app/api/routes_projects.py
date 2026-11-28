from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db
from app.core.security import get_current_tenant
from app.core.tenancy import apply_tenant, get_owned, scoped
from app.models.db_models import Project
from app.schemas.cad_schemas import ProjectCreate, ProjectResponse

router = APIRouter(
    prefix="/projects",
    tags=["Projects"],
    dependencies=[Depends(get_current_tenant)],
)

@router.post("", response_model=ProjectResponse)
async def create_project(data: ProjectCreate, db: AsyncSession = Depends(get_db)):
    project = apply_tenant(Project(
        name=data.name,
        description=data.description,
        unit=data.unit
    ))
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project

@router.get("", response_model=List[ProjectResponse])
async def list_projects(db: AsyncSession = Depends(get_db)):
    result = await db.execute(scoped(
        select(Project).order_by(Project.created_at.desc()), Project
    ))
    return result.scalars().all()

@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    project = await get_owned(db, Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
