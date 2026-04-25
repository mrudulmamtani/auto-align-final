"""
Swimlane JSON Serializer — converts LayoutGrid → portable JSON spec.

All positions are pre-converted to Visio coordinate space:
  - Units: inches
  - Origin: bottom-left of page
  - Y increases upward

This intermediate format decouples the Visio renderer from the layout engine,
allowing the same spec to drive other renderers (PPTX, SVG, etc.).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .layout_engine import LayoutGrid, LABEL_W, PHASE_W, TITLE_H, HDR_H


# ── JSON-serializable data classes ─────────────────────────────────────────────

@dataclass
class RectSpec:
    label: str
    cx_in: float   # centre X (Visio coords, inches)
    cy_in: float   # centre Y (Visio coords, inches)
    w_in: float
    h_in: float

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "cx_in": round(self.cx_in, 4),
            "cy_in": round(self.cy_in, 4),
            "w_in": round(self.w_in, 4),
            "h_in": round(self.h_in, 4),
        }


@dataclass
class LaneSpec:
    label: str
    label_rect: RectSpec   # left label column
    bg_rect:    RectSpec   # main swim lane background

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "label_rect": self.label_rect.to_dict(),
            "bg_rect": self.bg_rect.to_dict(),
        }


@dataclass
class NodeSpec:
    id:        str
    label:     str
    node_type: str   # "start" | "end" | "process" | "decision"
    cx_in:     float
    cy_in:     float
    w_in:      float
    h_in:      float

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "node_type": self.node_type,
            "cx_in": round(self.cx_in, 4),
            "cy_in": round(self.cy_in, 4),
            "w_in": round(self.w_in, 4),
            "h_in": round(self.h_in, 4),
        }


@dataclass
class EdgeSpec:
    from_id:   str
    to_id:     str
    condition: str = ""

    def to_dict(self) -> dict:
        return {"from_id": self.from_id, "to_id": self.to_id, "condition": self.condition}


@dataclass
class SwimlaneJsonSpec:
    title:          str
    part_no:        int
    total_parts:    int
    page_w_in:      float
    page_h_in:      float
    title_bar:      RectSpec
    phase_headers:  list[RectSpec]
    lanes:          list[LaneSpec]
    nodes:          list[NodeSpec]
    edges:          list[EdgeSpec]

    def to_dict(self) -> dict:
        return {
            "title":        self.title,
            "part_no":      self.part_no,
            "total_parts":  self.total_parts,
            "page_w_in":    round(self.page_w_in, 4),
            "page_h_in":    round(self.page_h_in, 4),
            "title_bar":    self.title_bar.to_dict(),
            "phase_headers": [p.to_dict() for p in self.phase_headers],
            "lanes":        [l.to_dict() for l in self.lanes],
            "nodes":        [n.to_dict() for n in self.nodes],
            "edges":        [e.to_dict() for e in self.edges],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ── Builder ────────────────────────────────────────────────────────────────────

def build_spec(grid: LayoutGrid) -> SwimlaneJsonSpec:
    """
    Convert a LayoutGrid into a SwimlaneJsonSpec with all positions in Visio coordinates.

    Coordinate mapping (LayoutGrid → Visio):
      Lane area Y:    lane_y[i] is already measured from bottom of lane area.
                      In Visio, the lane area sits at Y=[0, total_lane_h].
                      Node cy values are in this same coordinate space.
      Phase headers:  Visio Y = total_lane_h + HDR_H/2 (centre)
      Title bar:      Visio Y = total_lane_h + HDR_H + TITLE_H/2 (centre)
      Page height:    fig_h = TITLE_H + HDR_H + total_lane_h
    """
    spec         = grid.spec
    total_lane_h = sum(grid.lane_heights)
    page_w       = grid.fig_w
    page_h       = grid.fig_h   # TITLE_H + HDR_H + total_lane_h

    # ── Title bar ──────────────────────────────────────────────────────────────
    title_bar = RectSpec(
        label  = spec.title,
        cx_in  = page_w / 2,
        cy_in  = total_lane_h + HDR_H + TITLE_H / 2,
        w_in   = page_w,
        h_in   = TITLE_H,
    )

    # ── Phase column headers ───────────────────────────────────────────────────
    phase_headers: list[RectSpec] = []
    for pi, phase_name in enumerate(spec.phases):
        phase_headers.append(RectSpec(
            label = phase_name,
            cx_in = LABEL_W + pi * PHASE_W + PHASE_W / 2,
            cy_in = total_lane_h + HDR_H / 2,
            w_in  = PHASE_W,
            h_in  = HDR_H,
        ))

    # ── Swimlane rows ──────────────────────────────────────────────────────────
    lanes: list[LaneSpec] = []
    for ri, role_name in enumerate(spec.roles):
        lh      = grid.lane_heights[ri]
        ly      = grid.lane_y[ri]      # bottom Y of this lane (Visio coords)
        lane_cy = ly + lh / 2

        label_rect = RectSpec(
            label  = role_name,
            cx_in  = LABEL_W / 2,
            cy_in  = lane_cy,
            w_in   = LABEL_W,
            h_in   = lh,
        )
        bg_w = page_w - LABEL_W
        bg_rect = RectSpec(
            label  = "",
            cx_in  = LABEL_W + bg_w / 2,
            cy_in  = lane_cy,
            w_in   = bg_w,
            h_in   = lh,
        )
        lanes.append(LaneSpec(label=role_name, label_rect=label_rect, bg_rect=bg_rect))

    # ── Process nodes ──────────────────────────────────────────────────────────
    nodes: list[NodeSpec] = []
    for node in spec.nodes:
        if node.node_id not in grid.positions:
            continue
        pos = grid.positions[node.node_id]
        nodes.append(NodeSpec(
            id        = node.node_id,
            label     = node.title,
            node_type = node.node_type,
            cx_in     = pos.cx,
            cy_in     = pos.cy,
            w_in      = pos.hw * 2,
            h_in      = pos.hh * 2,
        ))

    # ── Edges ──────────────────────────────────────────────────────────────────
    edges: list[EdgeSpec] = [
        EdgeSpec(from_id=e.from_id, to_id=e.to_id, condition=e.condition)
        for e in spec.edges
    ]

    return SwimlaneJsonSpec(
        title         = spec.title,
        part_no       = spec.part_no,
        total_parts   = spec.total_parts,
        page_w_in     = page_w,
        page_h_in     = page_h,
        title_bar     = title_bar,
        phase_headers = phase_headers,
        lanes         = lanes,
        nodes         = nodes,
        edges         = edges,
    )
