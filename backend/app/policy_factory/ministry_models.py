"""
Ministry Document Models — Arabic-primary Pydantic v2 models for all three
document tiers: Policy (السياسة), Standard (المعيار), Procedure (الإجراء).

Each model maps to the exact section_blueprints defined in:
  backend/policy.json     — 10-section policy schema
  backend/standard.json   — 8-section standard schema
  backend/procedure.json  — 15-section procedure schema

All text fields labelled _ar store Arabic prose.
Fields labelled _en store optional English technical glosses only.
"""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone


# ── Shared metadata ────────────────────────────────────────────────────────────

class MinistryMeta(BaseModel):
    doc_id: str                        # e.g. "POL-01", "STD-02", "PRC-03"
    doc_type: str                      # "policy" | "standard" | "procedure"
    title_ar: str
    title_en: str = ""
    version: str = "1.0"
    issue_date: str = ""
    classification: str = "سري - للاستخدام الداخلي"
    owner: str = "إدارة الأمن السيبراني"
    reference_number: str = ""
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── Definition table row ───────────────────────────────────────────────────────

class DefinitionEntry(BaseModel):
    term_ar: str
    term_en: str = ""
    definition_ar: str


# ── Approval block ─────────────────────────────────────────────────────────────

class ApprovalStage(BaseModel):
    stage_ar: str           # e.g. "أعدّه", "راجعه", "وافق عليه"
    role_ar: str
    name_ar: str = "[الاسم]"
    date_ar: str = "[التاريخ]"


# ── Version control row ────────────────────────────────────────────────────────

class VersionRow(BaseModel):
    version: str = "1.0"
    update_type_ar: str = "إصدار أوّلي"
    summary_ar: str = "الإصدار الأوّلي من الوثيقة"
    updated_by_ar: str = "إدارة الأمن السيبراني"
    approval_date: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# POLICY DOCUMENT  (6-8 pages)  — the WHY
# schema: backend/policy.json  → section_blueprints
# ══════════════════════════════════════════════════════════════════════════════

class PolicyClause(BaseModel):
    """One governing requirement in Section 4 (policy_statement)."""
    clause_no: int
    text_ar: str                       # mandatory "يجب" / "يحظر" statement
    sub_bullets_ar: list[str] = []     # optional sub-requirements


class PolicyRelatedDoc(BaseModel):
    title_ar: str
    title_en: str = ""
    ref_type: str = ""                 # "وطني" | "إجراء" | "معيار" | etc.


class MinistryPolicyDraft(BaseModel):
    meta: MinistryMeta

    # Section 1 — definitions
    definitions: list[DefinitionEntry]                 # 4-10 entries

    # Section 2 — objective (1-2 paragraphs)
    objective_ar: str

    # Section 3 — scope (1-2 paragraphs)
    scope_ar: str

    # Section 4 — policy statement (dominant, 7-25 clauses)
    policy_clauses: list[PolicyClause]

    # Section 5 — roles and responsibilities (brief)
    roles_ar: str

    # Section 6 — related documents
    related_docs: list[PolicyRelatedDoc]

    # Section 7 — effective date
    effective_date_ar: str

    # Section 8 — policy review (1-2 paragraphs)
    review_ar: str

    # Section 9 — review and approval
    approval_stages: list[ApprovalStage]

    # Section 10 — version control
    version_rows: list[VersionRow]

    # Optional — control mapping (clause_no -> list of framework refs)
    control_mapping: dict[str, list[str]] = {}

    # Dependency context digest (not rendered, used for downstream docs)
    dependency_summary: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# STANDARD DOCUMENT  (14-20 pages)  — the WHAT & WHO
# schema: backend/standard.json  → section_blueprints
# ══════════════════════════════════════════════════════════════════════════════

class StandardClause(BaseModel):
    """One operative clause in a domain cluster (4.x.y numbering)."""
    clause_id: str                     # e.g. "4.1.1", "4.2.3"
    text_ar: str                       # normative statement
    guidance_ar: str = ""              # optional guidance note
    is_mandatory: bool = True          # True = "يجب", False = "ينبغي"


class StandardDomainCluster(BaseModel):
    """One sub-section of Section 4 (4.1, 4.2, 4.3, 4.4)."""
    cluster_id: str                    # "4.1", "4.2", etc.
    title_ar: str
    objective_ar: str
    potential_risks_ar: str
    clauses: list[StandardClause]


class MinistryStandardDraft(BaseModel):
    meta: MinistryMeta

    # Notice page text
    notice_ar: str
    notice_en: str = ""

    # Section 1 — abbreviations and definitions (6-15 entries)
    definitions: list[DefinitionEntry]

    # Section 2 — objective (2-4 paragraphs)
    objective_ar: str

    # Section 3 — scope (intro + categorized)
    scope_intro_ar: str
    scope_systems_ar: list[str]        # Systems and Applications category
    scope_roles_ar: list[str]          # Roles and Permissions category
    scope_processes_ar: list[str]      # Critical Processes
    scope_persons_ar: list[str]        # Covered Persons and Entities

    # Section 4 — standards (dominant, 3-4 clusters)
    domain_clusters: list[StandardDomainCluster]

    # Section 5 — exceptions
    exceptions_ar: str

    # Section 6 — roles and responsibilities (table-like, 1-3 lines per role)
    roles_responsibilities: dict[str, str]   # role_ar -> duties_ar

    # Section 7 — update and review
    update_review_ar: str

    # Section 8 — compliance
    compliance_ar: str

    # Version control
    version_rows: list[VersionRow]
    approval_stages: list[ApprovalStage]

    # Dependency context digest
    dependency_summary: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# PROCEDURE DOCUMENT  (12-35 pages)  — the HOW
# schema: backend/procedure.json  → section_blueprints
# ══════════════════════════════════════════════════════════════════════════════

class ProcedureStep(BaseModel):
    """One step within a phase (7.x.y)."""
    step_id: str                       # e.g. "7.1.1", "7.2.3"
    step_title_ar: str
    actor_ar: str                      # who performs this step
    action_ar: str                     # what they do
    system_ar: str = ""                # system/tool used
    output_ar: str = ""                # output or deliverable
    evidence_ar: str = ""              # audit evidence
    timing_ar: str = ""                # timing or SLA
    sub_steps_ar: list[str] = []       # numbered sub-actions
    decision_ar: str = ""              # if decision point, describe it


class ProcedurePhase(BaseModel):
    """One phase of the procedure (7.x)."""
    phase_id: str                      # "7.1", "7.2", etc.
    phase_title_ar: str
    phase_objective_ar: str = ""
    steps: list[ProcedureStep]


class ProcedureRoleItem(BaseModel):
    role_ar: str
    responsibilities_ar: list[str]


class MinistryProcedureDraft(BaseModel):
    meta: MinistryMeta

    # Parent document references
    parent_policy_id: str = ""
    parent_standard_id: str = ""

    # Section 1 — definitions and abbreviations (5-12 entries)
    definitions: list[DefinitionEntry]

    # Section 2 — procedure objective (1-2 paragraphs)
    objective_ar: str

    # Section 3 — scope and applicability (1-2 paragraphs)
    scope_ar: str

    # Section 4 — roles and responsibilities
    roles: list[ProcedureRoleItem]

    # Section 5 — procedure overview (flow description, 1-2 paragraphs)
    overview_ar: str

    # Section 6 — triggers, prerequisites, inputs and tools
    triggers_ar: list[str]
    prerequisites_ar: list[str]
    inputs_ar: list[str]
    tools_ar: list[str]

    # Section 7 — detailed procedure steps (dominant, 2-6 phases)
    phases: list[ProcedurePhase]

    # Section 8 — decision points, exceptions and escalations
    decision_points_ar: list[str]
    exceptions_ar: str
    escalation_ar: str

    # Section 9 — outputs, records, evidence and forms
    outputs_ar: list[str]
    records_ar: list[str]
    evidence_ar: list[str]
    forms_ar: list[str]

    # Section 10 — time controls, SLAs and control checkpoints
    time_controls_ar: list[str]

    # Section 11 — related documents
    related_docs: list[PolicyRelatedDoc]

    # Section 12 — effective date
    effective_date_ar: str

    # Section 13 — procedure review
    review_ar: str

    # Section 14 — review and approval
    approval_stages: list[ApprovalStage]

    # Section 15 — version control
    version_rows: list[VersionRow]

    # Dependency context digest
    dependency_summary: str = ""
