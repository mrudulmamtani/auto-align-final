"""
New JSON schemas for the AutoAlign Template Conversion Platform.

Extends the existing artifact JSONs with forensic location data
(page numbers, paragraph indices) and template conversion metadata.
Control numbers are the primary mapping key throughout.
"""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime, timezone


class ControlLocation(BaseModel):
    """
    Forensic location of a single control citation within a source DOCX.
    Keyed by control_id (e.g. '1-3-2') — the authoritative identifier.
    """
    # Control identity
    control_id: str                    # e.g. "1-3-2"
    framework: str                     # e.g. "NCA_ECC"
    nca_id: Optional[str] = None       # NCA label (same as control_id for NCA chunks)
    chunk_id: Optional[str] = None     # source chunk UUID from bundles JSON
    rerank_score: Optional[float] = None

    # Document context
    element_ref: str                   # "Element 1" | "1.1" | "Domain 3 req 1.2"
    section: str                       # e.g. "Policy Elements"
    section_number: str                # e.g. "3"
    domain_title: Optional[str] = None # for standards

    # Forensic position in SOURCE docx
    page_number: Optional[int] = None
    paragraph_index: Optional[int] = None
    char_offset_start: Optional[int] = None
    char_offset_end: Optional[int] = None

    # Position AFTER template conversion (filled by converter / Office.js)
    converted_page_number: Optional[int] = None
    converted_paragraph_index: Optional[int] = None

    # Extraction metadata
    extraction_method: Literal["win32com", "heuristic", "officejs", "manual"] = "heuristic"
    extraction_confidence: float = 0.75  # 0.0–1.0


class SectionLocation(BaseModel):
    """Location of a major section heading in the DOCX."""
    section_number: str
    title: str
    page_number: Optional[int] = None
    paragraph_index: Optional[int] = None
    heading_level: int = 1

    # After conversion
    converted_page_number: Optional[int] = None


class TemplateConfig(BaseModel):
    """Organization-specific template configuration."""
    org_name: str
    org_id: str                        # URL-safe slug
    template_id: str                   # unique ID for this template version

    # Branding
    logo_filename: Optional[str] = None
    primary_color: str = "#1F497D"
    secondary_color: str = "#4472C4"
    accent_color: str = "#22C55E"

    # Typography
    font_family: str = "Calibri"
    heading_font: str = "Calibri"

    # Header / Footer
    header_left: str = ""
    header_center: str = ""
    header_right: str = "CONFIDENTIAL"
    footer_left: str = ""
    footer_center: str = "Page {page} of {total}"
    footer_right: str = ""

    # Page setup
    page_size: Literal["A4", "Letter"] = "A4"
    cover_bg_color: Optional[str] = None

    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ForensicDocumentMap(BaseModel):
    """
    Primary output of the forensic extraction pass.
    Replaces *_1_bundles.json with richer location + template data.
    Control numbers (control_id) are the mapping keys throughout.
    """
    # Identity
    doc_id: str                        # "POL-01", "STD-15", ...
    document_type: Literal["policy", "standard", "procedure"]
    title: str
    version: str
    org_name: str

    # Source artifact paths
    source_result_json: str
    source_bundles_json: str
    source_draft_json: str
    source_docx: str
    source_traceability_docx: str

    # QA metadata (from result JSON)
    qa_passed: bool
    shall_count: int
    traced_count: int

    # Forensic extraction metadata
    forensic_extracted_at: Optional[str] = None
    forensic_method: Literal["win32com", "heuristic", "officejs", "manual"] = "heuristic"
    total_paragraphs: Optional[int] = None
    estimated_pages: Optional[int] = None

    # Location maps (control_id is the key via control_locations list)
    section_locations: list[SectionLocation] = []
    control_locations: list[ControlLocation] = []

    # Template conversion output
    template_config: Optional[TemplateConfig] = None
    converted_docx: Optional[str] = None
    converted_at: Optional[str] = None

    map_version: str = "2.0"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def get_control(self, control_id: str) -> Optional[ControlLocation]:
        """Lookup a control location by control_id."""
        for c in self.control_locations:
            if c.control_id == control_id:
                return c
        return None

    def control_ids(self) -> list[str]:
        return [c.control_id for c in self.control_locations]


class BatchForensicIndex(BaseModel):
    """Index of all forensic maps for all generated documents."""
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    total_documents: int = 0
    total_controls_mapped: int = 0
    documents: list[dict] = []   # lightweight summaries
