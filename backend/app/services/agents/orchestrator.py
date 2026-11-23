import os
import json
from typing import Dict, Any, Optional, Callable, Awaitable
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import CadGeneration, AgentLog
from app.services.agents.vision_agent import VisionAnalystAgent
from app.services.agents.csg_planner import CSGArchitectAgent
from app.services.agents.cad_coder import CadCoderAgent
from app.services.agents.validator import ValidatorAgent
from app.core.config import settings

class AgentOrchestrator:
    """
    Coordinates the 4-stage Multi-Agent CAD Pipeline:
    1. VisionAnalystAgent (Spatial analysis)
    2. CSGArchitectAgent (Constructive Solid Geometry planning)
    3. CadCoderAgent (CadQuery code generation)
    4. ValidatorAgent (Self-healing compiler validation)
    """

    def __init__(self, db: AsyncSession, ws_broadcast: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None):
        self.db = db
        self.ws_broadcast = ws_broadcast
        self.vision_agent = VisionAnalystAgent()
        self.csg_agent = CSGArchitectAgent()
        self.cad_coder = CadCoderAgent()
        self.validator = ValidatorAgent(max_retries=3)

    async def log_step(self, generation_id: str, agent_name: str, log_type: str, message: str):
        """Persists agent thought/action to DB and broadcasts over WebSocket."""
        log_entry = AgentLog(
            generation_id=generation_id,
            agent_name=agent_name,
            log_type=log_type,
            message=message
        )
        self.db.add(log_entry)
        await self.db.commit()

        if self.ws_broadcast:
            await self.ws_broadcast({
                "type": "agent_log",
                "generation_id": generation_id,
                "agent_name": agent_name,
                "log_type": log_type,
                "message": message
            })

    async def run_pipeline(
        self,
        generation_id: str,
        views_data: Dict[str, Any],
        scale_ratio: float,
        engine_type: str = "cadquery"
    ) -> CadGeneration:
        """Runs the entire multi-agent synthesis and compilation pipeline."""
        
        # 1. Update status
        gen = await self.db.get(CadGeneration, generation_id)
        if not gen:
            raise ValueError(f"Generation {generation_id} not found")

        gen.status = "generating"
        await self.db.commit()

        # Target export paths
        step_filename = f"{generation_id}.step"
        stl_filename = f"{generation_id}.stl"
        dxf_filename = f"{generation_id}.dxf"

        step_path = str(settings.EXPORTS_DIR / step_filename)
        stl_path = str(settings.EXPORTS_DIR / stl_filename)
        dxf_path = str(settings.EXPORTS_DIR / dxf_filename)

        # Stage 1: Spatial Vision Analysis
        await self.log_step(generation_id, "VisionAnalyst", "thought", "Cross-referencing 6-axis orthogonal contours and bounding metrics...")
        spatial_analysis = await self.vision_agent.analyze_views(views_data, scale_ratio)
        await self.log_step(generation_id, "VisionAnalyst", "info", f"Classification: {spatial_analysis.get('object_classification')}. Estimated dimensions: {spatial_analysis.get('dimensions_mm')}")

        # Stage 2: CSG Geometric Architecture
        await self.log_step(generation_id, "CSGArchitect", "thought", "Formulating Constructive Solid Geometry (CSG) modeling sequence...")
        csg_plan = await self.csg_agent.create_csg_plan(spatial_analysis)
        await self.log_step(generation_id, "CSGArchitect", "info", f"CSG Recipe: {len(csg_plan.get('operations', []))} operations scheduled. {csg_plan.get('design_rationale')}")

        # Stage 3: CAD Code Synthesis
        await self.log_step(generation_id, "CadCoder", "thought", f"Synthesizing parametric {engine_type} code...")
        initial_code = await self.cad_coder.generate_code(csg_plan, engine_type)
        await self.log_step(generation_id, "CadCoder", "code", initial_code)

        # Stage 4: Self-Healing Validation Loop
        gen.status = "compiling"
        await self.db.commit()

        async def repair_callback(error_text: str) -> str:
            await self.log_step(generation_id, "CadCoder", "thought", "Applying patch for compiler error...")
            patched = await self.cad_coder.generate_code(csg_plan, engine_type, error_feedback=error_text)
            await self.log_step(generation_id, "CadCoder", "code", patched)
            return patched

        async def validator_log(log_type: str, msg: str):
            await self.log_step(generation_id, "Validator", log_type, msg)

        dims = {
            "x": spatial_analysis.get("dimensions_mm", {}).get("length_x", 60.0),
            "y": spatial_analysis.get("dimensions_mm", {}).get("width_y", 40.0),
            "z": spatial_analysis.get("dimensions_mm", {}).get("height_z", 25.0)
        }

        success, final_code, err = await self.validator.validate_and_heal(
            code=initial_code,
            engine_type=engine_type,
            step_path=step_path,
            stl_path=stl_path,
            dxf_path=dxf_path,
            dimensions=dims,
            features=spatial_analysis.get("primary_features", []),
            coder_repair_fn=repair_callback,
            log_callback=validator_log
        )

        # Update generation record
        gen.code = final_code
        gen.dimensions_mm = dims
        gen.status = "completed" if success else "failed"
        gen.error_log = err
        
        if os.path.exists(step_path):
            gen.step_file = f"/storage/cad_exports/{step_filename}"
        if os.path.exists(stl_path):
            gen.stl_file = f"/storage/cad_exports/{stl_filename}"
        if os.path.exists(dxf_path):
            gen.dxf_file = f"/storage/cad_exports/{dxf_filename}"

        await self.db.commit()
        await self.db.refresh(gen)

        await self.log_step(
            generation_id,
            "Orchestrator",
            "success" if success else "error",
            f"Pipeline finished with status: {gen.status}."
        )

        return gen
