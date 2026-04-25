"""
MatplotlibFlowchartRenderer — top-down vertical flowchart from a DiagramSpec.

Visual design system (spec §1–§11):
  Canvas  : 9.0" wide (≈ 900u), height dynamic
  Colors  : matches swimlane — #2563EB process · #F59E0B decision · #10B981 start/end
  Fonts   : Segoe UI / Calibri, 12pt nodes · 11pt phase banners · 13pt title
  Shapes  : fixed-tier heights — SMALL 0.60" (≤5 words) · MEDIUM 0.80" (≤7 words)
  Connectors : orthogonal only, 1.2pt, zorder=2 (behind shapes at zorder=4)
    - "Yes" branch: straight down from diamond bottom
    - "No" / "Fail" branch: orthogonal right detour → re-enter from right side
  Text    : centred H+V, zorder=6

No LLM. No external dependencies. Pure matplotlib.

Pipeline position:
    DiagramSpec → MatplotlibFlowchartRenderer → PNG bytes
"""
from __future__ import annotations

import io
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

from .procedure_parser import DiagramSpec, DiagramNode

# Import the shared design-system constants from the swimlane renderer
from .matplotlib_renderer import (
    C_TITLE, C_TITLE_FG,
    C_HDR_BG, C_HDR_FG,
    C_PROCESS, C_PROCESS_BD, C_PROCESS_FG,
    C_DECISION, C_DECISION_BD, C_DECISION_FG,
    C_STARTEND, C_STARTEND_BD, C_STARTEND_FG,
    C_ARROW, C_WHITE,
    FONT_NODE, FONT_PHASE, FONT_TITLE, FONT_EDGE,
    LINE_H_PT, CONN_LW, BORDER_LW,
    _try_font,
)


# ── Flowchart-specific layout constants (all in inches) ───────────────────────
FIG_W         = 9.00   # figure width (≈ 900 logical units)
COL_X         = 4.50   # centre x of main flow column
NODE_W        = 5.40   # process / oval width (max 7 words at 12pt fits cleanly)
DEC_W         = 4.20   # decision diamond width
NODE_H_SMALL  = 0.60   # height tier: ≤ 5 words  (spec §4)
NODE_H_MEDIUM = 0.90   # height tier: ≤ 7 words  (diamond needs extra vertical)
Y_GAP         = 0.35   # vertical gap between consecutive nodes  (spec §7 ≥ 30u)
PHASE_H       = 0.36   # phase-header banner height
PHASE_GAP     = 0.20   # vertical space above a phase-banner
RIGHT_OFFSET  = 0.65   # x distance from node right edge for "No" detour path


# ── Typography helpers ─────────────────────────────────────────────────────────

def _wrap(text: str, chars: int) -> list[str]:
    lines: list[str] = []
    for para in (text or "").split("\n"):
        if len(para) <= chars:
            lines.append(para)
        else:
            lines.extend(textwrap.wrap(para, chars) or [para])
    return lines or [""]


def _word_count(title: str) -> int:
    return len(title.split())


def _tier_h(title: str, is_decision: bool = False) -> float:
    """Fixed height tier based on word count (spec §4)."""
    base = NODE_H_MEDIUM if is_decision else (
        NODE_H_SMALL if _word_count(title) <= 5 else NODE_H_MEDIUM
    )
    return base


def _text_ml(ax, cx: float, cy: float, lines: list[str],
             sz: float, lh_in: float, color: str, font: str, z: int = 6) -> None:
    """Draw multi-line text centred at (cx, cy)."""
    n = len(lines)
    for i, line in enumerate(lines):
        y = cy + (i - (n - 1) / 2) * lh_in
        ax.text(cx, y, line, fontsize=sz, ha="center", va="center",
                color=color, fontfamily=font, zorder=z, clip_on=False)


def _seg_pts(ax, *pts, z: int = 2) -> None:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    ax.plot(xs, ys, color=C_ARROW, lw=CONN_LW,
            solid_capstyle="round", solid_joinstyle="round", zorder=z)


def _arrow_to(ax, xy: tuple, xytext: tuple, z: int = 2) -> None:
    AP = dict(arrowstyle="->", color=C_ARROW, lw=CONN_LW,
              mutation_scale=9, shrinkA=0, shrinkB=0)
    ax.annotate("", xy=xy, xytext=xytext,
                arrowprops={**AP, "connectionstyle": "arc3,rad=0.0"},
                zorder=z, clip_on=False)


# ── Main renderer ──────────────────────────────────────────────────────────────

class MatplotlibFlowchartRenderer:
    """
    Top-down flowchart with professional design system.

    Layout:
      - Nodes ordered top-to-bottom by (phase_idx, slot_idx)
      - Each phase gets a coloured header banner
      - Decision "Yes" → straight vertical arrow from diamond bottom
      - Decision "No"/"Fail" → orthogonal L: right vertex → right gutter → dest right
      - All connectors at zorder=2 (behind shapes at zorder=4)
    """

    def render(self, spec: DiagramSpec) -> bytes:
        try:
            return self._render(spec)
        except Exception as exc:
            import traceback
            print(f"[FlowchartRenderer] Render failed: {exc}")
            traceback.print_exc()
            return b""

    def _render(self, spec: DiagramSpec) -> bytes:
        font_name = _try_font()
        nodes     = sorted(spec.nodes, key=lambda n: (n.phase_idx, n.slot_idx))
        if not nodes:
            return b""

        # chars-per-line at 12pt for each shape type
        _C_W = 0.062   # inches per char at 12pt
        chars_proc = max(12, int(NODE_W   / _C_W))
        chars_dec  = max(12, int(DEC_W * 0.68 / _C_W))
        chars_oval = max(12, int(NODE_W * 0.80 / _C_W))

        # ── Pass 1: compute heights + y-positions (top-down, y increases down) ─
        info: dict[str, dict] = {}
        y_cursor  = 0.55    # start below title
        prev_phase = -1

        for node in nodes:
            # Insert phase banner gap
            if node.phase_idx != prev_phase:
                if prev_phase >= 0:
                    y_cursor += PHASE_GAP
                y_cursor  += PHASE_H + PHASE_GAP * 0.5
                prev_phase = node.phase_idx

            nt = node.node_type
            if nt in ("start", "end"):
                lines = _wrap(node.title, chars_oval)
                h     = _tier_h(node.title, is_decision=False)
            elif nt == "decision":
                lines = _wrap(node.title, chars_dec)
                h     = _tier_h(node.title, is_decision=True)
            else:
                lines = _wrap(node.title, chars_proc)
                h     = _tier_h(node.title, is_decision=False)

            cy = y_cursor + h / 2
            info[node.node_id] = {
                "lines": lines, "h": h, "cy": cy, "node": node,
            }
            y_cursor = cy + h / 2 + Y_GAP

        fig_h = y_cursor + 0.50

        # ── Pass 2: figure + axes ──────────────────────────────────────────────
        fig, ax = plt.subplots(figsize=(FIG_W, fig_h), dpi=150)
        ax.set_xlim(0, FIG_W)
        ax.set_ylim(fig_h, 0)     # y=0 at top, increases downward
        ax.axis("off")
        fig.patch.set_facecolor(C_WHITE)
        ax.set_facecolor(C_WHITE)

        # Title
        part_sfx = (
            f" — Part {spec.part_no} of {spec.total_parts}"
            if spec.total_parts > 1 else ""
        )
        ax.text(FIG_W / 2, 0.28,
                f"Flowchart: {spec.title}{part_sfx}",
                fontsize=FONT_TITLE, fontweight="bold",
                ha="center", va="center",
                color=C_TITLE, fontfamily=font_name, zorder=10)

        # ── Phase banners ──────────────────────────────────────────────────────
        phase_first: dict[int, str] = {}
        for node in nodes:
            if node.phase_idx not in phase_first:
                phase_first[node.phase_idx] = node.node_id

        drawn: set[int] = set()
        for pi, nid in sorted(phase_first.items()):
            if pi in drawn:
                continue
            drawn.add(pi)
            n_info  = info[nid]
            ph_top  = n_info["cy"] - n_info["h"] / 2 - PHASE_GAP * 0.5 - PHASE_H
            ax.add_patch(plt.Rectangle(
                (0.20, ph_top), FIG_W - 0.40, PHASE_H,
                fc=C_HDR_BG, ec="none", zorder=2, clip_on=False))
            ph_label = nodes[next(
                i for i, n in enumerate(nodes) if n.phase_idx == pi
            )].phase or f"Phase {pi + 1}"
            ax.text(FIG_W / 2, ph_top + PHASE_H / 2, ph_label,
                    fontsize=FONT_PHASE, fontweight="bold",
                    ha="center", va="center",
                    color=C_HDR_FG, fontfamily=font_name, zorder=5)

        # ── Draw connectors (zorder=2, behind shapes) ──────────────────────────
        RIGHT_X = COL_X + NODE_W / 2 + RIGHT_OFFSET   # x-coord of right detour

        for edge in spec.edges:
            if edge.from_id not in info or edge.to_id not in info:
                continue
            if edge.from_id == edge.to_id:
                continue

            src_info = info[edge.from_id]
            dst_info = info[edge.to_id]
            src_node = src_info["node"]
            sh, dh   = src_info["h"], dst_info["h"]
            sx = COL_X
            # In top-down coords: bottom of source = cy + h/2 (larger y)
            #                     top of dest      = cy - h/2 (smaller y)
            sy = src_info["cy"] + sh / 2    # bottom of source shape
            dx = COL_X
            dy = dst_info["cy"] - dh / 2   # top of dest shape
            cond_lc = (edge.condition or "").strip().lower()

            is_no = (
                src_node.node_type == "decision"
                and ("no" in cond_lc or "fail" in cond_lc or "else" in cond_lc)
            )

            if is_no:
                # Orthogonal No-branch (spec §8: right-angle routing only)
                # diamond right vertex → right gutter → dest right edge
                dia_rx  = COL_X + DEC_W / 2       # right vertex x
                dia_my  = src_info["cy"]           # diamond centre y
                dest_rx = COL_X + NODE_W / 2      # right edge of dest node
                dst_cy  = dst_info["cy"]

                _seg_pts(ax,
                         (dia_rx,  dia_my),
                         (RIGHT_X, dia_my),
                         (RIGHT_X, dst_cy), z=2)
                _arrow_to(ax, (dest_rx, dst_cy), (RIGHT_X + 0.01, dst_cy), z=2)

                # Condition label at the detour bend
                ax.text(dia_rx + 0.08, dia_my - 0.07,
                        edge.condition or "No", fontsize=FONT_EDGE,
                        color=C_ARROW, ha="left", va="bottom",
                        fontfamily=font_name, zorder=7)

            else:
                # Straight vertical arrow (Yes / unlabelled)
                if src_node.node_type == "decision":
                    sy = src_info["cy"] + sh / 2   # bottom tip of diamond
                _arrow_to(ax, (dx, dy), (sx, sy), z=2)
                if edge.condition:
                    ax.text(sx + 0.10, (sy + dy) / 2,
                            edge.condition, fontsize=FONT_EDGE,
                            color=C_ARROW, ha="left", va="center",
                            fontfamily=font_name, zorder=7)

        # ── Draw shapes ON TOP of connectors (zorder=4) ───────────────────────
        for node in nodes:
            n_info  = info[node.node_id]
            lines   = n_info["lines"]
            h, cy   = n_info["h"], n_info["cy"]
            nt      = node.node_type

            if nt in ("start", "end"):
                ax.add_patch(mpatches.Ellipse(
                    (COL_X, cy), NODE_W, h,
                    fc=C_STARTEND, ec=C_STARTEND_BD, lw=BORDER_LW,
                    zorder=4, clip_on=False))
                _text_ml(ax, COL_X, cy, lines,
                         FONT_NODE, LINE_H_PT, C_STARTEND_FG, font_name, z=6)

            elif nt == "decision":
                dw = DEC_W
                xs = [COL_X,         COL_X + dw / 2, COL_X,         COL_X - dw / 2, COL_X]
                ys = [cy - h / 2,    cy,              cy + h / 2,    cy,              cy - h / 2]
                ax.fill(xs, ys,
                        fc=C_DECISION, ec=C_DECISION_BD,
                        lw=BORDER_LW, zorder=4, clip_on=False)
                _text_ml(ax, COL_X, cy, lines,
                         FONT_NODE, LINE_H_PT, C_DECISION_FG, font_name, z=6)

            else:  # process
                corner_r = min(0.10, h * 0.18)
                ax.add_patch(FancyBboxPatch(
                    (COL_X - NODE_W / 2, cy - h / 2), NODE_W, h,
                    boxstyle=f"round,pad={corner_r}",
                    fc=C_PROCESS, ec=C_PROCESS_BD, lw=BORDER_LW,
                    zorder=4, clip_on=False))
                _text_ml(ax, COL_X, cy, lines,
                         FONT_NODE, LINE_H_PT, C_PROCESS_FG, font_name, z=6)

        # ── Export ─────────────────────────────────────────────────────────────
        buf = io.BytesIO()
        plt.tight_layout(pad=0.10)
        fig.savefig(buf, format="png", dpi=150,
                    bbox_inches="tight", facecolor=C_WHITE, edgecolor="none")
        plt.close(fig)
        buf.seek(0)
        return buf.read()
