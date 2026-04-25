"""
Diagram Generator — deterministic pipeline orchestrator.

Converts ProcedureDraftOutput into swimlane PNG(s) and a flowchart PlantUML string.
No LLM calls. Layout and rendering are fully computed from structured data.

Pipeline:
    ProcedureDraftOutput
        → ProcedureParser    (extract DiagramSpec grid — no LLM)
        → LayoutEngine       (compute pixel positions — no LLM)
        → MatplotlibRenderer (render Visio-style swimlane PNG — no LLM)
        → PlantUMLRenderer   (generate flowchart PlantUML code — no LLM)
"""
from __future__ import annotations

import json

from ..models import ProcedureDraftOutput
from .procedure_parser import ProcedureParser, DiagramSpec
from .layout_engine import LayoutEngine
from .matplotlib_renderer import MatplotlibRenderer
from .renderer_plantuml import PlantUMLRenderer
from .renderer_matplotlib_flowchart import MatplotlibFlowchartRenderer
from .swimlane_json_serializer import build_spec
from .visio_swimlane_renderer import VisioSwimlaneRenderer


class DiagramGenerator:
    """
    Deterministic diagram generator for procedure documents.

    Replaces the old SwimlaneAgent (LLM) + DiagramAgent (LLM) pair.
    Both swimlane and flowchart are now fully deterministic.
    """

    def __init__(self) -> None:
        self._parser   = ProcedureParser()
        self._layout   = LayoutEngine()
        self._mpl      = MatplotlibRenderer()
        self._plantuml = PlantUMLRenderer()
        self._visio    = VisioSwimlaneRenderer()

    # ── Public API ─────────────────────────────────────────────────────────────

    def generate_swimlane(self, draft: ProcedureDraftOutput) -> list[bytes]:
        """
        Generate swimlane diagram PNG(s) for a procedure draft.

        Returns a list of PNG bytes — usually one item, but may return
        multiple parts when the procedure exceeds MAX_PHASES complexity.
        """
        results: list[bytes] = []
        for spec in self._parser.parse(draft):
            grid = self._layout.compute(spec)
            png  = self._mpl.render(grid)
            if png:
                results.append(png)
                print(
                    f"[DiagramGenerator] Swimlane part {spec.part_no}/{spec.total_parts} "
                    f"— {len(spec.nodes)} nodes, {len(spec.edges)} edges, "
                    f"{len(png):,} bytes."
                )
        return results

    def generate_flowchart_code(self, draft: ProcedureDraftOutput) -> str:
        """
        Generate PlantUML activity diagram code for the procedure flowchart.

        Returns PlantUML string that can be:
          1. Rendered via plantuml.com API → PNG
          2. Embedded as a code block in the DOCX for manual rendering
        """
        specs = self._parser.parse(draft)
        if not specs:
            return ""
        code = self._plantuml.render(specs[0])
        print(f"[DiagramGenerator] Flowchart PlantUML: {len(code)} chars.")
        return code

    def generate_flowchart_png(self, draft) -> list[bytes]:
        """
        Renders the procedure flowchart as native matplotlib PNG (no external server).
        Returns one PNG per phase group (same split logic as swimlane).
        """
        specs = self.get_specs(draft)
        renderer = MatplotlibFlowchartRenderer()
        results: list[bytes] = []
        for spec in specs:
            png = renderer.render(spec)
            if png:
                results.append(png)
        return results

    def generate_swimlane_vsdx(self, draft: ProcedureDraftOutput) -> list[tuple[bytes, dict]]:
        """
        Generate swimlane diagram(s) as Visio .vsdx files.

        Returns a list of (vsdx_bytes, json_spec_dict) tuples — one per diagram
        part.  The json_spec_dict is the intermediate SwimlaneJsonSpec serialised
        to a plain dict; callers can write it to disk for debugging or archiving.

        Example
        -------
        results = generator.generate_swimlane_vsdx(draft)
        for i, (vsdx_bytes, spec_dict) in enumerate(results):
            Path(f"swimlane_part{i+1}.vsdx").write_bytes(vsdx_bytes)
            Path(f"swimlane_part{i+1}.json").write_text(
                json.dumps(spec_dict, indent=2))
        """
        results: list[tuple[bytes, dict]] = []
        for spec in self._parser.parse(draft):
            grid      = self._layout.compute(spec)
            json_spec = build_spec(grid)
            spec_dict = json_spec.to_dict()
            try:
                vsdx_bytes = self._visio.render(spec_dict)
                results.append((vsdx_bytes, spec_dict))
                print(
                    f"[DiagramGenerator] Visio swimlane part "
                    f"{spec.part_no}/{spec.total_parts} — "
                    f"{len(spec.nodes)} nodes, {len(spec.edges)} edges, "
                    f"{len(vsdx_bytes):,} bytes."
                )
            except Exception as exc:
                print(f"[DiagramGenerator] Visio render failed (part {spec.part_no}): {exc}")
        return results

    def get_specs(self, draft: ProcedureDraftOutput) -> list[DiagramSpec]:
        """Return DiagramSpec(s) for inspection, testing, or alternative renderers."""
        return self._parser.parse(draft)
