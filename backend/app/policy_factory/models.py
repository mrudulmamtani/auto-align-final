"""
Core data models for every artifact produced by the Policy Factory pipeline.
Every normative requirement MUST carry at least one citation chunk_id —
this is enforced at the Pydantic layer and re-checked deterministically in validation.
"""
from __future__ import annotations
from pydantic import BaseModel, Field, model_validator
from typing import Literal, Optional
from datetime import datetime, timezone


class EntityProfile(BaseModel):
    org_name: str
    sector: str                        # e.g. "Financial Services"
    hosting_model: str                 # "cloud" | "on-premise" | "hybrid"
    soc_model: str                     # "internal" | "managed" | "none"
    data_classification: list[str]     # ["confidential", "restricted", "public"]
    ot_presence: bool = False
    critical_systems: list[str] = []
    jurisdiction: str = "UAE"


class DocumentSpec(BaseModel):
    doc_type: Literal["policy", "standard", "procedure"]
    doc_id: Optional[str] = None       # e.g. "POL-01", "STD-02", "PRC-03" — drives golden routing
    topic: str                         # e.g. "Access Control", "Incident Response"
    scope: str
    target_audience: str
    required_sections: list[str] = []
    exclusions: list[str] = []
    version: str = "1.0"
    existing_document: Optional[str] = None   # raw text of existing artifact for gap analysis


# ── Control Store ─────────────────────────────────────────────────────────────

class ControlChunk(BaseModel):
    chunk_id: str                      # stable UUID
    framework: str                     # "NIST_80053" | "UAE_IA" | "NCA_ECC" | "NCA_CSCC" ...
    control_id: str                    # e.g. "AC-02", "T5.2.2", "1-1-1"
    title: str
    statement: str                     # exact source text
    domain: str
    subdomain: str = ""
    uae_ia_id: Optional[str] = None    # mapped UAE IA ID (on NIST controls)
    nca_id: Optional[str] = None       # mapped NCA control label (on NIST chunks) or own label (NCA chunks)
    content_hash: str = ""
    source_uri: str = ""
    framework_version: str = "SP800-53r5"


class RetrievalPacket(BaseModel):
    query_topic: str
    retrieved_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    chunks: list[ControlChunk]

    @property
    def chunk_id_set(self) -> set[str]:
        return {c.chunk_id for c in self.chunks}


# ── Control Bundles (Enrichment output) ───────────────────────────────────────

class ControlBundle(BaseModel):
    chunk_id: str
    control_id: str
    title: str
    statement: str
    domain: str
    framework: str = "NIST_80053"      # actual framework of this chunk
    uae_ia_id: Optional[str] = None
    nca_id: Optional[str] = None       # NCA control label for this bundle
    implementation_notes: list[str] = Field(default_factory=list)   # agent-generated, max 3 bullets
    evidence_examples: list[str] = Field(default_factory=list)     # what artifacts satisfy this control
    rerank_score: Optional[float] = None   # cross-encoder score (higher = more relevant)


# ── Draft artifacts — schema-locked for Structured Outputs ────────────────────

class Requirement(BaseModel):
    req_id: str                        # stable, e.g. "REQ-001"
    text: str                          # normative statement
    is_normative: bool                 # True if contains SHALL/MUST/REQUIRED/WILL
    citations: list[str]               # chunk_ids from RetrievalPacket
    mapped_control_ids: list[str]      # control_ids derived from cited chunks

    @model_validator(mode="after")
    def normative_must_have_citation(self) -> "Requirement":
        if self.is_normative and not self.citations:
            raise ValueError(
                f"Requirement {self.req_id} is normative (SHALL/MUST) but has no citations."
            )
        return self


class DraftSection(BaseModel):
    section_id: str
    title: str
    purpose: str                       # one sentence explaining this section
    requirements: list[Requirement]


class DraftOutput(BaseModel):
    doc_id: str
    doc_type: str
    topic: str
    org_name: str
    version: str
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    sections: list[DraftSection]

    @property
    def all_requirements(self) -> list[Requirement]:
        return [r for s in self.sections for r in s.requirements]


# ── Validation ────────────────────────────────────────────────────────────────

class ValidationFinding(BaseModel):
    finding_id: str
    severity: Literal["FAIL", "WARN"]
    check: str                         # "CITATION_COMPLETENESS" | "CONTROL_COVERAGE" | "HALLUCINATION"
    message: str
    affected_req_id: Optional[str] = None


class ValidationReport(BaseModel):
    passed: bool
    citation_coverage_pct: float       # 1.0 = 100% — hard gate
    control_coverage_pct: float
    uncovered_chunk_ids: list[str]
    findings: list[ValidationFinding]


# ── Planner output ────────────────────────────────────────────────────────────

class SectionBlueprint(BaseModel):
    section_id: str
    title: str
    purpose: str
    control_domains: list[str]         # UAE IA domains / NIST families to retrieve
    retrieval_queries: list[str]       # queries for the retriever


class DocumentPlan(BaseModel):
    doc_type: str
    topic: str
    org_name: str
    executive_summary: str
    sections: list[SectionBlueprint]
    required_control_ids: list[str]    # specific controls that MUST be covered


# ── Golden Policy Baseline models (POL-* documents) ───────────────────────────

GOLDEN_TOC = [
    "Objectives",
    "Scope and Applicability",
    "Policy Elements",
    "Roles and Responsibilities",
    "Policy Compliance",
    "Exceptions",
]

SUBPROGRAM_CATALOG = [
    ("2-1",  "Cybersecurity Strategy"),
    ("2-2",  "Cybersecurity Roles and Responsibilities"),
    ("2-3",  "Cybersecurity Risk Management"),
    ("2-4",  "Cybersecurity in IT Projects"),
    ("2-5",  "Regulatory Compliance"),
    ("2-6",  "Cybersecurity Audit"),
    ("2-7",  "Cybersecurity in Human Resources"),
    ("2-8",  "Cybersecurity Awareness and Training"),
    ("2-9",  "Asset Management"),
    ("2-10", "Acceptable Use"),
    ("2-11", "Identity and Access Management"),
    ("2-12", "System and Application Protection"),
    ("2-13", "Email Security"),
    ("2-14", "Network Security"),
    ("2-15", "Mobile Device Security"),
    ("2-16", "Data Protection and Privacy"),
    ("2-17", "Cryptography"),
    ("2-18", "Backup and Recovery"),
    ("2-19", "Vulnerability Management"),
    ("2-20", "Penetration Testing"),
    ("2-21", "Logs and Monitoring"),
    ("2-22", "Cybersecurity Incident Management"),
    ("2-23", "Physical and Environmental Security"),
    ("2-24", "Application Security"),
    ("2-25", "Business Continuity and Resilience"),
    ("2-26", "Third-Party and Supplier Security"),
    ("2-27", "Cloud Security"),
    ("2-28", "Social Media Security"),
    ("2-29", "Patch Management"),
    ("2-30", "Secure Configuration and Hardening"),
    ("2-31", "Malware Protection"),
    ("2-32", "Remote Access Security"),
    ("2-33", "Server Security"),
    ("2-34", "Database Security"),
]


class TraceEntry(BaseModel):
    framework: str       # "UAE_IA" | "NIST_80053"
    control_id: str      # e.g. "T5.2.2" or "AC-02"
    source_ref: str      # chunk_id from RetrievalPacket


class PolicyElement(BaseModel):
    element_no: str          # "1", "2", "3", ...
    statement_en: str        # Normative SHALL statement
    trace: list[TraceEntry]  # Non-empty for every shall statement


class Subprogram(BaseModel):
    sub_no: str              # "2-1" ... "2-34"
    name_en: str
    objective_en: str        # 1–2 sentence objective
    references: list[str]    # optional doc IDs e.g. ["STD-26", "PRC-33"]


class RolesResponsibilities(BaseModel):
    authority_owner_delegates: list[str]
    legal: list[str]
    internal_audit: list[str]
    HR: list[str]
    cybersecurity: list[str]
    other_departments: list[str]
    all_staff: list[str]


class PolicyDraftOutput(BaseModel):
    doc_id: str                        # e.g. "POL-01"
    document_type: str = "policy"
    title_en: str
    version: str
    effective_date: str
    owner: str
    classification: str
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    objectives_en: str
    scope_applicability_en: str
    policy_elements: list[PolicyElement]
    policy_subprograms: list[Subprogram]   # 2-1 .. 2-34
    roles_responsibilities: RolesResponsibilities
    compliance_clauses: list[str]          # exactly 3
    exceptions_en: str
    closing_note_en: str


class PolicyQAFinding(BaseModel):
    check: str
    severity: Literal["FAIL", "WARN"]
    message: str


class PolicyQAReport(BaseModel):
    passed: bool
    findings: list[PolicyQAFinding]
    shall_count: int
    traced_count: int


# ── Golden Standard Baseline models (STD-* documents) ─────────────────────────

STANDARD_TOC = [
    "Objectives",
    "Scope and Applicability",
    "Standards Requirements",
    "Roles and Responsibilities",
    "Update and Review",
    "Compliance with the Standard",
]

EXCEPTIONS_CLAUSE = (
    "Any exception to this standard must be approved in writing by the Cybersecurity "
    "Department according to the approved exception and risk acceptance process."
)


class StandardDefinition(BaseModel):
    term_en: str
    description_en: str


class StandardRequirement(BaseModel):
    req_id: str             # e.g. "1.1", "1.2"
    statement_en: str       # MUST contain "shall" for normative requirements
    placeholders: list[str] = []
    trace: list[TraceEntry] # non-empty for any "shall" requirement


class StandardDomain(BaseModel):
    domain_number: int
    title_en: str
    objective_en: str
    potential_risks_en: str
    requirements: list[StandardRequirement]


class StandardRoleItem(BaseModel):
    item_no: str     # "1-", "2-", "3-"
    text_en: str


class StandardDraftOutput(BaseModel):
    doc_id: str                  # e.g. "STD-01"
    document_type: str = "standard"
    title_en: str
    version: str
    effective_date: str
    owner: str
    classification: str
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    definitions: list[StandardDefinition]           # min 5
    objectives_en: str                              # CIA + regulatory/ECC
    scope_en: str                                   # applicability + exceptions clause
    domains: list[StandardDomain]                   # min 3
    roles_responsibilities: list[StandardRoleItem]  # exactly 3 (1-, 2-, 3-)
    review_update_en: str                           # 3 triggers
    compliance_en: list[str]                        # exactly 3 clauses
    closing_note_en: str


class StandardQAFinding(BaseModel):
    check: str
    severity: Literal["FAIL", "WARN"]
    message: str


class StandardQAReport(BaseModel):
    passed: bool
    findings: list[StandardQAFinding]
    shall_count: int
    traced_count: int


# ── Golden Procedure Baseline models (PRC-* documents) ────────────────────────

# 15-section TOC per procedure.json schema (authoritative)
PROCEDURE_TOC = [
    "Definitions and Abbreviations",
    "Procedure Objective",
    "Scope and Applicability",
    "Roles and Responsibilities",
    "Procedure Overview",
    "Triggers, Prerequisites, Inputs and Tools",
    "Detailed Procedure Steps",
    "Decision Points, Exceptions and Escalations",
    "Outputs, Records, Evidence and Forms",
    "Time Controls, Service Levels and Control Checkpoints",
    "Related Documents",
    "Effective Date",
    "Procedure Review",
    "Review and Approval",
    "Version Control",
]


# ── New procedure section models (15-section structure) ───────────────────────

class ProcedureDefinition(BaseModel):
    term: str
    definition: str


class ProcedureTrigger(BaseModel):
    trigger: str
    description: str


class ProcedureInputForm(BaseModel):
    form_name: str
    purpose: str
    reference: str


class ProcedureOutputRecord(BaseModel):
    output: str
    recipient_or_destination: str


class ProcedureEvidenceRecord(BaseModel):
    record_or_evidence: str
    owner: str
    retention: str
    storage_location: str


class ProcedureTimeControl(BaseModel):
    activity_or_step: str
    service_level: str
    responsible_role: str
    escalation_if_breached: str


class ProcedureRoleItem(BaseModel):
    role_title: str               # e.g. "Security Administrator"
    responsibilities: list[str]   # min 1 responsibility per role


class ProcedureStep(BaseModel):
    step_no: str             # "1", "1.1", "2" etc.
    phase: str               # "Preparation" | "Implementation" | "Verification"
    actor: str               # role performing this step
    action: str              # imperative instruction; may include CLI/code context
    expected_output: str     # observable result confirming step completion
    code_block: str          # CLI command / config snippet; empty string if none
    citations: list[str]     # chunk_ids from RetrievalPacket that ground this step


class ProcedurePhase(BaseModel):
    phase_name: str          # "Preparation" | "Implementation" | "Verification"
    phase_intro: str = ""    # introductory paragraph describing this phase's purpose and context
    steps: list[ProcedureStep]


class ProcedureVerificationCheck(BaseModel):
    check_id: str            # "V1", "V2", …
    description: str
    method: str              # "manual" | "automated" | "audit review"
    expected_result: str
    evidence_artifact: str   # artifact that proves this check passed


class ProcedureDraftOutput(BaseModel):
    doc_id: str              # e.g. "PRC-01"
    document_type: str = "procedure"
    title_en: str
    version: str
    effective_date: str
    owner: str
    classification: str
    parent_policy_id: str    # e.g. "POL-01"
    parent_standard_id: str  # e.g. "STD-01"
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # ── Section 1: Definitions and Abbreviations ──────────────────────────────
    definitions: list[ProcedureDefinition] = []             # min 5 operational terms

    # ── Section 2: Procedure Objective ────────────────────────────────────────
    objective_en: str

    # ── Section 3: Scope and Applicability ────────────────────────────────────
    scope_en: str

    # ── Section 4: Roles and Responsibilities ─────────────────────────────────
    roles_responsibilities: list[ProcedureRoleItem]         # min 3

    # ── Section 5: Procedure Overview ─────────────────────────────────────────
    procedure_overview: str = ""                            # high-level narrative

    # ── Section 6: Triggers, Prerequisites, Inputs and Tools ──────────────────
    triggers: list[ProcedureTrigger] = []                   # events that initiate procedure
    prerequisites: list[str]                                # min 3
    tools_required: list[str]                               # min 1 with vendor/version
    input_forms: list[ProcedureInputForm] = []              # forms/templates used

    # ── Section 7: Detailed Procedure Steps ───────────────────────────────────
    phases: list[ProcedurePhase]                            # min 4 phases, 15+ steps total

    # ── Section 8: Decision Points, Exceptions and Escalations ────────────────
    decision_points_and_escalations: str = ""               # branching logic + escalation matrix
    exception_handling_en: str                              # exception process (kept for compat)

    # ── Section 9: Outputs, Records, Evidence and Forms ───────────────────────
    outputs_records: list[ProcedureOutputRecord] = []       # outputs produced
    evidence_records: list[ProcedureEvidenceRecord] = []    # evidence for audit
    verification_checks: list[ProcedureVerificationCheck]  # min 3
    evidence_collection: list[str]                          # min 2 artifacts (legacy compat)

    # ── Section 10: Time Controls, Service Levels and Control Checkpoints ─────
    time_controls: list[ProcedureTimeControl] = []          # SLAs per step/phase

    # ── Section 11: Related Documents ─────────────────────────────────────────
    related_documents: list[str] = []                       # parent policy, standard, forms

    # ── Section 13: Procedure Review ──────────────────────────────────────────
    procedure_review: str = ""                              # cadence + triggers

    # ── Section 14: Review and Approval ───────────────────────────────────────
    review_and_approval: str = ""                           # approval chain

    # ── Diagrams (Appendix) ───────────────────────────────────────────────────
    swimlane_diagram: str    # Mermaid flowchart LR (roles as subgraphs)
    flowchart_diagram: str   # Mermaid flowchart TD (decision logic)


class ProcedureQAFinding(BaseModel):
    check: str
    severity: Literal["FAIL", "WARN"]
    message: str


class ProcedureQAReport(BaseModel):
    passed: bool
    findings: list[ProcedureQAFinding]
    step_count: int
    cited_step_count: int
    diagram_count: int


# ── Augmented Control Context (Gap Analysis Agent output) ─────────────────────

class AugmentedControlContext(BaseModel):
    control_id: str
    chunk_id: str
    enriched_description: str
    implementation_guidance: list[str]   # concrete actionable steps
    validation_guidance: list[str]       # how to verify the control is implemented
    gap_detected: bool
    gap_type: str      # "implementation" | "configuration" | "validation" | "none"
    nist_supplement: str   # NIST guidance used to fill the gap; empty if none
