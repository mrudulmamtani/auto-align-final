"""
StandardSpec — the Pydantic schema emitted by the Planner for any STD-* document.
Validates the planner's intent before drafting begins.
"""
from pydantic import BaseModel
from ..models import STANDARD_TOC


class StandardSpec(BaseModel):
    document_id: str                  # e.g. "STD-01"
    document_type: str = "standard"
    title_en: str
    version: str = "1.0"
    effective_date: str = "TBD"
    owner: str = "Chief Information Security Officer"
    classification: str = "Internal"

    toc_en: list[str] = STANDARD_TOC  # must be exactly STANDARD_TOC

    retrieval_queries: list[str]      # queries to feed the control store
    required_control_ids: list[str] = []
