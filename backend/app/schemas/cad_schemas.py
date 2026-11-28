from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# --- Project Schemas ---
class ProjectCreate(BaseModel):
    name: str = Field(..., max_length=128, json_schema_extra={"example": "Mounting Bracket V1"})
    description: Optional[str] = Field(
        None,
        json_schema_extra={"example": "6-axis reverse engineering of an aluminum bracket"},
    )
    unit: str = Field("mm", json_schema_extra={"example": "mm"})

class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str]
    unit: str
    created_at: datetime
    updated_at: datetime

# --- Scan Session Schemas ---
class SixAxisUploadData(BaseModel):
    project_id: str
    has_scale_reference: bool = False
    scale_px_to_mm: Optional[float] = 1.0

class ViewDetail(BaseModel):
    image_url: str
    edge_url: Optional[str] = None
    width_px: int
    height_px: int
    contours_count: int
    bounding_box_mm: Optional[List[float]] = None

class ScanSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    status: Optional[str] = "capturing"
    has_scale_reference: int
    scale_px_to_mm: float
    calibration_json: Optional[Dict[str, Any]] = None
    geometry_report_json: Optional[Dict[str, Any]] = None
    ply_file: Optional[str] = None
    views_data: Dict[str, Any]
    created_at: datetime

# --- Generation Schemas ---
class GenerationTriggerRequest(BaseModel):
    scan_session_id: str
    target_engine: str = Field("build123d", json_schema_extra={"example": "build123d"})
    refinement_prompt: Optional[str] = None

class AgentLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_name: str
    log_type: str
    message: str
    created_at: datetime

class CadGenerationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    scan_session_id: str
    version: int
    status: str
    code: Optional[str]
    step_file: Optional[str]
    dxf_file: Optional[str]
    stl_file: Optional[str]
    dimensions_mm: Optional[Dict[str, float]]
    error_log: Optional[str]
    created_at: datetime
    agent_logs: Optional[List[AgentLogResponse]] = []
