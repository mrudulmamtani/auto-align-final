"""
Procedure Parser — converts ProcedureDraftOutput into a canonical DiagramSpec.

Deterministic: no LLM involvement. Layout is derived entirely from the
structured procedure data (phases, roles, steps).

Visual design system constraints enforced here:
  - max 7 words per node label  (spec §4 / §5)
  - max 10 nodes per diagram    (spec §11)
  - max 3 phases per diagram    (split if exceeded)
  - max 3 decision diamonds     (keeps diagrams readable)
  - max 6 role swimlanes        (spec §2)

Pipeline position:
    ProcedureDraftOutput → ProcedureParser → DiagramSpec
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from collections import defaultdict
from typing import Literal

from ..models import ProcedureDraftOutput, ProcedurePhase, ProcedureStep


# ── Complexity limits ──────────────────────────────────────────────────────────
MAX_NODES     = 10   # max nodes per diagram (spec §11: 7–10)
MAX_DECISIONS = 3    # max decision diamonds per diagram
MAX_LANES     = 6    # max role swimlanes
MAX_PHASES    = 3    # max phases before diagram is split
MAX_WORDS     = 7    # max words per node label (spec §5)

# ── Decision keyword detection (deterministic, no LLM) ────────────────────────
_DECISION_KEYWORDS = frozenset({
    "verify", "check", "validate", "test", "assess", "review",
    "approve", "approved", "pass", "fail", "confirm", "determine",
    "evaluate", "inspect", "detect", "compare", "audit", "scan",
})

NodeType = Literal["start", "process", "decision", "end"]

_STRIP_PARENS  = re.compile(r'\([^)]*\)')   # remove "(…)" asides
_STRIP_PUNCT   = re.compile(r"[^\w\s\-']")  # keep hyphens and apostrophes


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class DiagramNode:
    node_id:   str         # "N_{phase_idx}_{role_idx}_{slot_idx}"
    step_no:   str         # original step number e.g. "1", "2.3"
    phase:     str         # phase name
    role:      str         # role performing the step
    title:     str         # ≤7 words, verb-first, no punctuation (spec §5)
    node_type: NodeType    # "start" | "process" | "decision" | "end"
    phase_idx: int         # column index (0-based)
    role_idx:  int         # row index (0-based)
    slot_idx:  int         # vertical stack position within cell (0-based)


@dataclass
class DiagramEdge:
    from_id:   str
    to_id:     str
    condition: str = ""    # "" | "Yes" | "No"


@dataclass
class DiagramSpec:
    title:       str
    phases:      list[str]          # ordered phase names
    roles:       list[str]          # ordered role names
    nodes:       list[DiagramNode]
    edges:       list[DiagramEdge]
    part_no:     int = 1
    total_parts: int = 1


# ── Helpers ────────────────────────────────────────────────────────────────────

def _is_decision(action: str) -> bool:
    words = set(action.lower().split())
    return bool(words & _DECISION_KEYWORDS)


def _compress_label(s: str) -> str:
    """
    Compress an action string to max MAX_WORDS words for a diagram node label.

    Rules (all deterministic):
      1. Strip trailing punctuation (.,;:))
      2. Remove parenthetical asides "(…)" that add noise
      3. Remove mid-string punctuation, keeping hyphens and apostrophes
      4. Take first MAX_WORDS words — preserves verb-first phrasing naturally,
         since procedure steps are written "Verb Object …" (e.g. "Configure firewall
         rules for inbound traffic" → "Configure firewall rules for inbound traffic")

    spec §5: max 7 words per node, verb-first, no punctuation-heavy text.
    """
    s = s.strip().rstrip(".,;:)")
    s = _STRIP_PARENS.sub("", s).strip()
    s = _STRIP_PUNCT.sub(" ", s)
    words = s.split()
    if not words:
        return "Process Step"
    return " ".join(words[:MAX_WORDS])


def _match_role_idx(actor: str, roles: list[str]) -> int:
    """Best-match actor string to role index by shared significant words."""
    al = actor.lower()
    best, best_score = 0, 0
    for i, role in enumerate(roles):
        score = len(
            {w for w in al.split() if len(w) > 3}
            & {w for w in role.lower().split() if len(w) > 3}
        )
        if score > best_score:
            best, best_score = i, score
    return best


# ── Parser ─────────────────────────────────────────────────────────────────────

class ProcedureParser:
    """
    Converts ProcedureDraftOutput → list[DiagramSpec].

    Usually returns one spec. Returns multiple specs when the phase count
    exceeds MAX_PHASES (auto-split into groups of MAX_PHASES each).
    Each spec is capped at MAX_NODES nodes.
    """

    def parse(self, draft: ProcedureDraftOutput) -> list[DiagramSpec]:
        phases = draft.phases
        roles  = [r.role_title for r in draft.roles_responsibilities]

        if len(roles) > MAX_LANES:
            print(f"[ProcedureParser] Clamping roles {len(roles)} → {MAX_LANES}.")
            roles = roles[:MAX_LANES]

        if len(phases) > MAX_PHASES:
            return self._split(draft.title_en, phases, roles)

        return [self._build(draft.title_en, phases, roles, 1, 1)]

    # ── Internal builders ─────────────────────────────────────────────────────

    def _split(
        self,
        title: str,
        phases: list[ProcedurePhase],
        roles: list[str],
    ) -> list[DiagramSpec]:
        chunks = [phases[i: i + MAX_PHASES] for i in range(0, len(phases), MAX_PHASES)]
        total  = len(chunks)
        return [
            self._build(title, chunk, roles, i + 1, total)
            for i, chunk in enumerate(chunks)
        ]

    def _build(
        self,
        title: str,
        phases: list[ProcedurePhase],
        roles: list[str],
        part_no: int,
        total_parts: int,
    ) -> DiagramSpec:
        nodes:        list[DiagramNode] = []
        step_to_node: dict[str, str]    = {}
        slot_ctr:     dict              = defaultdict(int)

        all_steps: list[tuple[int, ProcedureStep]] = []
        for pi, ph in enumerate(phases):
            for st in ph.steps:
                all_steps.append((pi, st))

        total_steps    = len(all_steps)
        decision_count = 0

        for seq, (pi, st) in enumerate(all_steps):
            ri  = _match_role_idx(st.actor, roles)
            key = (pi, ri)
            slot = slot_ctr[key]
            slot_ctr[key] += 1

            # Deterministic node-type assignment
            if seq == 0:
                ntype: NodeType = "start"
            elif seq == total_steps - 1:
                ntype = "end"
            elif decision_count < MAX_DECISIONS and _is_decision(st.action):
                ntype = "decision"
                decision_count += 1
            else:
                ntype = "process"

            node_id = f"N_{pi}_{ri}_{slot}"
            node = DiagramNode(
                node_id=node_id,
                step_no=st.step_no,
                phase=phases[pi].phase_name,
                role=roles[ri],
                title=_compress_label(st.action),   # ≤7 words (spec §5)
                node_type=ntype,
                phase_idx=pi,
                role_idx=ri,
                slot_idx=slot,
            )
            nodes.append(node)
            step_to_node[st.step_no] = node_id

        # Node cap (spec §11: max 7–10 per diagram)
        if len(nodes) > MAX_NODES:
            print(
                f"[ProcedureParser] Node cap {MAX_NODES} hit "
                f"({len(nodes)} nodes). Truncating."
            )
            kept         = {n.node_id for n in nodes[:MAX_NODES]}
            nodes        = nodes[:MAX_NODES]
            step_to_node = {k: v for k, v in step_to_node.items() if v in kept}

        # ── Edge building ──────────────────────────────────────────────────────
        edges: list[DiagramEdge] = []
        seen:  set[tuple[str, str]] = set()

        def _add(a: str | None, b: str | None, cond: str = "") -> None:
            if a and b and a != b and (a, b) not in seen:
                seen.add((a, b))
                edges.append(DiagramEdge(from_id=a, to_id=b, condition=cond))

        # Sequential within each phase
        for ph in phases:
            prev: str | None = None
            for st in ph.steps:
                nid = step_to_node.get(st.step_no)
                if nid:
                    if prev:
                        _add(prev, nid)
                    prev = nid

        # Cross-phase: last step of phase N → first step of phase N+1
        phase_last:  list[str | None] = []
        phase_first: list[str | None] = []
        for ph in phases:
            valid = [s for s in ph.steps if step_to_node.get(s.step_no)]
            phase_last.append(step_to_node[valid[-1].step_no] if valid else None)
            phase_first.append(step_to_node[valid[0].step_no]  if valid else None)

        for pi in range(len(phases) - 1):
            _add(phase_last[pi], phase_first[pi + 1])

        spec_title = (
            f"{title} (Part {part_no} of {total_parts})"
            if total_parts > 1 else title
        )
        return DiagramSpec(
            title=spec_title,
            phases=[ph.phase_name for ph in phases],
            roles=roles,
            nodes=nodes,
            edges=edges,
            part_no=part_no,
            total_parts=total_parts,
        )
