"""
Matplotlib Renderer — renders a LayoutGrid into a professional swimlane PNG.

Visual design system (spec §1–§11):
  Canvas  : 960×540 logical units (16:9), 1u = 0.01", rendered @150 DPI
  Colors  : #2563EB process · #F59E0B decision · #10B981 start/end · #F3F4F6 lanes
  Fonts   : Segoe UI (Calibri / DejaVu Sans fallback), 12pt nodes · 11pt headers · 13pt title
  Shapes  : rounded-rect (process) · diamond (decision) · ellipse (start/end)
  Connectors : orthogonal (right-angle) only, 1.2pt, zorder=2 (behind shapes)
  Text    : always centred H+V, zorder=6 (above shapes)
  Borders : 1.5pt solid, slightly darker than fill

No LLM. Fully deterministic from the LayoutGrid.

Pipeline position:
    LayoutGrid → MatplotlibRenderer → PNG bytes
"""
from __future__ import annotations

import io
import textwrap

from .layout_engine import (
    LayoutGrid, LABEL_W, PHASE_W, TITLE_H, HDR_H,
    NODE_MAX_W, _chars_per_line, _snap,
)


# ── Professional color palette (spec §6) ───────────────────────────────────────

# Title / chrome
C_TITLE      = "#1E3A5F"   # deep navy — title bar
C_TITLE_FG   = "#FFFFFF"

# Phase column headers
C_HDR_BG     = "#1E40AF"   # deep blue
C_HDR_FG     = "#FFFFFF"

# Lane backgrounds (spec: #F3F4F6)
C_LANE_BG    = "#F3F4F6"   # light gray cell fill
C_LANE_LBL_0 = "#E5E7EB"   # even lane label column
C_LANE_LBL_1 = "#D1D5DB"   # odd lane label column
C_LANE_LABEL = "#1E3A5F"   # label text color

# Grid lines
C_GRID       = "#D1D5DB"   # cell border / grid lines
C_SEP        = "#9CA3AF"   # dashed column separator

# Process nodes — blue (spec §6)
C_PROCESS    = "#2563EB"
C_PROCESS_BD = "#1D4ED8"   # slightly darker border
C_PROCESS_FG = "#FFFFFF"   # white text on blue

# Decision nodes — amber (spec §6)
C_DECISION    = "#F59E0B"
C_DECISION_BD = "#D97706"
C_DECISION_FG = "#111827"  # dark text on amber

# Start/End nodes — green (spec §6)
C_STARTEND    = "#10B981"
C_STARTEND_BD = "#059669"
C_STARTEND_FG = "#FFFFFF"

# Connectors + misc
C_ARROW      = "#374151"   # dark gray connectors
C_TEXT       = "#111827"   # body text (spec)
C_WHITE      = "#FFFFFF"


# ── Typography (spec §5) ───────────────────────────────────────────────────────

FONT_FAMILY   = "Segoe UI"
_FONT_FALLBACK = ["Calibri", "DejaVu Sans", "Arial"]

FONT_NODE     = 12         # pt — node labels (spec: 12–14 pt)
FONT_LANE     = 11         # pt — lane role labels  (spec: 16 pt; scaled for narrow col)
FONT_PHASE    = 11         # pt — phase headers
FONT_TITLE    = 13         # pt — diagram title (spec: 20 pt; scaled for banner height)
FONT_EDGE     = 8          # pt — connector condition labels

LINE_SPACING  = 1.15       # spec: 1.1–1.2
LINE_H_PT     = FONT_NODE * LINE_SPACING / 72   # line height in inches at 12pt

CONN_LW       = 1.2        # connector line width pt (spec: 1–1.5 pt)
BORDER_LW     = 1.5        # node border width pt


# ── Font resolver ──────────────────────────────────────────────────────────────

def _try_font() -> str:
    """Return the best available font family installed on this system."""
    try:
        import matplotlib.font_manager as fm
        families = {f.name for f in fm.fontManager.ttflist}
        for f in [FONT_FAMILY] + _FONT_FALLBACK:
            if f in families:
                return f
    except Exception:
        pass
    return "DejaVu Sans"


# ── Renderer ───────────────────────────────────────────────────────────────────

class MatplotlibRenderer:
    """
    Renders a LayoutGrid as a Visio-style horizontal swimlane PNG.

    Shape legend (spec §3):
        start / end  → green ellipse (pill)
        decision     → amber diamond
        process      → blue rounded rectangle, white text centred

    Connector rules (spec §8):
        Orthogonal (right-angle) routing ONLY — no diagonal or curved lines.
        Connectors drawn at zorder=2, shapes at zorder=4, text at zorder=6.
        Backward same-lane arrows routed below the lane bottom.
    """

    def render(self, grid: LayoutGrid) -> bytes | None:
        try:
            return self._render(grid)
        except Exception as exc:
            import traceback
            print(f"[MatplotlibRenderer] Render failed: {exc}")
            traceback.print_exc()
            return None

    # ── Core renderer ──────────────────────────────────────────────────────────

    def _render(self, grid: LayoutGrid) -> bytes | None:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        from matplotlib.patches import FancyBboxPatch

        font_name = _try_font()
        spec      = grid.spec
        n_phases  = len(spec.phases)
        n_roles   = len(spec.roles)
        col_w     = grid.col_w
        nw        = grid.node_w
        cpl       = _chars_per_line(nw)

        # ── Figure setup ───────────────────────────────────────────────────────
        fig, ax = plt.subplots(figsize=(grid.fig_w, grid.fig_h), dpi=150)
        ax.set_xlim(0, grid.fig_w)
        ax.set_ylim(0, grid.fig_h)
        ax.axis("off")
        fig.patch.set_facecolor(C_WHITE)
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

        # ── Drawing primitives ─────────────────────────────────────────────────

        def _rect(x, y, w, h, fc, ec, lw=1.0, z=1):
            ax.add_patch(mpatches.Rectangle(
                (x, y), w, h, fc=fc, ec=ec, lw=lw,
                zorder=z, clip_on=False))

        def _txt(x, y, s, sz=FONT_NODE, bold=False, color=C_TEXT,
                 ha="center", va="center", z=6):
            ax.text(x, y, s, ha=ha, va=va, fontsize=sz, color=color, zorder=z,
                    fontweight="bold" if bold else "normal",
                    fontfamily=font_name, clip_on=False)

        def _wrap(s: str, w: int) -> list[str]:
            """Wrap text to at most w chars per line. Never truncates."""
            lines = textwrap.wrap(s, width=max(8, w), break_long_words=False)
            return lines or [s]

        def _multiline(cx: float, cy: float, lines: list[str],
                       sz: float, lh_in: float, color: str,
                       bold: bool = False, z: int = 6) -> None:
            """Draw multi-line text centred at (cx, cy), z=6 (above shapes)."""
            n   = len(lines)
            top = cy + (n - 1) * lh_in / 2
            for i, line in enumerate(lines):
                _txt(cx, top - i * lh_in, line, sz=sz,
                     color=color, bold=bold, z=z)

        def _trunc(s: str, n: int) -> str:
            return s[: n - 1] + "\u2026" if len(s) > n else s

        # Connector primitives — zorder=2 (behind shapes at zorder=4)
        def _seg(*pts, z: int = 2, lw: float = CONN_LW) -> None:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            ax.plot(xs, ys, color=C_ARROW, lw=lw,
                    solid_capstyle="round", solid_joinstyle="round", zorder=z)

        def _arrow_to(xy: tuple, xytext: tuple, z: int = 2) -> None:
            AP = dict(arrowstyle="->", color=C_ARROW, lw=CONN_LW,
                      mutation_scale=9, shrinkA=0, shrinkB=0)
            ax.annotate("", xy=xy, xytext=xytext,
                        arrowprops={**AP, "connectionstyle": "arc3,rad=0.0"},
                        zorder=z, clip_on=False)

        def _lbl_edge(x: float, y: float, text: str, z: int = 8) -> None:
            ax.text(x, y, text, fontsize=FONT_EDGE, ha="center", va="bottom",
                    color=C_ARROW, zorder=z, fontfamily=font_name,
                    bbox=dict(fc=C_WHITE, ec="none", pad=0.5, alpha=0.85))

        # ── Title bar ──────────────────────────────────────────────────────────
        ty = grid.fig_h - TITLE_H
        _rect(0, ty, grid.fig_w, TITLE_H, fc=C_TITLE, ec=C_TITLE, lw=0, z=2)
        _txt(grid.fig_w / 2, ty + TITLE_H / 2,
             _trunc(spec.title, 80), sz=FONT_TITLE,
             bold=True, color=C_TITLE_FG, z=6)

        # ── Phase column headers ───────────────────────────────────────────────
        hy      = ty - HDR_H
        hdr_cpl = max(8, _chars_per_line(col_w * 0.85))
        # Empty corner cell
        _rect(0, hy, LABEL_W, HDR_H, fc=C_HDR_BG, ec=C_HDR_BG, lw=0, z=2)
        for pi, ph_name in enumerate(spec.phases):
            px = LABEL_W + pi * col_w
            _rect(px, hy, col_w, HDR_H, fc=C_HDR_BG, ec=C_WHITE, lw=1.0, z=2)
            ph_lines = _wrap(ph_name, hdr_cpl)
            _multiline(px + col_w / 2, hy + HDR_H / 2,
                       ph_lines, sz=FONT_PHASE, lh_in=LINE_H_PT,
                       color=C_HDR_FG, bold=True, z=5)

        # ── Role lanes ────────────────────────────────────────────────────────
        lbl_cpl = max(6, _chars_per_line(LABEL_W * 0.75))
        for ri, role in enumerate(spec.roles):
            ry  = grid.lane_y[ri]
            lh  = grid.lane_heights[ri]
            lbl_bg = C_LANE_LBL_0 if ri % 2 == 0 else C_LANE_LBL_1
            # Grid cells
            for pi in range(n_phases):
                _rect(LABEL_W + pi * col_w, ry, col_w, lh,
                      fc=C_LANE_BG, ec=C_GRID, lw=0.5, z=1)
            # Role label column
            _rect(0, ry, LABEL_W, lh, fc=lbl_bg, ec=C_GRID, lw=1.0, z=2)
            rl = _wrap(role, lbl_cpl)
            _multiline(LABEL_W / 2, ry + lh / 2, rl,
                       sz=FONT_LANE, lh_in=LINE_H_PT,
                       color=C_LANE_LABEL, bold=True, z=5)

        # Dashed column separators (thin, decorative)
        for pi in range(1, n_phases):
            sx = LABEL_W + pi * col_w
            ax.plot([sx, sx], [0, hy], ls="--", color=C_SEP, lw=0.6, zorder=3)

        # ── Build node lookup ─────────────────────────────────────────────────
        node_map = {n.node_id: n for n in spec.nodes}

        # ── Draw connectors FIRST (zorder=2, behind shapes at zorder=4) ───────
        for edge in spec.edges:
            if edge.from_id not in grid.positions or edge.to_id not in grid.positions:
                continue
            if edge.from_id == edge.to_id:
                continue

            from_node = node_map.get(edge.from_id)
            to_node   = node_map.get(edge.to_id)
            if not from_node or not to_node:
                continue

            fg = grid.positions[edge.from_id]
            tg = grid.positions[edge.to_id]
            x1, y1, hw1, hh1 = fg.cx, fg.cy, fg.hw, fg.hh
            x2, y2, hw2, hh2 = tg.cx, tg.cy, tg.hw, tg.hh

            ci_from = from_node.phase_idx
            ci_to   = to_node.phase_idx
            ri_from = from_node.role_idx
            ri_to   = to_node.role_idx

            same_lane = (ri_from == ri_to)
            same_col  = (ci_from == ci_to)
            forward   = ci_to >= ci_from

            if same_lane and same_col:
                # ── Stacked in same cell: straight vertical arrow ─────────────
                going_down = y2 < y1
                if going_down:
                    _arrow_to((x2, y2 + hh2), (x1, y1 - hh1))
                else:
                    _arrow_to((x2, y2 - hh2), (x1, y1 + hh1))
                if edge.condition:
                    _lbl_edge(x1, (y1 + y2) / 2, edge.condition)

            elif same_lane and not same_col:
                if forward:
                    # ── Forward: horizontal stair-step (orthogonal) ───────────
                    ex,  ey  = x1 + hw1, y1
                    enx, eny = x2 - hw2, y2
                    bnd_x = _snap(LABEL_W + (ci_from + 1) * col_w)
                    if abs(ey - eny) < 0.02:
                        # Same height — straight horizontal arrow
                        _arrow_to((enx, eny), (ex, ey))
                    else:
                        # L-shaped: right → bend at phase boundary → right
                        _seg((ex, ey), (bnd_x, ey), (bnd_x, eny))
                        _arrow_to((enx, eny), (bnd_x, eny))
                    if edge.condition:
                        _lbl_edge(bnd_x + (enx - bnd_x) * 0.5,
                                  eny + 0.06, edge.condition)
                else:
                    # ── Backward: route BELOW the lane bottom (orthogonal) ────
                    # Exit from bottom of source, go below lane, enter bottom of dest
                    below_y = _snap(grid.lane_y[ri_from] - 0.14)
                    ex,  ey  = x1, y1 - hh1    # bottom of source
                    enx, eny = x2, y2 - hh2    # bottom of dest
                    _seg((ex, ey), (ex, below_y), (enx, below_y))
                    _arrow_to((enx, eny), (enx, below_y))
                    if edge.condition:
                        _lbl_edge((ex + enx) / 2, below_y - 0.04, edge.condition)

            else:
                # ── Cross-lane ────────────────────────────────────────────────
                going_down = y2 < y1
                if going_down:
                    ex,  ey  = x1, y1 - hh1    # bottom of source
                    enx, eny = x2, y2 + hh2    # top of dest
                else:
                    ex,  ey  = x1, y1 + hh1    # top of source
                    enx, eny = x2, y2 - hh2    # bottom of dest

                if same_col:
                    # Same column, different lane: route via right gutter
                    if ci_from < n_phases - 1:
                        gx   = _snap(LABEL_W + (ci_from + 1) * col_w - 0.05)
                        gex  = x1 + hw1
                        genx = x2 + hw2
                    else:
                        gx   = _snap(LABEL_W + ci_from * col_w + 0.05)
                        gex  = x1 - hw1
                        genx = x2 - hw2
                    _seg((gex, y1), (gx, y1), (gx, y2))
                    _arrow_to((genx, y2), (gx, y2))
                    if edge.condition:
                        off = 0.08 if ci_from < n_phases - 1 else -0.08
                        _lbl_edge(gx + off, (y1 + y2) / 2, edge.condition)
                else:
                    # Different column + different lane: L-shaped orthogonal
                    right_gutter = _snap(LABEL_W + (ci_from + 1) * col_w - 0.05)
                    left_gutter  = _snap(LABEL_W + ci_from * col_w + 0.05)
                    if going_down:
                        channel_y = _snap(
                            grid.lane_y[ri_to] + grid.lane_heights[ri_to] - 0.10
                        )
                    else:
                        channel_y = _snap(grid.lane_y[ri_to] + 0.10)
                    route_x = right_gutter if ci_to >= ci_from else left_gutter
                    _seg((ex, ey), (route_x, ey),
                         (route_x, channel_y), (enx, channel_y))
                    _arrow_to((enx, eny), (enx, channel_y))
                    if edge.condition:
                        _lbl_edge(
                            (route_x + enx) / 2, channel_y + 0.06, edge.condition
                        )

        # ── Draw shapes ON TOP of connectors (zorder=4, text at zorder=6) ──────
        for node in spec.nodes:
            geo = grid.positions.get(node.node_id)
            if not geo:
                continue
            cx, cy, hw, hh = geo.cx, geo.cy, geo.hw, geo.hh
            label = node.title
            lines = _wrap(label, cpl)

            if node.node_type in ("start", "end"):
                ew, eh = hw * 2, hh * 2
                ax.add_patch(mpatches.Ellipse(
                    (cx, cy), ew, eh,
                    fc=C_STARTEND, ec=C_STARTEND_BD, lw=BORDER_LW,
                    zorder=4, clip_on=False))
                oval_cpl = max(8, _chars_per_line(ew * 0.80))
                oval_lines = _wrap(label, oval_cpl)
                _multiline(cx, cy, oval_lines, sz=FONT_NODE,
                           lh_in=LINE_H_PT, color=C_STARTEND_FG, bold=True, z=6)

            elif node.node_type == "decision":
                dw, dh = hw * 2, hh * 2
                ax.add_patch(plt.Polygon(
                    [[cx, cy + dh / 2], [cx + dw / 2, cy],
                     [cx, cy - dh / 2], [cx - dw / 2, cy]],
                    closed=True,
                    fc=C_DECISION, ec=C_DECISION_BD, lw=BORDER_LW,
                    zorder=4, clip_on=False))
                d_cpl = max(8, _chars_per_line(dw * 0.68))
                d_lines = _wrap(label, d_cpl)
                _multiline(cx, cy, d_lines, sz=FONT_NODE,
                           lh_in=LINE_H_PT, color=C_DECISION_FG, z=6)

            else:  # process
                bw, bh    = hw * 2, hh * 2
                corner_r  = min(0.10, bh * 0.18)
                ax.add_patch(FancyBboxPatch(
                    (cx - bw / 2, cy - bh / 2), bw, bh,
                    boxstyle=f"round,pad={corner_r}",
                    fc=C_PROCESS, ec=C_PROCESS_BD, lw=BORDER_LW,
                    zorder=4, clip_on=False))
                _multiline(cx, cy, lines, sz=FONT_NODE,
                           lh_in=LINE_H_PT, color=C_PROCESS_FG, z=6)

        # ── Export ─────────────────────────────────────────────────────────────
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150,
                    bbox_inches="tight", facecolor=C_WHITE, pad_inches=0.05)
        plt.close(fig)
        buf.seek(0)
        data = buf.read()
        return data if data[:4] == b"\x89PNG" else None
