"""
Layout Engine — deterministic pixel positions for all diagram nodes.

Grid spec (spec §1):
  Canvas  : 960 × 540 logical units (16:9 PowerPoint / Word slide)
  Scale   : 1 logical unit = 0.01 inches  →  960u = 9.60"  540u = 5.40"
  Grid    : 12-column × 60u columns, 20u gutters
  Snap    : all positions rounded to nearest GRID_UNIT (0.01")

Node sizing (spec §4):
  Min width  : 120u = 1.20"
  Max width  : 220u = 2.20"
  Height tiers (fixed, selected by word count):
    Small  : 60u = 0.60"  (≤ 5 words)
    Medium : 80u = 0.80"  (≤ 7 words — parser enforces this upper bound)

Lane geometry (spec §2):
  Min lane height : 120u = 1.20"
  Padding top/bottom : 20u = 0.20"
  Cell gap (stacked nodes) : 30u = 0.30"

Typography (spec §5):
  char_width at 12pt Segoe UI / Calibri ≈ 0.062" per character

No LLM. Fully deterministic from DiagramSpec.

Pipeline position:
    DiagramSpec → LayoutEngine → LayoutGrid
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict

from .procedure_parser import DiagramSpec, DiagramNode


# ── Grid constants (all in figure-inches, 1 unit = 0.01") ─────────────────────
GRID_UNIT    = 0.01    # snap granularity — 1 logical unit

# Canvas column layout
LABEL_W      = 1.80   # role-label column  (180u)
PHASE_W      = 2.40   # per-phase column   (240u  — 4 × 60u grid columns)
TITLE_H      = 0.44   # title bar          (44u)
HDR_H        = 0.40   # phase header row   (40u)

# Node sizing (spec §4)
NODE_MIN_W   = 1.20   # 120u  minimum node width
NODE_MAX_W   = 2.20   # 220u  maximum node width
NODE_H_SMALL  = 0.60  # 60u   ≤ 5 words
NODE_H_MEDIUM = 0.80  # 80u   ≤ 7 words (parser enforces this upper bound)

# Lane geometry (spec §2)
LANE_H_MIN   = 1.20   # 120u  minimum lane height
LANE_PAD_V   = 0.20   # 20u   top/bottom lane padding
CELL_GAP     = 0.30   # 30u   vertical gap between stacked nodes in a cell

# Typography — average character width at 12pt Segoe UI / Calibri (empirical)
_CHAR_W      = 0.062   # inches per average character at 12pt


# ── Public helpers (used by renderers) ────────────────────────────────────────

def _snap(v: float) -> float:
    """Snap value to nearest GRID_UNIT (0.01")."""
    return round(v / GRID_UNIT) * GRID_UNIT


def _word_count(title: str) -> int:
    return len(title.split())


def _tier_h(title: str) -> float:
    """
    Return fixed height tier based on word count.
    ≤ 5 words → SMALL (0.60"), ≤ 7 words → MEDIUM (0.80").
    Parser guarantees max 7 words, so no third tier is needed.
    """
    return NODE_H_SMALL if _word_count(title) <= 5 else NODE_H_MEDIUM


def _node_width(col_w: float) -> float:
    """Compute node width: 88% of column, clamped to [NODE_MIN_W, NODE_MAX_W]."""
    return _snap(min(NODE_MAX_W, max(NODE_MIN_W, col_w * 0.88)))


def _chars_per_line(nw: float) -> int:
    """Characters that fit on one line at 12pt in a node of width nw inches."""
    return max(12, int(nw / _CHAR_W))


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class NodeGeometry:
    node_id:   str
    cx:        float     # centre x (figure inches, grid-snapped)
    cy:        float     # centre y (figure inches, grid-snapped)
    hw:        float     # half-width  of bounding box
    hh:        float     # half-height of bounding box
    phase_idx: int
    role_idx:  int


@dataclass
class LayoutGrid:
    """Fully computed, deterministic layout for one DiagramSpec."""
    spec:         DiagramSpec
    # Derived constants
    col_w:        float             # phase column width
    row_h:        float             # max lane height (informational)
    lane_heights: list[float]       # per-role lane height
    lane_y:       list[float]       # y-offset of BOTTOM of each lane
    positions:    dict[str, NodeGeometry]
    fig_w:        float
    fig_h:        float
    # Node width (computed by layout, consumed by renderers)
    node_w:       float = NODE_MAX_W
    # Pass-through constants for renderers
    label_w:      float = LABEL_W
    title_h:      float = TITLE_H
    hdr_h:        float = HDR_H


# ── Layout engine ──────────────────────────────────────────────────────────────
##DO NOT FUCKING TOUCH!!!!
class LayoutEngine:
    """
    Computes a LayoutGrid from a DiagramSpec.
    Identical inputs always produce identical outputs (fully deterministic).
    All positions are grid-snapped to 0.01".
    """

    def compute(self, spec: DiagramSpec) -> LayoutGrid:
        n_phases = len(spec.phases)
        n_roles  = len(spec.roles)

        col_w = PHASE_W
        nw    = _node_width(col_w)

        # ── Cell occupancy ─────────────────────────────────────────────────────
        cell_nodes: dict[tuple[int, int], list[DiagramNode]] = defaultdict(list)
        for node in spec.nodes:
            cell_nodes[(node.phase_idx, node.role_idx)].append(node)

        for k in cell_nodes:
            cell_nodes[k].sort(key=lambda n: n.slot_idx)

        # ── Node bounding-box helpers ──────────────────────────────────────────

        def _hw_hh(node: DiagramNode) -> tuple[float, float]:
            """Half-width and half-height for edge routing (grid-snapped)."""
            h = _tier_h(node.title)
            if node.node_type in ("start", "end"):
                return _snap(nw * 0.48), _snap(h * 0.50)
            if node.node_type == "decision":
                return _snap(nw * 0.46), _snap(h * 0.50)
            return _snap(nw / 2), _snap(h / 2)

        def _visual_h(node: DiagramNode) -> float:
            """Actual rendered height = hh × 2."""
            _, hh = _hw_hh(node)
            return hh * 2

        # ── Per-cell stack heights ─────────────────────────────────────────────

        def _cell_stack_h(pi: int, ri: int) -> float:
            nodes = cell_nodes.get((pi, ri), [])
            if not nodes:
                return 0.0
            total = sum(_visual_h(n) for n in nodes)
            total += CELL_GAP * max(0, len(nodes) - 1)
            return total

        # ── Per-role lane heights (≥ LANE_H_MIN, content-driven) ──────────────

        def _lane_h(ri: int) -> float:
            max_stack = max(
                (_cell_stack_h(pi, ri) for pi in range(n_phases)),
                default=0.0,
            )
            return _snap(max(LANE_H_MIN, max_stack + 2 * LANE_PAD_V))

        lane_heights = [_lane_h(ri) for ri in range(n_roles)]
        total_lane_h = sum(lane_heights)

        # ── Lane y-offsets (bottom-up: role 0 is topmost visually) ────────────
        lane_y: list[float] = [0.0] * n_roles
        y_cur = 0.0
        for ri in range(n_roles - 1, -1, -1):
            lane_y[ri] = _snap(y_cur)
            y_cur += lane_heights[ri]

        # ── Figure dimensions ──────────────────────────────────────────────────
        # Minimum width = 6.50" to fit in Word column; expands with phase count
        fig_w = _snap(max(6.50, LABEL_W + n_phases * PHASE_W))
        fig_h = _snap(TITLE_H + HDR_H + total_lane_h)

        # ── Node pixel positions — stacked and vertically centred per cell ─────
        positions: dict[str, NodeGeometry] = {}

        for (pi, ri), nodes in cell_nodes.items():
            cx_cell = _snap(LABEL_W + pi * col_w + col_w / 2)
            ry      = lane_y[ri]
            lh      = lane_heights[ri]

            # Compute stack dimensions
            stack_h = sum(_visual_h(n) for n in nodes)
            stack_h += CELL_GAP * max(0, len(nodes) - 1)

            # Centre the stack vertically in the lane
            # (top of stack = lane_bottom + lane_h/2 + stack_h/2)
            y_top = _snap(ry + lh / 2 + stack_h / 2)

            y_cursor = y_top
            for node in nodes:
                vh = _visual_h(node)
                cy = _snap(y_cursor - vh / 2)
                hw, hh = _hw_hh(node)
                positions[node.node_id] = NodeGeometry(
                    node_id=node.node_id,
                    cx=cx_cell,
                    cy=cy,
                    hw=hw,
                    hh=hh,
                    phase_idx=pi,
                    role_idx=ri,
                )
                y_cursor = _snap(cy - vh / 2 - CELL_GAP)

        row_h = max(lane_heights) if lane_heights else LANE_H_MIN

        return LayoutGrid(
            spec=spec,
            col_w=col_w,
            row_h=row_h,
            lane_heights=lane_heights,
            lane_y=lane_y,
            positions=positions,
            fig_w=fig_w,
            fig_h=fig_h,
            node_w=nw,
        )
