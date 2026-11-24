"""
PhotoCAD - build123d API Documentation RAG Retriever
Document ID: PCAD-LG-004 (Node 3 Synthesizer RAG Layer)

Provides curated, verified build123d context chunks to eliminate LLM syntax hallucinations.
Integrated with pgvector (Supabase) in production, with in-memory fallback for zero-heat development.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class Build123dDocChunk(BaseModel):
    api_symbol: str
    category: str  # "builder_3d", "sketch_2d", "operations", "export"
    content: str
    code_example: str


# Curated Golden Dataset of build123d API Conventions (v0.9.x / v1.0)
GOLDEN_BUILD123D_DOCS: List[Build123dDocChunk] = [
    Build123dDocChunk(
        api_symbol="BuildPart",
        category="builder_3d",
        content=(
            "BuildPart is the primary 3D context manager in build123d. "
            "All additive or subtractive 3D solid operations must execute inside 'with BuildPart() as part:'. "
            "Always assign RESULT_PART = part.part at the conclusion of the script."
        ),
        code_example=(
            "from build123d import BuildPart, BuildSketch, Rectangle, extrude\n"
            "with BuildPart() as part:\n"
            "    with BuildSketch():\n"
            "        Rectangle(60.0, 40.0)\n"
            "    extrude(amount=25.0)\n"
            "RESULT_PART = part.part"
        )
    ),
    Build123dDocChunk(
        api_symbol="BuildSketch",
        category="sketch_2d",
        content=(
            "BuildSketch creates 2D planar profiles. It can be constructed on standard planes "
            "(Plane.XY, Plane.XZ, Plane.YZ) or directly onto faces of an existing solid using "
            "'with BuildSketch(part.faces().sort_by(Axis.Z)[-1]):'."
        ),
        code_example=(
            "with BuildSketch(part.faces().sort_by(Axis.Z)[-1]):\n"
            "    Circle(radius=8.0)\n"
            "extrude(amount=-10.0, mode=Mode.SUBTRACT)"
        )
    ),
    Build123dDocChunk(
        api_symbol="fillet",
        category="operations",
        content=(
            "fillet rounds selected edges. Edge selection must filter or group edges safely. "
            "CRITICAL: Always apply fillets LAST in the feature tree. "
            "Ensure radius < min_adjacent_wall_thickness / 2.5 to avoid OpenCascade BRep_API crashes."
        ),
        code_example=(
            "# Fillet all vertical Z-aligned edges safely\n"
            "vertical_edges = part.edges().filter_by(Axis.Z)\n"
            "fillet(vertical_edges, radius=3.0)"
        )
    ),
    Build123dDocChunk(
        api_symbol="hole",
        category="operations",
        content=(
            "Locations with Circle and subtractive extrude creates precise mounting hole patterns. "
            "Prefer Locations tuples for symmetrical 4-hole or circular patterns."
        ),
        code_example=(
            "with BuildSketch(part.faces().sort_by(Axis.Z)[-1]):\n"
            "    with Locations((20, 15), (-20, 15), (20, -15), (-20, -15)):\n"
            "        Circle(radius=3.0)\n"
            "extrude(amount=-THICKNESS_MM, mode=Mode.SUBTRACT)"
        )
    ),
    Build123dDocChunk(
        api_symbol="chamfer",
        category="operations",
        content=(
            "chamfer applies beveled edges to planar boundaries. "
            "Use length parameter in millimeters (1:1 mm)."
        ),
        code_example=(
            "top_edges = part.edges().filter_by(Axis.Z, reverse=True).group_by(Axis.Z)[-1]\n"
            "chamfer(top_edges, length=1.5)"
        )
    )
]


class Build123dRAGService:
    """Retrieves relevant build123d code snippets for LangGraph Node 3."""

    @staticmethod
    def retrieve_context_for_operations(operations: List[str]) -> List[Dict[str, str]]:
        """
        Retrieves matching documentation chunks based on scheduled CSG operations.
        Falls back to Golden Dataset in development.
        """
        matched_chunks = []
        op_set = {op.lower() for op in operations}

        for chunk in GOLDEN_BUILD123D_DOCS:
            symbol_lower = chunk.api_symbol.lower()
            if symbol_lower in op_set or any(op in symbol_lower for op in op_set):
                matched_chunks.append({
                    "symbol": chunk.api_symbol,
                    "guidance": chunk.content,
                    "canonical_pattern": chunk.code_example
                })

        # Always include BuildPart foundation if list is small
        if not any(c["symbol"] == "BuildPart" for c in matched_chunks):
            matched_chunks.insert(0, {
                "symbol": GOLDEN_BUILD123D_DOCS[0].api_symbol,
                "guidance": GOLDEN_BUILD123D_DOCS[0].content,
                "canonical_pattern": GOLDEN_BUILD123D_DOCS[0].code_example
            })

        return matched_chunks
