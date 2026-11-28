# Metric Scale Calibration Skill (`scale-calibration.skill.md`)

*Apply whenever modifying `frontend/src/components/scanner/ScaleCalibrator.tsx`, `frontend/src/utils/scaleDetection.ts`, or `CalibrationSpec` handling.*

## Non-negotiable rules

1. **Millimeters are the only output unit.** Every detector returns `mm_per_unit` (mm per source pixel) and a `known_length_mm` reference; no inches, no meter conversions inside the client.
2. **Three modes, one ADT.** `known_dimension`, `id1_card`, `aruco_token` all produce the same `CalibrationSpec`; adding a detector must not change the backend ADT shape.
3. **ID-1 geometry:** ISO/IEC 7810 ID-1 is exactly `85.60 x 53.98 mm` (aspect `1.5858`). Accept a detected quadrilateral only when the aspect error is ≤ 8% and the area is ≥ 0.5% of the image.
4. **ArUco fiducials:** detect a black border / white quiet zone, decode a 4x4 or 5x5 binary dictionary, and only accept an exact Hamming-distance match. Minimum side length in pixels must be ≥ 12 px; otherwise reject rather than guess. Use the declared marker side length (default 20 mm) as the physical reference.
5. **Never fabricate a calibration.** If no token/card is found, keep the manual 2-point caliper path and leave `mm_per_unit` undefined. A detected result must always populate both corner/edge pixel coordinates so the user can audit it visually.
6. **Coordinate mapping uses natural pixels.** Overlay positions derive from `naturalWidth/naturalHeight` and the rendered `object-contain` box; account for letterboxing so marker A/B badges land on the detected corners.
7. **Deterministic, dependency-light.** Detection runs in pure TypeScript on a downscaled canvas (max 1600 px); no OpenCV WASM download is required for the built-in fiducials.

## Verification checklist

- Unit tests cover: exact ID-1 rectangle, rotated ID-1 rectangle, unknown marker rejected, manual mode untouched.
- `npm run typecheck && npm run build` pass after detector integration.
- Saving a detected calibration emits `mode`, `reference_side`, `known_length_mm`, point pair, and positive `mm_per_unit`.
