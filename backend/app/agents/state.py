"""
PhotoCAD - Canonical LangGraph State & Event Schemas
Document ID: PCAD-LG-004 Section 2 / PCAD-API-ADT-003 Section 3
"""

from __future__ import annotations

from operator import add
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from app.schemas.adt import CSGFeatureTree, Open3DGeometryReport, ValidationMetrics


class PhotoCADGraphState(TypedDict, total=False):
    # Immutable Inputs
    scan_id: str
    masked_image_urls: Dict[str, str]           # front/back/left/right/top/bottom
    geometry_report: Open3DGeometryReport
    ply_local_path: Optional[str]
    user_edit_instruction: Optional[str]        # Populated during /refine calls

    # Intermediate Agent Artifacts
    spatial_analysis: Optional[Dict[str, Any]]  # Structured inventory from Node 1
    feature_tree: Optional[CSGFeatureTree]      # Structured Pydantic tree from Node 2
    retrieved_api_docs: List[Dict[str, str]]    # Output of pgvector/RAG lookup
    previous_code: Optional[str]                # Used to compute live unified code diffs
    current_code: Optional[str]                 # Output of Node 3
    code_diff: Optional[str]                    # Unified diff transmitted to UI over WS

    # Execution & Validation State
    compile_error_trace: Optional[str]          # Output of Node 4 on failure
    compile_retries: int                        # Inner loop counter (0..3)
    geometry_iterations: int                    # Outer loop counter (0..3)
    latest_artifacts: Dict[str, str]            # {"step": ..., "stl": ..., "dxf": ..., "py": ...}
    latest_dimensions_mm: Dict[str, float]
    validation_metrics: Optional[ValidationMetrics]

    # Best-Effort Tracking (Guarantees safest output if outer loop caps out)
    best_code: Optional[str]
    best_chamfer_mm: float
    best_artifact_keys: Dict[str, str]
    best_dimensions_mm: Dict[str, float]
    best_metrics: Optional[ValidationMetrics]
    final_status: str                           # completed | completed_with_warning | failed

    # Streaming Audit Trail (accumulates across nodes via operator.add)
    event_log: Annotated[List[Dict[str, Any]], add]
