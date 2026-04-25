"""
Graphviz Renderer — optional alternative renderer for swimlane diagrams.

Uses DOT language with rank=same constraints to enforce phase column alignment.
Each phase becomes a cluster subgraph. Role grouping is indicated by node color.

Requires: graphviz Python package + Graphviz binary installed.
Install:   pip install graphviz  &&  apt-get install graphviz

Pipeline position:
    DiagramSpec → GraphvizRenderer → DOT string → Graphviz binary → PNG bytes
"""
from __future__ import annotations

import re

from .procedure_parser import DiagramSpec, DiagramNode


# ── Shape / color maps ─────────────────────────────────────────────────────────

_SHAPE: dict[str, str] = {
    "start":    "oval",
    "end":      "oval",
    "decision": "diamond",
    "process":  "box",
}

_FILL: dict[str, str] = {
    "start":    "#1F3864",
    "end":      "#1F3864",
    "decision": "#FFF2CC",
    "process":  "#DEEAF1",
}

_FONT_COLOR: dict[str, str] = {
    "start": "white",
    "end":   "white",
}

# Role-row tint colors (cycles through this list)
_ROW_TINTS = [
    "#EBF3FB", "#F7FBFF", "#E8F4E8", "#FFF8EC",
    "#F5F0FF", "#FFF0F0", "#F0FFFF", "#FFFAF0",
]


def _dot_id(s: str) -> str:
    """Make a safe DOT identifier."""
    return re.sub(r"\W", "_", s)


class GraphvizRenderer:
    """
    Converts a DiagramSpec into a Graphviz DOT string.

    Layout strategy:
      - Each phase → cluster subgraph with rank=same
      - Nodes labeled with step_no + title
      - Role rows indicated by fillcolor (cycling palette)
      - Edges are routed orthogonally via splines=ortho
    """

    def render(self, spec: DiagramSpec) -> str:
        from collections import defaultdict

        phase_nodes: dict[int, list[DiagramNode]] = defaultdict(list)
        for node in spec.nodes:
            phase_nodes[node.phase_idx].append(node)

        # Assign tint color per role index
        role_tint = {
            ri: _ROW_TINTS[ri % len(_ROW_TINTS)]
            for ri in range(len(spec.roles))
        }

        lines = [
            "digraph swimlane {",
            '    graph [rankdir=LR, splines=ortho, nodesep=0.4, ranksep=1.0,',
            '           bgcolor="white", fontname="Arial", fontsize=11];',
            '    node  [fontname="Arial", fontsize=9, style="filled,rounded",'
            '           margin="0.12,0.06"];',
            '    edge  [fontname="Arial", fontsize=8, color="#404040"];',
            "",
        ]

        # Phase cluster subgraphs
        for pi, ph_name in enumerate(spec.phases):
            nodes_in_phase = sorted(
                phase_nodes[pi], key=lambda n: (n.role_idx, n.slot_idx)
            )
            lines.append(f"    subgraph cluster_p{pi} {{")
            lines.append(f'        label="{ph_name}";')
            lines.append("        style=filled;")
            lines.append('        fillcolor="#F0F6FF";')
            lines.append('        color="#4472C4";')
            lines.append("        fontsize=10;")
            lines.append("        fontname=\"Arial\";")
            lines.append("        rank=same;")
            for node in nodes_in_phase:
                nid   = _dot_id(node.node_id)
                shape = _SHAPE.get(node.node_type, "box")
                fill  = role_tint.get(node.role_idx, "#DEEAF1")
                if node.node_type in ("start", "end"):
                    fill = _FILL[node.node_type]
                elif node.node_type == "decision":
                    fill = _FILL["decision"]
                fc    = _FONT_COLOR.get(node.node_type, "#1A1A2E")
                lbl   = node.title.replace('"', '\\"')
                role  = spec.roles[node.role_idx] if node.role_idx < len(spec.roles) else ""
                lines.append(
                    f'        {nid} [label="{node.step_no}\\n{lbl}\\n({role})", '
                    f'shape={shape}, fillcolor="{fill}", fontcolor="{fc}"];'
                )
            lines.append("    }")
            lines.append("")

        # Edges
        node_dot_id = {n.node_id: _dot_id(n.node_id) for n in spec.nodes}
        for edge in spec.edges:
            src = node_dot_id.get(edge.from_id)
            dst = node_dot_id.get(edge.to_id)
            if src and dst:
                lbl_attr = f' [label="{edge.condition}"]' if edge.condition else ""
                lines.append(f"    {src} -> {dst}{lbl_attr};")

        lines.append("}")
        return "\n".join(lines)

    def render_to_png(self, spec: DiagramSpec) -> bytes | None:
        """Render DOT to PNG using the graphviz binary (requires graphviz installed)."""
        try:
            import graphviz
            dot_src = self.render(spec)
            src = graphviz.Source(dot_src)
            return src.pipe(format="png")
        except ImportError:
            print("[GraphvizRenderer] graphviz package not installed. pip install graphviz")
            return None
        except Exception as exc:
            print(f"[GraphvizRenderer] Render failed: {exc}")
            return None
