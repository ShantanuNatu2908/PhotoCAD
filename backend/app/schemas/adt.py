"""
PhotoCAD - Abstract Data Types (ADTs) & Canonical Data Contracts
Document ID: PCAD-API-ADT-003
Version: 1.0.0

These Pydantic v2 schemas govern the mathematical boundary between:
1. Open3D Serverless GPU Workers (gpu_workers/)
2. LangGraph Multi-Agent Orchestrator (backend/app/agents/)
3. FastAPI Control Plane & Client UI (frontend/)
"""

from enum import Enum
from typing import Literal, Optional, List, Dict, Tuple, Union
from pydantic import BaseModel, Field, ConfigDict

class CaptureSide(str, Enum):
    """The 6 orthogonal perspectives required for full volumetric capture."""
    FRONT = "front"
    BACK = "back"
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"


class CalibrationSpec(BaseModel):
    """Specification for establishing real-world millimeter scale (1:1 mm)."""
    model_config = ConfigDict(extra="forbid")

    mode: Literal["aruco_token", "id1_card", "known_dimension"]
    reference_side: CaptureSide
    known_length_mm: float = Field(..., gt=1.0, le=2000.0, description="Real-world reference length in mm")
    point_a_px: Optional[Tuple[float, float]] = Field(None, description="Pixel coordinate (X, Y) of start point")
    point_b_px: Optional[Tuple[float, float]] = Field(None, description="Pixel coordinate (X, Y) of end point")
    mm_per_unit: Optional[float] = Field(None, gt=0.0, description="Calculated metric scale factor")


class DetectedPlane(BaseModel):
    """Planar surface detected via Open3D RANSAC plane segmentation."""
    model_config = ConfigDict(extra="forbid")

    plane_id: str = Field(..., description="Unique ID for planar face e.g. 'plane_top_01'")
    normal: Tuple[float, float, float] = Field(..., description="Unit surface normal vector (nx, ny, nz)")
    centroid_mm: Tuple[float, float, float] = Field(..., description="Center of planar segment in mm (X, Y, Z)")
    area_mm2: float = Field(..., ge=0.0, description="Estimated surface area in square millimeters")
    inlier_ratio: float = Field(..., ge=0.0, le=1.0, description="Ratio of point cloud points belonging to plane")


class DetectedCylinder(BaseModel):
    """Cylindrical hole or boss detected via RANSAC / normal clustering."""
    model_config = ConfigDict(extra="forbid")

    cylinder_id: str = Field(..., description="Unique ID e.g. 'cyl_center_hole_01'")
    kind: Literal["boss", "through_hole", "blind_hole"] = Field(..., description="Classification of cylinder")
    axis_origin_mm: Tuple[float, float, float] = Field(..., description="Point on the cylinder axis in mm")
    axis_direction: Tuple[float, float, float] = Field(..., description="Unit vector of the central axis (dx, dy, dz)")
    radius_mm: float = Field(..., gt=0.1, description="Cylinder radius in mm")
    depth_mm: float = Field(..., gt=0.1, description="Extruded depth or through length in mm")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Detection confidence score")


class Open3DGeometryReport(BaseModel):
    """
    Structured geometric ground-truth produced by Open3D registration
    and primitive decomposition. Passed to LangGraph Node 1.
    """
    model_config = ConfigDict(extra="forbid")

    scan_id: str = Field(..., description="Parent scan session ID")
    units: Literal["mm"] = "mm"
    point_count: int = Field(..., ge=100, description="Total points in fused point cloud")
    icp_fitness_score: float = Field(..., ge=0.0, le=1.0, description="ICP multi-view alignment fitness")
    icp_inlier_rmse_mm: float = Field(..., ge=0.0, description="Root-mean-square error of inlier alignment in mm")
    bounding_box_mm: Tuple[float, float, float] = Field(..., description="Oriented bounding envelope (X, Y, Z) in mm")
    principal_axes: List[Tuple[float, float, float]] = Field(..., min_length=3, max_length=3, description="Eigenvectors of inertia")
    symmetry_planes: List[Literal["XY", "YZ", "XZ"]] = Field(default_factory=list, description="Detected planes of symmetry")
    planes: List[DetectedPlane] = Field(default_factory=list, description="List of detected planar faces")
    cylinders: List[DetectedCylinder] = Field(default_factory=list, description="List of detected cylindrical features")
    ply_object_key: str = Field(..., description="Cloudflare R2 object key for the fused .PLY point cloud")


class FeatureStep(BaseModel):
    """A discrete Constructive Solid Geometry (CSG) modeling step in build123d."""
    model_config = ConfigDict(extra="forbid")

    step_index: int = Field(..., ge=1, description="Sequential order of operation execution")
    operation: Literal[
        "base_extrude", "cut_extrude", "revolve",
        "hole", "fillet", "chamfer", "mirror", "pattern"
    ] = Field(..., description="CAD kernel operation primitive")
    target_plane: str = Field(..., description="Datum plane or face reference, e.g. 'XY', '>Z', 'face_top'")
    parameters_mm: Dict[str, Union[float, List[float], str]] = Field(
        ..., description="Exact parametric dimensions in millimeters"
    )
    rationale: str = Field(..., description="Engineering explanation of why this step is sequenced here")


class CSGFeatureTree(BaseModel):
    """
    Ordered B-Rep construction plan generated by LangGraph Node 2 (Parametric Architect).
    Translates raw scan measurements into parameterized CAD steps.
    """
    model_config = ConfigDict(extra="forbid")

    part_summary: str = Field(..., description="High-level engineering classification of the part")
    coordinate_origin: Literal["center_bottom", "center_centroid"] = "center_bottom"
    global_parameters_mm: Dict[str, float] = Field(
        ..., description="Uppercase named parametric constants in mm (e.g. LENGTH_MM, HOLE_DIA_MM)"
    )
    steps: List[FeatureStep] = Field(..., min_length=1, description="Sequential modeling instructions")


class ValidationMetrics(BaseModel):
    """
    Computed by LangGraph Node 5 (Geometric Validator) comparing
    the compiled .STEP B-Rep mesh against the fused Open3D scan.
    """
    model_config = ConfigDict(extra="forbid")

    is_watertight: bool = Field(..., description="True if solid has zero open or non-manifold edges")
    volume_mm3: float = Field(..., ge=0.0, description="Volume of the solid in cubic millimeters")
    surface_area_mm2: float = Field(..., ge=0.0, description="Total surface area in square millimeters")
    chamfer_mean_mm: float = Field(..., ge=0.0, description="Mean bidirectional Chamfer Distance in mm")
    chamfer_p95_mm: float = Field(..., ge=0.0, description="95th-percentile Chamfer Distance in mm")
    bbox_delta_mm: Tuple[float, float, float] = Field(..., description="Bounding box delta (dx, dy, dz) vs scan in mm")
    passed_tolerance: bool = Field(..., description="True if chamfer_mean_mm <= 1.0mm and is_watertight is True")
    discrepancy_notes: List[str] = Field(
        default_factory=list, description="Localized feedback for Outer Loop geometric refinement"
    )
