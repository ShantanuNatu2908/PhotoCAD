import os
import cv2
import numpy as np
from PIL import Image
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

class VisionEngine:
    """
    Computer Vision Service for 6-Axis Orthogonal Scans.
    Performs:
    1. Background segmentation & noise reduction.
    2. Canny edge detection & Otsu adaptive thresholding.
    3. Contour approximation & vector feature extraction (polygons, bounding boxes, hole centers).
    4. Metric scale calibration via ArUco marker or reference object.
    """

    @staticmethod
    def calculate_scale_from_marker(image_path: str, marker_size_mm: float = 20.0) -> Optional[float]:
        """
        Detects an ArUco marker in the image and computes pixels-per-millimeter (px_to_mm).
        If no ArUco marker is found, returns None.
        """
        img = cv2.imread(image_path)
        if img is None:
            return None
            
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Check standard 4x4 ArUco dictionary
        try:
            aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
            parameters = cv2.aruco.DetectorParameters()
            detector = cv2.aruco.ArucoDetector(aruco_dict, parameters)
            corners, ids, _ = detector.detectMarkers(gray)
            
            if ids is not None and len(corners) > 0:
                # Use the first detected marker
                pts = corners[0][0]
                # Calculate side lengths in pixels
                side1 = np.linalg.norm(pts[0] - pts[1])
                side2 = np.linalg.norm(pts[1] - pts[2])
                avg_pixel_size = (side1 + side2) / 2.0
                
                # Scale ratio: pixels per mm
                px_per_mm = avg_pixel_size / marker_size_mm
                return float(px_per_mm)
        except Exception:
            pass
            
        return None

    @staticmethod
    def process_orthogonal_view(
        image_path: str,
        output_edge_dir: str,
        view_name: str,
        px_per_mm: float = 1.0
    ) -> Dict[str, Any]:
        """
        Processes a single orthogonal camera angle:
        - Extracts edges and contours
        - Computes bounding dimensions (in pixels and scaled to mm)
        - Detects internal holes/features
        - Saves processed edge image map
        """
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"Failed to load image at {image_path}")

        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 1. Bilateral filter to smooth texture while keeping sharp geometry edges
        blurred = cv2.bilateralFilter(gray, 9, 75, 75)

        # 2. Adaptive Canny Edge Detection with Otsu thresholds
        high_thresh, _ = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        low_thresh = 0.5 * high_thresh
        edges = cv2.Canny(blurred, low_thresh, high_thresh)

        # 3. Morphological closing to seal boundary contours
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        closed_edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

        # 4. Find all contours with hierarchy (separates external silhouette from internal holes)
        contours, hierarchy = cv2.findContours(closed_edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        # Save processed edge visualization
        edge_filename = f"{view_name}_edges.png"
        edge_output_path = os.path.join(output_edge_dir, edge_filename)
        cv2.imwrite(edge_output_path, closed_edges)

        # 5. Extract significant geometric features
        features: List[Dict[str, Any]] = []
        primary_bbox = None
        primary_area = 0.0

        for i, cnt in enumerate(contours):
            area = cv2.contourArea(cnt)
            # Filter noise
            if area < 50:
                continue

            # Approximate polygonal curve
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
            
            x, y, bw, bh = cv2.boundingRect(cnt)
            is_hole = False
            if hierarchy is not None and hierarchy[0][i][3] != -1:
                is_hole = True  # Has a parent contour -> internal cutout or hole

            feature_info = {
                "type": "hole" if is_hole else "boundary",
                "area_px": float(area),
                "vertices_count": len(approx),
                "bbox_px": [int(x), int(y), int(bw), int(bh)],
                "bbox_mm": [
                    round(bw / px_per_mm, 2),
                    round(bh / px_per_mm, 2)
                ]
            }

            # Check if this is circular/cylindrical (hole or boss)
            if len(approx) > 6:
                (cx, cy), radius = cv2.minEnclosingCircle(cnt)
                circle_area = np.pi * (radius ** 2)
                if abs(area - circle_area) / circle_area < 0.25:
                    feature_info["geometric_primitive"] = "circle"
                    feature_info["radius_mm"] = round(radius / px_per_mm, 2)
                    feature_info["center_mm"] = [round(cx / px_per_mm, 2), round(cy / px_per_mm, 2)]

            features.append(feature_info)

            # Track dominant external boundary
            if not is_hole and area > primary_area:
                primary_area = area
                primary_bbox = [
                    round(bw / px_per_mm, 2),
                    round(bh / px_per_mm, 2)
                ]

        return {
            "view": view_name,
            "original_resolution": [w, h],
            "edge_map_path": edge_output_path,
            "features_detected": len(features),
            "primary_dimensions_mm": primary_bbox or [round(w / px_per_mm, 2), round(h / px_per_mm, 2)],
            "features": features[:15]  # Top features
        }
