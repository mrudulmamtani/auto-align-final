"""
Workflow models — internal partial-output containers for the sub-agentic pipeline.
These are never exposed to the pipeline caller; the supervisor assembles them into
the final typed output models (PolicyDraftOutput / StandardDraftOutput / ProcedureDraftOutput).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Any


@dataclass
class SectionOutput:
    """Generic per-section agent result."""
    section_id: str          # e.g. "front_matter" | "phase_0" | "evidence"
    status: Literal["ok", "fail", "skipped"]
    data: dict[str, Any]     # partial fields matching the parent output model
    qa_issues: list[str] = field(default_factory=list)
    attempt: int = 1


@dataclass
class PhaseResearch:
    """Per-phase control bundles (pre-filtered and reranked)."""
    phase_index: int
    phase_name: str
    bundles: list           # list[ControlBundle]
    augmented: list         # list[AugmentedControlContext]


@dataclass
class WorkflowResearch:
    """Complete research package produced before any drafting begins."""
    full_bundles: list                    # all retrieved + reranked ControlBundles
    front_matter_bundles: list            # §1-6 relevant bundles
    phase_research: list[PhaseResearch]   # per-phase bundles
    evidence_bundles: list                # §8-10 relevant bundles
    augmented_contexts: list              # gap-analysis contexts (if existing_document provided)
