# NURBS Surface Skill (`nurbs-surfaces.skill.md`)

*Apply whenever modifying `backend/app/cad/visual_hull.py`, adding B-spline patches, or changing STEP export topology.*

## Non-negotiable rules

1. **Faceted fallback stays default.** The voxel-carved closed shell remains the safe default; smooth patches are opt-in per scan/feature flag so existing interop golden tests never regress. Smooth patches feed the same build123d-derived STEP body rather than replacing it.
2. **Units stay millimetres (1:1).** Control points, knots, and evaluated points are all in `mm`; no conversion to metres/inches inside the kernel.
3. **C2 continuity by construction.** Use open uniform (clamped) cubic B-spline basis functions with degree 3 and knot vector `[0,0,0,0, ..., 1,1,1,1]`. Interior knot spans are C2.
4. **Watertight first, smooth second.** Fit surfaces only to an already pinch-free 2-manifold mesh (`_resolve_non_manifold_pinches`). Never smooth across a boundary that would open the shell.
5. **Bounded deviation.** Evaluate the fitted patch and assert max deviation from the source mesh ≤ `0.5 mm` or ≤ 1% of the bounding diagonal; otherwise keep the faceted shell and report the reason.
6. **Patch topology mirrors the six views.** Generate one tensor-product patch per principal face group (XY/XZ/YZ), with shared boundary control points so adjacent patches meet without cracks.
7. **STEP export stays AP214.** Smooth patches are emitted as `B_SPLINE_SURFACE_WITH_KNOTS` plus `CLOSED_SHELL` references; if the exporter cannot represent them, keep `ADVANCED_FACE` planar output and record `surface_mode: "faceted_fallback"`.
8. **Determinism.** Control-point fitting uses fixed sample counts and fixed seeds; repeated runs on the same voxel grid produce identical patch data.

## Verification checklist

- Patches are C2 (knot multiplicity 1 internally, degree 3).
- Exported geometry remains watertight (every edge shared by two faces).
- Deviation assertion passes on a synthetic curved silhouette and fails on a deliberately mismatched patch.
- Existing `tests/test_visual_hull_v1.py` and `tests/test_interop_golden_v1.py` remain green.
