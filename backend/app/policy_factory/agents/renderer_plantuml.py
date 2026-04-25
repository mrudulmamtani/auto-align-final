"""
PlantUML Renderer — converts a DiagramSpec into PlantUML activity diagram code.

Deterministic. No LLM involvement.
Used for the procedure flowchart (top-down sequential activity diagram).

Pipeline position:
    DiagramSpec → PlantUMLRenderer → PlantUML string → plantuml.com API → PNG
"""
from __future__ import annotations

import re

from .procedure_parser import DiagramSpec, DiagramNode


def _safe(s: str) -> str:
    """Strip characters that break PlantUML syntax."""
    return re.sub(r'[<>{}()\[\]#&"\'\\]', "", s).strip()


class PlantUMLRenderer:
    """
    Generates a PlantUML activity diagram (top-down, no swimlane partitions).

    Swimlane partitions are omitted because PlantUML's partition layout is
    vertical (not Visio-style horizontal), which conflicts with the required
    visual. The swimlane is rendered by MatplotlibRenderer instead.

    This renderer produces the flowchart (decision logic + step sequence).
    """

    def render(self, spec: DiagramSpec) -> str:
        lines = [
            "@startuml",
            "skinparam monochrome false",
            "skinparam defaultFontSize 10",
            "skinparam defaultFontName Arial",
            "skinparam ArrowColor #404040",
            "skinparam ActivityBackgroundColor #DEEAF1",
            "skinparam ActivityBorderColor #2E75B6",
            "skinparam ActivityBorderThickness 1",
            "skinparam ActivityStartColor #1F3864",
            "skinparam ActivityEndColor #1F3864",
            "skinparam ArrowFontSize 9",
            "skinparam ConditionStyle diamond",
            "",
        ]

        # Sort nodes by phase → role → slot for deterministic sequence
        ordered = sorted(
            spec.nodes,
            key=lambda n: (n.phase_idx, n.role_idx, n.slot_idx),
        )

        prev_phase: str | None = None
        open_ifs: int = 0  # track unclosed if-blocks

        for node in ordered:
            if node.phase != prev_phase:
                if prev_phase is not None:
                    lines.append("")
                lines.append(f"' --- {node.phase} ---")
                prev_phase = node.phase

            label = _safe(node.title)

            if node.node_type == "start":
                lines.append("start")
                lines.append(f":{label} [{node.step_no}];")

            elif node.node_type == "end":
                # Close any open decision blocks before stop
                for _ in range(open_ifs):
                    lines.append("endif")
                open_ifs = 0
                lines.append(f":{label} [{node.step_no}];")
                lines.append("stop")

            elif node.node_type == "decision":
                lines.append(f"if ({label}?) then (Yes)")
                lines.append(f":Proceed [{node.step_no}];")
                lines.append("else (No)")
                lines.append(":Escalate / Remediate;")
                lines.append("endif")
                # Note: we close decision immediately (no hanging open_ifs)

            else:  # process
                lines.append(f":{label} [{node.step_no}];")

        # Safety: close any open blocks
        for _ in range(open_ifs):
            lines.append("endif")

        lines.append("")
        lines.append("@enduml")
        return "\n".join(lines)
