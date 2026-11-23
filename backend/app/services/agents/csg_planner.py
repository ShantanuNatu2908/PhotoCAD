import json
from typing import Dict, Any, List
from google import genai
from app.core.config import settings

class CSGArchitectAgent:
    """
    Agent 2: CSG Geometric Architect
    Deconstructs the 3D spatial properties into an ordered sequence of
    Constructive Solid Geometry (CSG) operations:
    - Base primitive creation (Workplane.box / cylinder)
    - Extrusions and Cuts (holes, slots)
    - Surface modifications (Fillet, Chamfer)
    """

    def __init__(self, client: genai.Client = None):
        self.client = client or (genai.Client(api_key=settings.GEMINI_API_KEY) if settings.GEMINI_API_KEY else None)

    async def create_csg_plan(self, spatial_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generates an ordered CAD modeling sequence.
        """
        if not self.client:
            return self._heuristic_csg_plan(spatial_analysis)

        prompt = f"""You are a Senior CAD Modeling Architect specializing in B-Rep and Parametric Solid Modeling.
Based on the Spatial Vision Analysis below, design an optimal, deterministic CSG (Constructive Solid Geometry) construction plan for OpenCascade / CadQuery.

Spatial Analysis:
{json.dumps(spatial_analysis, indent=2)}

Rules for CSG Planning:
1. Always start from a clean primary datum plane (usually "XY").
2. Create the outer bounding solid first (box or cylinder).
3. Apply external modifications (fillets, chamfers) with safe radii (never exceeding half the minimum wall thickness).
4. Perform boolean cutouts / holes on referenced faces (e.g., .faces('>Z').workplane().hole(...)).
5. Ensure geometry is manifold and valid.

Respond ONLY with valid JSON conforming to this schema:
{{
  "base_primitive": {{
    "type": "box | cylinder",
    "parameters": {{ "x": float, "y": float, "z": float }}
  }},
  "operations": [
    {{
      "step": 1,
      "operation": "fillet | hole | cut | chamfer",
      "target_face": ">Z | <Z | >X | <X | |Z",
      "parameters": {{ "radius": float, "diameter": float, "depth": float }}
    }}
  ],
  "design_rationale": "short explanation of the modeling strategy"
}}
"""
        try:
            response = self.client.models.generate_content(
                model=settings.DEFAULT_LLM_MODEL,
                contents=prompt,
                config={"response_mime_type": "application/json"}
            )
            return json.loads(response.text)
        except Exception:
            return self._heuristic_csg_plan(spatial_analysis)

    def _heuristic_csg_plan(self, spatial_analysis: Dict[str, Any]) -> Dict[str, Any]:
        dims = spatial_analysis.get("dimensions_mm", {})
        x = dims.get("length_x", 60.0)
        y = dims.get("width_y", 40.0)
        z = dims.get("height_z", 25.0)

        fillet_radius = min(3.0, round(min(x, y, z) * 0.1, 1))

        operations = [
            {
                "step": 1,
                "operation": "fillet",
                "target_face": "|Z",
                "parameters": {"radius": fillet_radius}
            }
        ]

        # Add holes from features
        for idx, feat in enumerate(spatial_analysis.get("primary_features", [])):
            if feat.get("type") in ["through_hole", "blind_hole"]:
                diam = feat.get("parameters", {}).get("diameter_mm", 10.0)
                operations.append({
                    "step": idx + 2,
                    "operation": "hole",
                    "target_face": ">Z",
                    "parameters": {"diameter": diam, "depth": z}
                })

        return {
            "base_primitive": {
                "type": "box",
                "parameters": {"x": x, "y": y, "z": z}
            },
            "operations": operations,
            "design_rationale": "Parametric base extrusion with vertical edge fillets and through-hole feature."
        }
