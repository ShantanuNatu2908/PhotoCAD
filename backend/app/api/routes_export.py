from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.cad.interop_verifier import InteropVerifier
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_tenant
from app.core.tenancy import get_owned
from app.models.db_models import CadGeneration

router = APIRouter(prefix="/export", tags=["Export"], dependencies=[Depends(get_current_tenant)])


@router.get("/{generation_id}/interop-report")
async def get_cad_interoperability_report(
    generation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Runs AutoCAD, Fusion 360, and SolidWorks structural & 1:1 mm compatibility verification
    against exported .STEP, .DXF, and .STL files for a completed CAD generation.
    """
    gen = await get_owned(db, CadGeneration, generation_id, detail="CAD Generation not found")
    if not gen:
        raise HTTPException(status_code=404, detail="CAD Generation not found")

    step_path = settings.EXPORTS_DIR / f"{generation_id}.step"
    dxf_path = settings.EXPORTS_DIR / f"{generation_id}.dxf"
    stl_path = settings.EXPORTS_DIR / f"{generation_id}.stl"

    report = InteropVerifier.verify_bundle(step_path, dxf_path, stl_path)
    return {
        "generation_id": generation_id,
        "dimensions_mm": gen.dimensions_mm,
        **report.model_dump(),
    }

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
    gen = await get_owned(db, CadGeneration, generation_id, detail="CAD Generation not found")
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
        "dxf": "application/dxf",
        "py": "text/x-python",
    }

    return FileResponse(
        path=file_path,
        media_type=media_types.get(file_format, "application/octet-stream"),
        filename=f"PhotoCAD_{gen.id[:8]}.{file_format}"
    )
