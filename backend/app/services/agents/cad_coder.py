from typing import Dict, Any, Optional
from google import genai
from app.core.config import settings

class CadCoderAgent:
    """
    Agent 3: CadQuery / CAD Code Synthesizer
    Translates the CSG Recipe into executable, parametric CadQuery Python code
    or OpenSCAD code.
    """

    def __init__(self, client: genai.Client = None):
        self.client = client or (genai.Client(api_key=settings.GEMINI_API_KEY) if settings.GEMINI_API_KEY else None)

    async def generate_code(
        self,
        csg_plan: Dict[str, Any],
        engine_type: str = "cadquery",
        error_feedback: Optional[str] = None
    ) -> str:
        """
        Generates CAD script. If error_feedback is provided, acts in 'reflection/patch' mode.
        """
        if not self.client:
            return self._heuristic_code(csg_plan, engine_type)

        feedback_prompt = ""
        if error_feedback:
            feedback_prompt = f"""
PREVIOUS CODE ATTEMPT FAILED WITH COMPILER ERROR:
\"\"\"{error_feedback}\"\"\"
Please inspect the traceback carefully, fix the syntax/geometry logic (e.g. reduce fillet radius, check workplane orientation, ensure result object is defined), and output the corrected code.
"""

        prompt = f"""You are a Lead CAD Software Automation Engineer.
Convert this CSG plan into a robust, executable Python CadQuery script.

CSG Plan:
{csg_plan}
{feedback_prompt}

Requirements:
1. Output pure Python code only. No Markdown fences (no ```python).
2. Must import `cadquery as cq`.
3. Must assign the final geometry to a variable named `result`.
4. Keep all dimensions in millimeters.
5. Avoid dangerous large fillet radii that collapse faces; use conservative radii (e.g. 1.5 to 3.0mm).

Example template:
import cadquery as cq

result = (
    cq.Workplane("XY")
    .box(60.0, 40.0, 25.0)
    .edges("|Z")
    .fillet(2.5)
    .faces(">Z")
    .workplane()
    .hole(10.0)
)
"""
        try:
            response = self.client.models.generate_content(
                model=settings.DEFAULT_LLM_MODEL,
                contents=prompt
            )
            clean_code = response.text.replace("```python", "").replace("```", "").strip()
            return clean_code
        except Exception:
            return self._heuristic_code(csg_plan, engine_type)

    def _heuristic_code(self, csg_plan: Dict[str, Any], engine_type: str) -> str:
        params = csg_plan.get("base_primitive", {}).get("parameters", {})
        x = float(params.get("x", 60.0))
        y = float(params.get("y", 40.0))
        z = float(params.get("z", 25.0))

        # Safe fillet radius
        fillet = min(3.0, round(min(x, y, z) * 0.08, 1))

        # Hole diameter
        hole_diam = 10.0
        for op in csg_plan.get("operations", []):
            if op.get("operation") == "hole":
                hole_diam = float(op.get("parameters", {}).get("diameter", 10.0))
                break

        if engine_type == "openscad":
            return f"""// PhotoCAD OpenSCAD Model
difference() {{
    minkowski() {{
        cube([{x - 2 * fillet}, {y - 2 * fillet}, {z - 2 * fillet}], center=true);
        sphere(r={fillet}, $fn=30);
    }}
    translate([0, 0, -{z}])
        cylinder(h={z * 2}, d={hole_diam}, center=true, $fn=50);
}}
"""
        # Default CadQuery
        return f"""import cadquery as cq

# Parametric Base Dimensions (mm)
length_x = {x}
width_y = {y}
height_z = {z}
fillet_radius = {fillet}
hole_diameter = {hole_diam}

# Constructive Solid Modeling
result = (
    cq.Workplane("XY")
    .box(length_x, width_y, height_z)
    .edges("|Z")
    .fillet(fillet_radius)
    .faces(">Z")
    .workplane()
    .hole(hole_diameter)
)
"""
