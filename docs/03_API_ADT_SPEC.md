# PhotoCAD — API, WebSocket & ADT Data Contract

**Document ID:** `PCAD-API-ADT-003`  
**Version:** `1.0.0`  
**Status:** Approved for Development (Wave 1)  

---

## 1. API Design Conventions

* **Base URL:** `/api/v1`
* **Authentication:** Bearer JWT issued by Supabase Auth (`Authorization: Bearer <token>`).
* **Content Type:** `application/json; charset=utf-8` (binary assets transfer directly via Cloudflare R2 pre-signed URLs).
* **Idempotency:** State-mutating `POST` requests accept an optional `Idempotency-Key` UUID header.
* **Standard Error Envelope:**

~~~json
{
  "error": {
    "code": "CALIBRATION_MISSING",
    "message": "Metric scale calibration must be completed before starting 3D fusion.",
    "details": { "scan_id": "scn_01J9X..." },
    "request_id": "req_88a7f1..."
  }
}
~~~

---

## 2. REST API Endpoints

| Method | Endpoint | Purpose | Auth |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/scans` | Create a new scan session and issue 6 pre-signed R2 `PUT` URLs. | Required |
| `GET` | `/api/v1/scans/{scan_id}` | Fetch current scan status, calibration info, and revision list. | Required |
| `POST` | `/api/v1/scans/{scan_id}/views/{side}/confirm` | Confirm `.PNG` upload for a specific side (`front`, `back`, `left`, `right`, `top`, `bottom`) with client blur score. | Required |
| `POST` | `/api/v1/scans/{scan_id}/calibrate` | Submit ArUco reference metadata or 2-point known dimension in $\text{mm}$. | Required |
| `POST` | `/api/v1/scans/{scan_id}/generate` | Trigger the async Cloud GPU Fusion $\rightarrow$ LangGraph CAD pipeline. | Required |
| `POST` | `/api/v1/scans/{scan_id}/refine` | Submit a natural-language parametric edit to resume the LangGraph checkpoint and generate a new CAD revision. | Required |
| `GET` | `/api/v1/scans/{scan_id}/revisions/{rev}/artifacts` | Retrieve short-lived signed download URLs for `.STEP`, `.DXF`, `.STL`, `.PLY`, and `.py` files. | Required |
| `DELETE` | `/api/v1/scans/{scan_id}` | Immediately purge scan metadata and all associated R2 blobs. | Required |

### Key Request / Response Payloads

#### `POST /api/v1/scans` — Response (`201 Created`)
~~~json
{
  "scan_id": "scn_01J9X4K2M8P9Q",
  "status": "capturing",
  "upload_urls": {
    "front": "https://r2.photocad.app/raw/scn_.../front.png?X-Amz-Signature=...",
    "back": "https://r2.photocad.app/raw/scn_.../back.png?X-Amz-Signature=...",
    "left": "https://r2.photocad.app/raw/scn_.../left.png?X-Amz-Signature=...",
    "right": "https://r2.photocad.app/raw/scn_.../right.png?X-Amz-Signature=...",
    "top": "https://r2.photocad.app/raw/scn_.../top.png?X-Amz-Signature=...",
    "bottom": "https://r2.photocad.app/raw/scn_.../bottom.png?X-Amz-Signature=..."
  },
  "expires_in_seconds": 900
}
~~~

#### `POST /api/v1/scans/{scan_id}/calibrate` — Request
~~~json
{
  "mode": "known_dimension",
  "reference_side": "front",
  "point_a_px": [240.5, 512.0],
  "point_b_px": [890.0, 512.0],
  "known_length_mm": 64.5
}
~~~

#### `POST /api/v1/scans/{scan_id}/refine` — Request
~~~json
{
  "base_revision": 1,
  "instruction": "Change the 4 corner mounting holes from 5 mm diameter to 6.5 mm diameter and add a 1.5 mm chamfer to the top outer perimeter."
}
~~~

---

## 3. WebSocket Real-Time Event Contract

**Endpoint:** `wss://api.photocad.app/ws/v1/scans/{scan_id}?token=<jwt>`

All server-to-client messages adhere to a strict envelope:

~~~json
{
  "event": "<event_name>",
  "scan_id": "scn_01J9X4K2M8P9Q",
  "timestamp": "2026-11-24T07:15:32.104Z",
  "progress_pct": 55,
  "payload": {}
}
~~~

### Event Catalog

| Event Name | `progress_pct` | Payload Fields | Trigger Condition |
| :--- | :--- | :--- | :--- |
| `cv_segmentation_started` | `10` | `{ "views_count": 6 }` | Modal GPU worker begins SAM masking. |
| `cv_fusion_completed` | `35` | `{ "point_count": 148200, "ply_preview_url": "...", "bbox_mm": [64.5, 42.0, 18.2] }` | Depth Anything 3 + Open3D alignment finishes. |
| `agent_node_started` | `40`–`85` | `{ "node": "cad_synthesizer", "iteration": 1, "message": "Generating build123d B-Rep code..." }` | Any LangGraph node begins execution. |
| `cad_compile_error` | `65` | `{ "attempt": 1, "max_attempts": 3, "error_summary": "OCP BRep_API failure on fillet radius" }` | Sandbox compiler fails; Inner Self-Healing Loop triggers. |
| `validation_completed` | `88` | `{ "iteration": 1, "chamfer_mean_mm": 0.64, "chamfer_p95_mm": 1.12, "passed": true }` | Open3D Chamfer Validator compares `.STEP` vs scan. |
| `pipeline_completed` | `100` | `{ "revision": 1, "status": "completed", "artifacts": { "step_url": "...", "dxf_url": "...", "stl_url": "...", "py_url": "..." } }` | Final verified CAD assets published to R2. |
| `pipeline_failed` | `100` | `{ "code": "FUSION_LOW_OVERLAP", "message": "Top and Bottom views failed alignment. Please retake." }` | Unrecoverable error after exhausting retries. |

---

## 4. Abstract Data Types (ADTs — Pydantic v2 Models)

These canonical schemas govern the boundary between **Open3D GPU Workers**, **LangGraph Agents**, and **FastAPI**:

~~~python
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field

class CaptureSide(str, Enum):
    FRONT = "front"
    BACK = "back"
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"

class CalibrationSpec(BaseModel):
    mode: Literal["aruco_token", "id1_card", "known_dimension"]
    reference_side: CaptureSide
    known_length_mm: float = Field(gt=1.0, le=2000.0)
    point_a_px: Optional[tuple[float, float]] = None
    point_b_px: Optional[tuple[float, float]] = None
    mm_per_unit: Optional[float] = None

class DetectedPlane(BaseModel):
    plane_id: str
    normal: tuple[float, float, float]
    centroid_mm: tuple[float, float, float]
    area_mm2: float
    inlier_ratio: float

class DetectedCylinder(BaseModel):
    cylinder_id: str
    kind: Literal["boss", "through_hole", "blind_hole"]
    axis_origin_mm: tuple[float, float, float]
    axis_direction: tuple[float, float, float]
    radius_mm: float = Field(gt=0.1)
    depth_mm: float = Field(gt=0.1)
    confidence: float = Field(ge=0.0, le=1.0)

class Open3DGeometryReport(BaseModel):
    scan_id: str
    units: Literal["mm"] = "mm"
    point_count: int
    icp_fitness_score: float = Field(ge=0.0, le=1.0)
    icp_inlier_rmse_mm: float
    bounding_box_mm: tuple[float, float, float]  # (length_x, width_y, height_z)
    principal_axes: list[tuple[float, float, float]]
    symmetry_planes: list[Literal["XY", "YZ", "XZ"]]
    planes: list[DetectedPlane]
    cylinders: list[DetectedCylinder]
    ply_object_key: str

class FeatureStep(BaseModel):
    step_index: int
    operation: Literal[
        "base_extrude", "cut_extrude", "revolve",
        "hole", "fillet", "chamfer", "mirror", "pattern"
    ]
    target_plane: str
    parameters_mm: dict[str, float | list[float] | str]
    rationale: str

class CSGFeatureTree(BaseModel):
    part_summary: str
    coordinate_origin: Literal["center_bottom", "center_centroid"] = "center_bottom"
    global_parameters_mm: dict[str, float]
    steps: list[FeatureStep]

class ValidationMetrics(BaseModel):
    is_watertight: bool
    volume_mm3: float
    surface_area_mm2: float
    chamfer_mean_mm: float
    chamfer_p95_mm: float
    bbox_delta_mm: tuple[float, float, float]
    passed_tolerance: bool
    discrepancy_notes: list[str]
~~~

---

## 5. Relational & Vector Database Schema (PostgreSQL 16 + `pgvector`)

~~~sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1. Scan Projects
CREATE TABLE scan_projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    title TEXT NOT NULL DEFAULT 'Untitled Part',
    status TEXT NOT NULL CHECK (status IN (
        'capturing', 'calibrated', 'processing_cv', 'synthesizing_cad',
        'completed', 'completed_with_warning', 'failed'
    )),
    calibration_json JSONB,
    geometry_report_json JSONB,
    langgraph_thread_id TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Captured 6-Side Views
CREATE TABLE scan_views (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_id UUID NOT NULL REFERENCES scan_projects(id) ON DELETE CASCADE,
    side TEXT NOT NULL CHECK (side IN ('front', 'back', 'left', 'right', 'top', 'bottom')),
    raw_r2_key TEXT NOT NULL,
    masked_r2_key TEXT,
    blur_score DOUBLE PRECISION NOT NULL,
    width_px INT NOT NULL,
    height_px INT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (scan_id, side)
);

-- 3. Generated CAD Revisions (Supports Parametric Follow-Up Edits)
CREATE TABLE cad_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_id UUID NOT NULL REFERENCES scan_projects(id) ON DELETE CASCADE,
    revision_number INT NOT NULL,
    user_prompt TEXT,
    feature_tree_json JSONB NOT NULL,
    build123d_code TEXT NOT NULL,
    validation_metrics_json JSONB NOT NULL,
    step_r2_key TEXT NOT NULL,
    dxf_r2_key TEXT NOT NULL,
    stl_r2_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (scan_id, revision_number)
);

-- 4. build123d API Documentation RAG Index
CREATE TABLE build123d_doc_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    api_symbol TEXT NOT NULL,           -- e.g. 'BuildPart', 'Cylinder', 'fillet'
    category TEXT NOT NULL,             -- 'builder_3d', 'sketch_2d', 'operations', 'export'
    content TEXT NOT NULL,
    code_example TEXT,
    embedding VECTOR(1536) NOT NULL,
    doc_version TEXT NOT NULL DEFAULT '0.9.x',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_scan_projects_user ON scan_projects(user_id, created_at DESC);
CREATE INDEX idx_build123d_embedding ON build123d_doc_chunks
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
~~~
