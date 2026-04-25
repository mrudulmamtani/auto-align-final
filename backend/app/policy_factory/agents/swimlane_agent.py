"""
Swimlane Agent — deterministic swimlane diagram generator (v2).

Architecture change (v2):
  OLD: LLM (gpt-5.4) decides rows/columns/nodes/edges → non-deterministic,
       fragile, expensive, ~4s latency per call.

  NEW: Deterministic pipeline — no LLM, no API calls, no layout drift.
       ProcedureDraftOutput → ProcedureParser → LayoutEngine → MatplotlibRenderer → PNG

Layout decisions are computed entirely from the procedure's structured data:
  - rows    = roles from draft.roles_responsibilities (in declaration order)
  - columns = phases from draft.phases (in declaration order)
  - nodes   = one node per step, placed at (phase_idx, role_idx) cell
  - edges   = sequential within each phase + cross-phase connectors

Complexity limits enforced by ProcedureParser:
  MAX_NODES = 10 | MAX_DECISIONS = 3 | MAX_LANES = 6 | MAX_PHASES = 3
  (auto-split into multiple diagram parts when exceeded)

The SwimlaneSpec / SwimlaneAgent interface is preserved for backward
compatibility with renderer.py. Internally it delegates to DiagramGenerator.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..models import ProcedureDraftOutput
from .diagram_generator import DiagramGenerator


# ── Legacy spec types (kept for renderer.py backward compatibility) ────────────

@dataclass
class SwimlaneRow:
    id: str
    label: str


@dataclass
class SwimlaneColumn:
    id: str
    label: str


@dataclass
class SwimlaneNode:
    id: str
    label: str
    shape: str       # "start" | "process" | "decision" | "end"
    row_id: str
    col_id: str


@dataclass
class SwimlaneEdge:
    from_id: str
    to_id: str
    label: str = ""


@dataclass
class SwimlaneSpec:
    title: str
    rows: list
    columns: list
    nodes: list
    edges: list


# ── Agent ──────────────────────────────────────────────────────────────────────

class SwimlaneAgent:
    """
    Deterministic swimlane layout engine.

    .generate() returns None — the swimlane PNG is now generated directly
    by DiagramGenerator. Callers should use DiagramGenerator.generate_swimlane()
    instead. This class is retained only so that renderer.py import paths
    remain valid during the transition.
    """

    def __init__(self) -> None:
        self._generator = DiagramGenerator()

    def generate(self, draft: ProcedureDraftOutput) -> "SwimlaneSpec | None":
        """
        Deprecated: use DiagramGenerator.generate_swimlane() directly.

        Returns None so that renderer.py falls through to the DiagramGenerator
        path in _add_swimlane_block().
        """
        return None

    def generate_png_list(self, draft: ProcedureDraftOutput) -> list[bytes]:
        """
        Generate one or more swimlane PNG bytes objects for the procedure.
        Returns empty list on failure.
        """
        try:
            return self._generator.generate_swimlane(draft)
        except Exception as exc:
            print(f"[SwimlaneAgent] DiagramGenerator failed: {exc}")
            return []
