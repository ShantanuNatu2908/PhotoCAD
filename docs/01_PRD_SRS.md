# PhotoCAD — Product & Software Requirements Specification (PRD / SRS)

**Document ID:** `PCAD-PRD-SRS-001`  
**Version:** `1.0.0`  
**Status:** Approved for Development (Wave 1)  
**Target Platform:** Web Browser Thin-Client (Desktop & Mobile Browsers) + Cloud GPU Backend  

---

## 1. Product Vision & Executive Summary

**PhotoCAD** is a real-time, low-latency, web-based AI and Computer Vision platform that converts handheld, 6-sided physical object scans into editable, parametric **Boundary Representation (B-Rep) 3D CAD models** (`.STEP`, `.DXF`, `.STL`) compatible with AutoCAD, SolidWorks, and Fusion 360.

Unlike static photogrammetry suites or polygon-mesh generators that produce uneditable `.OBJ`/`.STL` triangles, PhotoCAD captures six crisp handheld views directly from a browser camera, fuses true 3D surface geometry in the cloud, and orchestrates a self-correcting multi-agent system to synthesize deterministic parametric CAD scripts.

---

## 2. Target User Personas

| Persona | Primary Goal | Key Pain Points Solved |
| :--- | :--- | :--- |
| **Mechanical / CAD Engineer** | Rapidly reverse-engineer broken brackets, flanges, or housings into editable AutoCAD/SolidWorks solids. | Manual caliper measurements take 30–60 minutes; raw 3D scan meshes cannot be directly extruded or filleted. |
| **Product / Industrial Designer** | Digitize physical clay/foam/3D-printed prototypes for iterative CAD refinement. | Dedicated handheld 3D scanners cost \$1,000–\$10,000+ and require heavy local workstations. |
| **Maker / 3D Printing Technician** | Scan a spare part via webcam or phone browser, tweak hole diameters, and export a printable `.STL` or `.STEP`. | Steep CAD learning curve and unreliable single-photo 3D AI generators that hallucinate dimensions. |

---

## 3. Product Scope (v1.0 MVP)

### In-Scope (v1.0)
* Browser-based real-time camera capture with automated sharpness filtering and 6-side guided overlay (Front, Back, Left, Right, Top, Bottom).
* Automated hand and background removal on handheld parts.
* Multi-view 3D depth estimation, 6-side point cloud registration, and metric scaling ($1:1\text{ mm}$).
* Cyclic LangGraph multi-agent synthesis generating parametric `build123d` Python scripts.
* Interactive 3D web viewport with measurement tools and native `.STEP`, `.DXF`, and `.STL` downloads.
* Post-generation natural-language parametric edits (e.g., *"Increase center bore diameter from $10\text{ mm}$ to $12\text{ mm}$"*).

### Out-of-Scope (v1.0 — Deferred to v2.0+)
* Native Android/iOS mobile applications (ARCore/ARKit/LiDAR).
* Multi-component moving assemblies with kinematic mates.
* Organic/sculptural freeform surfaces (e.g., human faces, cloth, foliage).
* Direct desktop CAD plugin integrations (SolidWorks/AutoCAD add-ins).

---

## 4. Functional Requirements (FR)

### 4.1 Real-Time Handheld Web Capture
* **`FR-01` Camera Initialization:** The web client shall request camera permissions via `navigator.mediaDevices.getUserMedia` at minimum $1280 \times 720$ resolution (preferring $1920 \times 1080$ and rear-facing camera on mobile browsers).
* **`FR-02` 6-Side Guided Overlay:** The UI shall guide the user sequentially through six capture orientations: `FRONT`, `BACK`, `LEFT`, `RIGHT`, `TOP`, and `BOTTOM`, displaying visual progress indicators and silhouette alignment cues.
* **`FR-03` Real-Time Blur Rejection:** The client shall compute frame sharpness locally (Laplacian variance or WebGPU edge gradient) and reject frames below the sharpness threshold to prevent motion blur.
* **`FR-04` Uncompressed Keyframe Capture:** Upon sharp frame lock (automatic or manual trigger), the client shall extract an uncompressed `.PNG` keyframe from the video canvas—never relying on lossy WebRTC video compression for reconstruction.
* **`FR-05` Retake Capability:** Users shall be able to preview and retake any individual side before submitting the scan for processing.

### 4.2 Metric Calibration ($1:1\text{ mm}$)
* **`FR-06` Dual Calibration Modes:** Before 3D fusion runs, the user shall establish real-world metric scale via either:
  1. **Visual Reference Token:** Detecting a standard ArUco marker or ISO/IEC 7810 ID-1 card ($85.60\text{ mm} \times 53.98\text{ mm}$) in the calibration frame, OR
  2. **Known-Dimension Entry:** Selecting two endpoints on the primary view and entering one caliper-measured length in $\text{mm}$.

### 4.3 Cloud Computer Vision & 3D Fusion
* **`FR-07` Hand & Background Segmentation:** The cloud GPU worker shall segment the target physical object from human hands, fingers, and background clutter across all 6 keyframes.
* **`FR-08` Multi-View 3D Surface Recovery:** The GPU worker shall estimate camera poses and dense depth maps across the 6 masked views to construct per-view 3D surface point clouds.
* **`FR-09` 6-Side Point Cloud Registration:** The backend shall align and fuse all 6 point clouds into a unified, outlier-filtered, metric-scaled `.PLY` model.
* **`FR-10` Geometric Primitive Extraction:** The backend shall extract structured geometric features (bounding box in $\text{mm}$, planar faces with surface normals, cylindrical bosses/holes with radii and axes, symmetry planes) into a deterministic JSON report.

### 4.4 Agentic CAD Synthesis & Self-Correction
* **`FR-11` Parametric Feature Planning:** The multi-agent pipeline shall synthesize an ordered B-Rep feature tree from the 6 masked views and geometric JSON report.
* **`FR-12` Deterministic Code Generation:** The code agent shall generate valid, parameterized `build123d` Python source code augmented via `pgvector` API documentation retrieval.
* **`FR-13` Sandboxed Compilation Loop:** Generated Python code shall execute inside an isolated, network-disabled sandbox; runtime or OpenCascade kernel exceptions shall trigger automated self-repair up to 3 attempts.
* **`FR-14` Geometric Accuracy Verification:** The system shall sample surface points from the compiled `.STEP` solid and measure the Chamfer Distance against the fused scan; deviations exceeding tolerance shall trigger geometric refinement up to 3 iterations.
* **`FR-15` Live Progress Streaming:** The backend shall stream real-time CV and agent state events to the browser over WebSockets.

### 4.5 3D Preview, Export & Parametric Editing
* **`FR-16` Interactive 3D Viewport:** Users shall inspect the generated CAD model (orbit, pan, zoom, wireframe toggle, point-cloud overlay comparison) directly in the browser via React Three Fiber.
* **`FR-17` Engineering Exports:** Users shall download verified, watertight `.STEP` (AP214/AP203), `.DXF` (orthographic 2D projection), `.STL` (watertight mesh), and editable `.py` (`build123d`) source files.
* **`FR-18` Conversational Parametric Editing:** Users shall submit follow-up text edits to modify dimensions or features by resuming the saved LangGraph checkpoint without rescanning the object.

---

## 5. Non-Functional Requirements (NFR)

| ID | Category | Requirement Specification | Target Metric |
| :--- | :--- | :--- | :--- |
| **`NFR-01`** | **End-to-End Latency** | Total elapsed time from 6th keyframe upload confirmation to downloadable `.STEP` file (median mechanical part). | $\le 45\text{ seconds}$ |
| **`NFR-02`** | **CV Pipeline Latency** | SAM segmentation + multi-view depth + Open3D fusion on serverless cloud GPU (NVIDIA L4/A10G). | $\le 15\text{ seconds}$ |
| **`NFR-03`** | **UI Responsiveness** | Browser live camera preview and sharpness overlay framerate on mid-tier laptops/phones. | $\ge 24\text{ FPS}$ |
| **`NFR-04`** | **Dimensional Accuracy** | Mean bidirectional Chamfer Distance between generated `.STEP` solid and scaled ground-truth scan on rigid prismatic parts. | $\le 1.0\text{ mm}$ |
| **`NFR-05`** | **Compilation Reliability** | Percentage of valid 6-side scans producing a watertight, non-corrupt `.STEP` solid within the retry budget. | $\ge 92\%$ |
| **`NFR-06`** | **AutoCAD Interoperability** | Exported `.STEP` and `.DXF` files must import cleanly with zero non-manifold edges and $1:1\text{ mm}$ units in AutoCAD, Fusion 360, and SolidWorks. | $100\%$ pass on Golden Dataset |
| **`NFR-07`** | **Sandbox Security** | LLM-generated Python execution must be isolated (no filesystem escape, no outbound network, strict CPU/RAM/timeout caps). | Zero host access; $30\text{ s}$ max timeout |
| **`NFR-08`** | **Camera Privacy** | Raw user keyframes containing hands/workspaces must be encrypted in transit (TLS 1.3) and auto-purged via object storage lifecycle rules. | Auto-delete raw frames after $24\text{ hours}$ |
| **`NFR-09`** | **Browser Compatibility** | Full support across latest 2 versions of Chrome, Edge, Safari (iOS/macOS), and Firefox. | Cross-browser E2E pass |
| **`NFR-10`** | **Cloud Cost Efficiency** | GPU workers must scale to zero when idle to prevent fixed compute burn during development and low-traffic periods. | Scale-to-zero within $60\text{ s}$ idle |

---

## 6. v1.0 Acceptance Criteria (Definition of Done)

A v1.0 release candidate is accepted only when:
1. All 18 Functional Requirements (`FR-01`–`FR-18`) pass automated integration and end-to-end tests.
2. A **Golden Dataset** of 10 caliper-measured physical mechanical parts (e.g., L-bracket, flanged bushing, mounting plate with bolt pattern, T-slot block) achieves $\ge 90\%$ watertight `.STEP` compilation and mean Chamfer Distance $\le 1.0\text{ mm}$.
3. At least 5 generated `.STEP` and `.DXF` files are manually imported into **AutoCAD** and **Fusion 360** and verified for exact $1:1\text{ mm}$ scale and editable solid faces.
4. Security audit confirms sandboxed `build123d` execution blocks network egress, file-system traversal, and infinite-loop DoS attacks.
