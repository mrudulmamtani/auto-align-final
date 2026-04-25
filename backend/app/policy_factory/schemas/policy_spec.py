"""
PolicySpec — the schema the Planner MUST emit for any POL-* document.
This is the structural contract between the Planner and the Drafter for golden-baseline policies.
The Drafter uses this to enforce exact TOC ordering, required elements, and subprogram catalog.
"""
from pydantic import BaseModel
from ..models import GOLDEN_TOC, SUBPROGRAM_CATALOG


class PolicyRetrievalPlan(BaseModel):
    """Lightweight plan for policy retrieval — Planner outputs this instead of DocumentPlan."""
    doc_id: str                      # "POL-01", "POL-06", etc.
    doc_type: str = "policy"
    title_en: str
    org_name: str
    topic: str
    toc: list[str] = GOLDEN_TOC     # Fixed — must be exactly GOLDEN_TOC
    retrieval_queries: list[str]     # Queries to retrieve governance / program controls
    required_control_ids: list[str]  # Specific NCA / UAE IA control IDs that MUST appear
    executive_summary: str           # Brief description of the policy's purpose
