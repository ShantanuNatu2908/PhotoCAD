import json
from typing import Dict, Any, List
from google import genai
from app.core.config import settings

class VisionAnalystAgent:
    """
    Agent 1: Spatial Vision Analyst
    Examines 6-axis orthogonal images, detected contours, and metric measurements.
    Outputs structured 3D spatial properties (bounding volume, symmetry, primary features).
    """

    def __init__(self, client: genai.Client = None):
        self.client = client or (genai.Client(api_key=settings.GEMINI_API_KEY) if settings.GEMINI_API_KEY else None)

    async def analyze_views(self, views_summary: Dict[str, Any], scale_ratio: float) -> Dict[str, Any]:
        """
        Synthesizes 6-axis edge features into a unified 3D spatial description.
        """
        # If no Gemini API key is configured or offline, use deterministic CV feature reconstruction
        if not self.client:
            return self._heuristic_analysis(views_summary, scale_ratio)

        prompt = f"""You are the Lead Spatial Vision Analyst in an industrial reverse-engineering team.
Your job is to analyze 6 orthogonal camera scans (Front, Back, Left, Right, Top, Bottom) of a physical mechanical/manufactured object.

CV Edge & Bounding Analysis Data:
{json.dumps(views_summary, indent=2)}

Scale Ratio (px to mm): {scale_ratio}

Respond ONLY with valid JSON conforming to this schema:
{{
  "object_classification": "e.g., mounting bracket / enclosure / cylindrical bushing / flange",
  "dimensions_mm": {{
    "length_x": float,
    "width_y": float,
    "height_z": float
  }},
  "symmetry_planes": ["XY", "YZ", or "ZX"],
  "primary_features": [
    {{
      "type": "through_hole | blind_hole | pocket | fillet | chamfer | boss",
      "orientation_face": "top | bottom | front | back | left | right",
      "position_mm": [x, y, z],
      "parameters": {{ "diameter_mm": float, "depth_mm": float }}
    }}
  ],
  "reasoning": "brief engineering summary"
}}
"""
        try:
            response = self.client.models.generate_content(
                model=settings.DEFAULT_LLM_MODEL,
                contents=prompt,
                config={"response_mime_type": "application/json"}
            )
            return json.loads(response.text)
        except Exception as e:
            # Fallback to CV heuristic analysis on API exception
            return self._heuristic_analysis(views_summary, scale_ratio, note=str(e))

    def _heuristic_analysis(self, views_summary: Dict[str, Any], scale_ratio: float, note: str = "") -> Dict[str, Any]:
        """
        Deterministic estimation based directly on OpenCV contour bounds.
        """
        # Estimate dimensions from Top (X, Y) and Front (X, Z) views
        top_dim = views_summary.get("top", {}).get("primary_dimensions_mm", [60.0, 40.0])
        front_dim = views_summary.get("front", {}).get("primary_dimensions_mm", [60.0, 25.0])
        
        dim_x = float(top_dim[0] or front_dim[0] or 60.0)
        dim_y = float(top_dim[1] or 40.0)
        dim_z = float(front_dim[1] or 25.0)

        # Detect any circular holes from Top view
        features = []
        top_features = views_summary.get("top", {}).get("features", [])
        for feat in top_features:
            if feat.get("geometric_primitive") == "circle" and feat.get("type") == "hole":
                rad = feat.get("radius_mm", 5.0)
                features.append({
                    "type": "through_hole",
                    "orientation_face": "top",
                    "position_mm": [0.0, 0.0, 0.0],
                    "parameters": {"diameter_mm": round(rad * 2.0, 2), "depth_mm": dim_z}
                })

        if not features:
            # Default central mounting hole
            features.append({
                "type": "through_hole",
                "orientation_face": "top",
                "position_mm": [0.0, 0.0, 0.0],
                "parameters": {"diameter_mm": round(min(dim_x, dim_y) * 0.25, 2), "depth_mm": dim_z}
            })

        return {
            "object_classification": "Parametric Prismatic Part",
            "dimensions_mm": {
                "length_x": dim_x,
                "width_y": dim_y,
                "height_z": dim_z
            },
            "symmetry_planes": ["XY", "YZ"],
            "primary_features": features,
            "reasoning": f"Synthesized from OpenCV 6-axis orthogonal bounding contours. {note}".strip()
        }
