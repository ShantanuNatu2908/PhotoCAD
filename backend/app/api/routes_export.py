import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.models.db_models import CadGeneration

router = APIRouter(prefix="/export", tags=["Export"])

@router.get("/{generation_id}/{file_format}")
async def download_cad_file(
    generation_id: str,
    file_format: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Downloads industrial CAD file formats:
    - `step`: ISO 10303-21 STEP B-Rep file (AutoCAD, SolidWorks, FreeCAD)
    - `stl`: Stereolithography mesh (3D Printing / Slicing)
    - `dxf`: 2D AutoCAD Drawing Exchange Format
    """
    gen = await db.get(CadGeneration, generation_id)
    if not gen:
        raise HTTPException(status_code=404, detail="CAD Generation not found")

    file_format = file_format.lower().replace(".", "")
    filename = f"{generation_id}.{file_format}"
    file_path = settings.EXPORTS_DIR / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File {filename} not yet generated or compilation failed.")

    media_types = {
        "step": "application/step",
        "stp": "application/step",
        "stl": "model/stl",
        "dxf": "application/dxf"
    }

    return FileResponse(
        path=file_path,
        media_type=media_types.get(file_format, "application/octet-stream"),
        filename=f"PhotoCAD_{gen.id[:8]}.{file_format}"
    )
