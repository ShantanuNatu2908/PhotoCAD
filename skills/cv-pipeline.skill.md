# CV Pipeline Skill (`cv-pipeline.skill.md`)

> **Scope:** Apply these engineering rules whenever building, modifying, or testing `gpu_workers/` (Modal, SAM 2.1/3.1, Depth Anything V2/DA3, Open3D) and `backend/app/services/cv_pipeline_service.py`.

---

## 1. Non-Negotiable Architecture Rules
1. **No 2D OpenCV Canny Contour 3D Reconstruction:** Never construct CAD geometry from 2D Canny edges or Otsu silhouettes alone. Follow the true 3D pipeline:
   `Uncompressed PNG Keyframes -> SAM 2.1 Masking -> Depth Anything (FP16) -> Open3D Multi-View Fusion -> Open3DGeometryReport`
2. **Keyframe-Only Inference:** Process the 6 uploaded `.PNG` keyframes as a bounded batch. Never maintain continuous video embedding memory across frames.
3. **Strict Monorepo Isolation:**
   - `gpu_workers/` runs PyTorch, SAM 2.1, Depth Anything, and Open3D inside Modal GPU containers (`L4`).
   - `backend/` must stay free of PyTorch and CUDA dependencies.

## 2. Modal & GPU Memory Discipline
1. **Half-Precision Mandatory:** Wrap all PyTorch neural network forward passes inside:
   ```python
   with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
       ...
   ```
2. **Explicit VRAM Reclamation:** Call `torch.cuda.empty_cache()` immediately after SAM segmentation and again after Depth Anything inference before launching C++ Open3D registration.
3. **Modal Function Settings:**
   - Use `gpu="L4"`, `scaledown_window=60`.
   - Mount persistent cache volume at `/root/.cache` (`modal.Volume.from_name("photocad-model-cache", create_if_missing=True)`) to prevent cold-start Hugging Face downloads.

## 3. Open3D Multi-View Fusion & Registration Hygiene
1. **Outlier Filtering Before ICP:** Every per-view partial point cloud must pass:
   ```python
   pcd_clean, _ = pcd.remove_statistical_outlier(nb_neighbors=20, std_ratio=2.0)
   ```
2. **Minimum Alignment Quality Guard:**
   - Measure global `icp_fitness_score` after multi-scale Point-to-Plane ICP.
   - If `icp_fitness_score < 0.65`, abort and return structured error `FUSION_LOW_OVERLAP` so users retake misaligned views rather than feeding corrupt geometry to LangGraph.
3. **Scale Before Primitive Extraction:** Apply the calibrated `mm_per_unit` scaling factor to the aligned point cloud *before* running RANSAC plane segmentation, cylinder detection, or PCA bounding box computation so every `Open3DGeometryReport` metric is natively in **millimeters (`mm`)**.
4. **Canonical ADT Compliance:** Output must validate strictly against `app.schemas.adt.Open3DGeometryReport`.
