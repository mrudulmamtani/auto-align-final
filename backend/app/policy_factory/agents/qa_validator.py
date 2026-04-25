"""
QA Validator Agent — 7 deterministic gate pipeline.

Runs as a separate agent stage AFTER the Generator Agent, replacing the legacy
review_policy / review_standard / review_procedure modules.

Pipeline:
  Generator Agent
      ↓
  Gate 1 — Schema Compliance
      ↓
  Gate 2 — Structural Integrity
      ↓
  Gate 3 — Content Depth Validation
      ↓
  Gate 4 — Operational Completeness (procedures)
      ↓
  Gate 5 — Formatting & Layout
      ↓
  Gate 6 — Language Compliance
      ↓
  Gate 7 — Governance Completeness
      ↓
  QAReport → passed | FAIL findings → re-draft loop
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from ..models import PolicyDraftOutput, StandardDraftOutput, ProcedureDraftOutput
from ..schema_loader import load_schema

GateID = Literal[
    "SCHEMA_COMPLIANCE",
    "STRUCTURAL_INTEGRITY",
    "CONTENT_DEPTH",
    "OPERATIONAL_COMPLETENESS",
    "FORMATTING_LAYOUT",
    "LANGUAGE_COMPLIANCE",
    "GOVERNANCE_COMPLETENESS",
]


@dataclass
class QAFinding:
    gate_id: GateID
    severity: str        # "FAIL" | "WARN"
    check: str           # machine-readable check name
    message: str         # human-readable detail


@dataclass
class QAReport:
    """Unified QA report compatible with the pipeline's finding-extraction interface."""
    doc_type: str
    passed: bool
    findings: list[QAFinding] = field(default_factory=list)
    # Stats (populated per doc type)
    shall_count: int = 0
    traced_count: int = 0
    step_count: int = 0
    cited_step_count: int = 0
    diagram_count: int = 0

    def model_dump(self) -> dict:
        return {
            "doc_type":        self.doc_type,
            "passed":          self.passed,
            "findings":        [
                {
                    "gate_id":  f.gate_id,
                    "severity": f.severity,
                    "check":    f.check,
                    "message":  f.message,
                }
                for f in self.findings
            ],
            "shall_count":     self.shall_count,
            "traced_count":    self.traced_count,
            "step_count":      self.step_count,
            "cited_step_count": self.cited_step_count,
            "diagram_count":   self.diagram_count,
        }


class QAValidator:
    """
    Schema-driven 7-gate validator.  No LLM involved — pure deterministic checks
    against the authoritative JSON schemas (policy.json / standard.json / procedure.json).
    """

    # ── Public entry points ────────────────────────────────────────────────────

    def validate_policy(self, draft: PolicyDraftOutput) -> QAReport:
        schema = load_schema("policy")
        findings: list[QAFinding] = []

        self._g1_policy(draft, schema, findings)
        self._g2_policy(draft, schema, findings)
        self._g3_policy(draft, schema, findings)
        # Gate 4 (operational completeness) — not applicable for policies
        self._g5_policy(draft, findings)
        self._g6_policy(draft, schema, findings)
        self._g7_policy(draft, findings)

        shall_count  = sum(1 for e in draft.policy_elements if "shall" in e.statement_en.lower())
        traced_count = sum(1 for e in draft.policy_elements if e.trace)
        fails        = [f for f in findings if f.severity == "FAIL"]

        report = QAReport(
            doc_type     = "policy",
            passed       = len(fails) == 0,
            findings     = findings,
            shall_count  = shall_count,
            traced_count = traced_count,
        )
        _print_summary(report)
        return report

    def validate_standard(self, draft: StandardDraftOutput) -> QAReport:
        schema = load_schema("standard")
        findings: list[QAFinding] = []

        self._g1_standard(draft, schema, findings)
        self._g2_standard(draft, schema, findings)
        self._g3_standard(draft, schema, findings)
        # Gate 4 — not applicable for standards
        self._g5_standard(draft, findings)
        self._g6_standard(draft, schema, findings)
        self._g7_standard(draft, findings)

        shall_count  = sum(
            1 for d in draft.domains for r in d.requirements
            if "shall" in r.statement_en.lower()
        )
        traced_count = sum(
            1 for d in draft.domains for r in d.requirements if r.trace
        )
        fails = [f for f in findings if f.severity == "FAIL"]

        report = QAReport(
            doc_type     = "standard",
            passed       = len(fails) == 0,
            findings     = findings,
            shall_count  = shall_count,
            traced_count = traced_count,
        )
        _print_summary(report)
        return report

    def validate_procedure(self, draft: ProcedureDraftOutput) -> QAReport:
        schema = load_schema("procedure")
        findings: list[QAFinding] = []

        self._g1_procedure(draft, schema, findings)
        self._g2_procedure(draft, schema, findings)
        self._g3_procedure(draft, schema, findings)
        self._g4_procedure(draft, findings)
        self._g5_procedure(draft, findings)
        self._g6_procedure(draft, schema, findings)
        self._g7_procedure(draft, findings)

        total_steps  = sum(len(ph.steps) for ph in draft.phases)
        cited_steps  = sum(1 for ph in draft.phases for st in ph.steps if st.citations)
        diagram_count = sum(
            1 for d in [draft.swimlane_diagram, draft.flowchart_diagram]
            if d and "-->" in d
        )
        fails = [f for f in findings if f.severity == "FAIL"]

        report = QAReport(
            doc_type        = "procedure",
            passed          = len(fails) == 0,
            findings        = findings,
            step_count      = total_steps,
            cited_step_count = cited_steps,
            diagram_count   = diagram_count,
        )
        _print_summary(report)
        return report

    # ── Gate 1: Schema Compliance ──────────────────────────────────────────────

    def _g1_policy(self, draft: PolicyDraftOutput, schema: dict, F: list[QAFinding]):
        fail = lambda c, m: F.append(QAFinding("SCHEMA_COMPLIANCE", "FAIL", c, m))
        if draft.document_type != "policy":
            fail("DOC_TYPE", f"document_type='{draft.document_type}', expected 'policy'")
        if not draft.doc_id:
            fail("DOC_ID_MISSING", "doc_id is empty")
        if not draft.title_en:
            fail("TITLE_MISSING", "title_en is empty")
        if not draft.policy_elements:
            fail("POLICY_STATEMENT_MISSING", "policy_elements (Section 4) is empty")
        if not draft.objectives_en:
            fail("OBJECTIVES_MISSING", "objectives_en (Section 2) is empty")
        if not draft.scope_applicability_en:
            fail("SCOPE_MISSING", "scope_applicability_en (Section 3) is empty")
        if not draft.roles_responsibilities:
            fail("ROLES_MISSING", "roles_responsibilities (Section 5) is missing")
        if not draft.compliance_clauses:
            fail("COMPLIANCE_MISSING", "compliance_clauses is empty")
        if not draft.exceptions_en:
            fail("EXCEPTIONS_MISSING", "exceptions_en is empty")

    def _g1_standard(self, draft: StandardDraftOutput, schema: dict, F: list[QAFinding]):
        fail = lambda c, m: F.append(QAFinding("SCHEMA_COMPLIANCE", "FAIL", c, m))
        if draft.document_type != "standard":
            fail("DOC_TYPE", f"document_type='{draft.document_type}', expected 'standard'")
        if not draft.doc_id:
            fail("DOC_ID_MISSING", "doc_id is empty")
        if not draft.title_en:
            fail("TITLE_MISSING", "title_en is empty")
        if not draft.definitions:
            fail("DEFINITIONS_MISSING", "definitions (Section 1) is empty")
        if not draft.objectives_en:
            fail("OBJECTIVES_MISSING", "objectives_en (Section 2) is empty")
        if not draft.scope_en:
            fail("SCOPE_MISSING", "scope_en (Section 3) is empty")
        if not draft.domains:
            fail("DOMAINS_MISSING", "domains (Section 4) is empty")
        if not draft.roles_responsibilities:
            fail("ROLES_MISSING", "roles_responsibilities (Section 6) is empty")
        if not draft.review_update_en:
            fail("REVIEW_UPDATE_MISSING", "review_update_en (Section 7) is empty")
        if not draft.compliance_en:
            fail("COMPLIANCE_MISSING", "compliance_en (Section 8) is empty")

    def _g1_procedure(self, draft: ProcedureDraftOutput, schema: dict, F: list[QAFinding]):
        fail = lambda c, m: F.append(QAFinding("SCHEMA_COMPLIANCE", "FAIL", c, m))
        if draft.document_type != "procedure":
            fail("DOC_TYPE", f"document_type='{draft.document_type}', expected 'procedure'")
        if not draft.doc_id:
            fail("DOC_ID_MISSING", "doc_id is empty")
        if not draft.title_en:
            fail("TITLE_MISSING", "title_en is empty")
        # Validate all 15 sections are present
        required = {
            "definitions (§1)":                  draft.definitions,
            "objective_en (§2)":                 draft.objective_en,
            "scope_en (§3)":                     draft.scope_en,
            "roles_responsibilities (§4)":       draft.roles_responsibilities,
            "procedure_overview (§5)":           draft.procedure_overview,
            "prerequisites (§6)":                draft.prerequisites,
            "tools_required (§6)":               draft.tools_required,
            "phases (§7)":                       draft.phases,
            "exception_handling_en (§8)":        draft.exception_handling_en,
            "verification_checks (§9)":          draft.verification_checks,
            "evidence_collection (§9)":          draft.evidence_collection,
            "time_controls (§10)":               draft.time_controls,
            "related_documents (§11)":           draft.related_documents,
            "procedure_review (§13)":            draft.procedure_review,
            "review_and_approval (§14)":         draft.review_and_approval,
        }
        for field_name, value in required.items():
            if not value:
                fail(f"{field_name.split('(')[0].strip().upper().replace(' ', '_')}_MISSING",
                     f"{field_name} is empty — all 15 sections are required")

    # ── Gate 2: Structural Integrity ───────────────────────────────────────────

    def _g2_policy(self, draft: PolicyDraftOutput, schema: dict, F: list[QAFinding]):
        fail = lambda c, m: F.append(QAFinding("STRUCTURAL_INTEGRITY", "FAIL", c, m))
        warn = lambda c, m: F.append(QAFinding("STRUCTURAL_INTEGRITY", "WARN", c, m))

        # Elements 1, 2, 3 must exist (schema section 4 requires General Provisions)
        element_nos = {e.element_no for e in draft.policy_elements}
        for required_no in ("1", "2", "3"):
            if required_no not in element_nos:
                fail(f"ELEMENT_{required_no}_MISSING",
                     f"policy_element '{required_no}' is missing")

        # All elements must use "shall" (mandatory verb per schema)
        for e in draft.policy_elements:
            if "shall" not in e.statement_en.lower() and "must" not in e.statement_en.lower():
                warn("ELEMENT_NO_MANDATORY_VERB",
                     f"element {e.element_no} does not contain 'shall' or 'must'")

    def _g2_standard(self, draft: StandardDraftOutput, schema: dict, F: list[QAFinding]):
        fail = lambda c, m: F.append(QAFinding("STRUCTURAL_INTEGRITY", "FAIL", c, m))

        s = schema["standard_document_schema"]
        bp_defs = s["section_blueprints"]["1. abbreviations_and_definitions"]
        min_terms = bp_defs["expected_length"]["terms_min"]
        if len(draft.definitions) < min_terms:
            fail("DEFINITIONS_TOO_FEW",
                 f"definitions: {len(draft.definitions)}, schema min={min_terms}")

        # Each domain cluster must have title + objective + risks + requirements
        for i, domain in enumerate(draft.domains):
            if not domain.title_en:
                fail(f"DOMAIN_{i}_TITLE_MISSING", f"domain[{i}].title_en is empty")
            if not domain.objective_en:
                fail(f"DOMAIN_{i}_OBJECTIVE_MISSING", f"domain[{i}].objective_en is empty")
            if not domain.potential_risks_en:
                fail(f"DOMAIN_{i}_RISKS_MISSING", f"domain[{i}].potential_risks_en is empty")
            if not domain.requirements:
                fail(f"DOMAIN_{i}_REQS_MISSING", f"domain[{i}].requirements is empty")

        # Roles: schema expects 3 items (1-, 2-, 3-)
        if len(draft.roles_responsibilities) < 3:
            fail("ROLES_TOO_FEW",
                 f"roles_responsibilities: {len(draft.roles_responsibilities)}, expected 3")

        # Compliance: schema requires 3 clauses + disciplinary
        if len(draft.compliance_en) < 3:
            fail("COMPLIANCE_TOO_FEW",
                 f"compliance_en: {len(draft.compliance_en)}, expected min 3")

    def _g2_procedure(self, draft: ProcedureDraftOutput, schema: dict, F: list[QAFinding]):
        fail = lambda c, m: F.append(QAFinding("STRUCTURAL_INTEGRITY", "FAIL", c, m))

        s = schema["procedure_document_schema"]
        bp_defs = s["section_blueprints"]["1. definitions_and_abbreviations"]
        # Roles: min 3 (Security Team, IT Ops, System Owner per schema)
        if len(draft.roles_responsibilities) < 3:
            fail("ROLES_TOO_FEW",
                 f"roles_responsibilities: {len(draft.roles_responsibilities)}, min=3")

        # Prerequisites: min 3 per schema
        if len(draft.prerequisites) < 3:
            fail("PREREQUISITES_TOO_FEW",
                 f"prerequisites: {len(draft.prerequisites)}, min=3")

        # Tools: min 1
        if len(draft.tools_required) < 1:
            fail("TOOLS_MISSING", "tools_required is empty")

        # Each phase must have title and steps
        for i, phase in enumerate(draft.phases):
            if not phase.phase_name:
                fail(f"PHASE_{i}_TITLE_MISSING", f"phase[{i}].phase_name is empty")
            if not phase.steps:
                fail(f"PHASE_{i}_NO_STEPS", f"phase[{i}] '{phase.phase_name}' has no steps")

    # ── Gate 3: Content Depth Validation ──────────────────────────────────────

    def _g3_policy(self, draft: PolicyDraftOutput, schema: dict, F: list[QAFinding]):
        fail = lambda c, m: F.append(QAFinding("CONTENT_DEPTH", "FAIL", c, m))

        s = schema["policy_document_schema"]
        # Section 4 must be dominant — check clause count
        cm = s["section_blueprints"]["4. policy_statement"]["clause_model"]
        min_clauses = cm["expected_clause_count"]["min"]
        if len(draft.policy_elements) < min_clauses:
            fail("POLICY_STATEMENT_TOO_SHORT",
                 f"policy_elements: {len(draft.policy_elements)}, schema min={min_clauses}")

        # Objectives must be substantive
        if len(draft.objectives_en) < 150:
            fail("OBJECTIVES_TOO_SHORT",
                 f"objectives_en: {len(draft.objectives_en)} chars, min=150")

        # Scope must be substantive
        if len(draft.scope_applicability_en) < 150:
            fail("SCOPE_TOO_SHORT",
                 f"scope_applicability_en: {len(draft.scope_applicability_en)} chars, min=150")

        # Every 'shall' element must have at least one trace entry
        for e in draft.policy_elements:
            if "shall" in e.statement_en.lower() and not e.trace:
                fail("SHALL_NO_TRACE",
                     f"element {e.element_no}: contains 'shall' but has no trace entries")

    def _g3_standard(self, draft: StandardDraftOutput, schema: dict, F: list[QAFinding]):
        fail = lambda c, m: F.append(QAFinding("CONTENT_DEPTH", "FAIL", c, m))

        # Section 4 must be 45-60% — proxy: min 3 domain clusters
        if len(draft.domains) < 3:
            fail("TOO_FEW_DOMAINS",
                 f"domains: {len(draft.domains)}, schema min=3")

        # Each domain: min 3 requirements per schema
        for i, domain in enumerate(draft.domains):
            if len(domain.requirements) < 3:
                fail(f"DOMAIN_{i}_TOO_FEW_REQS",
                     f"domain '{domain.title_en}': {len(domain.requirements)} reqs, min=3")

        # Every 'shall' requirement must have trace
        for d in draft.domains:
            for r in d.requirements:
                if "shall" in r.statement_en.lower() and not r.trace:
                    fail("SHALL_NO_TRACE",
                         f"req {r.req_id}: contains 'shall' but has no trace entries")

    def _g3_procedure(self, draft: ProcedureDraftOutput, schema: dict, F: list[QAFinding]):
        fail = lambda c, m: F.append(QAFinding("CONTENT_DEPTH", "FAIL", c, m))

        # Section 7 must be dominant — min 2 phases, 5 steps
        if len(draft.phases) < 2:
            fail("TOO_FEW_PHASES",
                 f"phases: {len(draft.phases)}, min=2")

        total_steps = sum(len(ph.steps) for ph in draft.phases)
        if total_steps < 5:
            fail("TOO_FEW_STEPS", f"total steps: {total_steps}, min=5")

        # Verification: min 3 per schema
        if len(draft.verification_checks) < 3:
            fail("VERIFICATION_TOO_FEW",
                 f"verification_checks: {len(draft.verification_checks)}, min=3")

        # Evidence: min 2 per schema
        if len(draft.evidence_collection) < 2:
            fail("EVIDENCE_TOO_FEW",
                 f"evidence_collection: {len(draft.evidence_collection)}, min=2")

    # ── Gate 4: Operational Completeness (procedures only) ────────────────────

    def _g4_procedure(self, draft: ProcedureDraftOutput, F: list[QAFinding]):
        fail = lambda c, m: F.append(QAFinding("OPERATIONAL_COMPLETENESS", "FAIL", c, m))

        for pi, phase in enumerate(draft.phases):
            for si, step in enumerate(phase.steps):
                for field_name, value in [
                    ("actor",           step.actor),
                    ("action",          step.action),
                    ("expected_output",  step.expected_output),
                ]:
                    if not value:
                        fail(
                            f"STEP_MISSING_{field_name.upper()}",
                            f"phase[{pi}].step[{si}] (#{step.step_no}) missing '{field_name}'"
                        )

        # Each verification check must have an evidence_artifact
        for ci, check in enumerate(draft.verification_checks):
            if not check.evidence_artifact:
                fail("CHECK_NO_EVIDENCE",
                     f"verification_check[{ci}] (id={check.check_id}) missing evidence_artifact")

        # Exception handling must be substantive (schema: 80+ chars)
        if len(draft.exception_handling_en) < 80:
            fail("EXCEPTION_HANDLING_TOO_SHORT",
                 f"exception_handling_en: {len(draft.exception_handling_en)} chars, min=80")

    # ── Gate 5: Formatting & Layout ────────────────────────────────────────────

    def _g5_policy(self, draft: PolicyDraftOutput, F: list[QAFinding]):
        fail = lambda c, m: F.append(QAFinding("FORMATTING_LAYOUT", "FAIL", c, m))
        warn = lambda c, m: F.append(QAFinding("FORMATTING_LAYOUT", "WARN", c, m))
        if not draft.version:
            fail("VERSION_MISSING", "version is empty — version control table requires a version")
        if not draft.classification:
            fail("CLASSIFICATION_MISSING",
                 "classification is empty — schema requires classification footer")
        if not draft.effective_date:
            warn("EFFECTIVE_DATE_MISSING", "effective_date not set")

    def _g5_standard(self, draft: StandardDraftOutput, F: list[QAFinding]):
        fail = lambda c, m: F.append(QAFinding("FORMATTING_LAYOUT", "FAIL", c, m))
        warn = lambda c, m: F.append(QAFinding("FORMATTING_LAYOUT", "WARN", c, m))
        if not draft.version:
            fail("VERSION_MISSING", "version is empty")
        if not draft.classification:
            fail("CLASSIFICATION_MISSING", "classification is empty")
        # Domain requirement numbering: N.M pattern per schema
        for i, domain in enumerate(draft.domains):
            for j, req in enumerate(domain.requirements):
                if not re.match(r'^\d+\.\d+$', req.req_id):
                    warn("REQ_ID_FORMAT",
                         f"domain[{i}].req[{j}] req_id '{req.req_id}' "
                         f"should match N.M pattern (e.g. '1.1')")

    def _g5_procedure(self, draft: ProcedureDraftOutput, F: list[QAFinding]):
        fail = lambda c, m: F.append(QAFinding("FORMATTING_LAYOUT", "FAIL", c, m))
        warn = lambda c, m: F.append(QAFinding("FORMATTING_LAYOUT", "WARN", c, m))
        if not draft.version:
            fail("VERSION_MISSING", "version is empty")
        if not draft.classification:
            fail("CLASSIFICATION_MISSING", "classification is empty")

        sw = draft.swimlane_diagram or ""
        fw = draft.flowchart_diagram or ""

        # Swimlane: PlantUML activity diagram with swimlanes — MANDATORY
        if not sw or "@startuml" not in sw:
            fail("SWIMLANE_MISSING",
                 "swimlane_diagram missing or not valid PlantUML (missing '@startuml')")
        elif "|" not in sw:
            warn("SWIMLANE_NO_LANES",
                 "swimlane_diagram should use '|Role Name|' lane separators")

        # Flowchart: PlantUML activity diagram — MANDATORY
        if not fw or "@startuml" not in fw:
            fail("FLOWCHART_MISSING",
                 "flowchart_diagram missing or not valid PlantUML (missing '@startuml')")

        # Diagrams must be distinct
        if sw and fw and sw.strip() == fw.strip():
            fail("DIAGRAMS_IDENTICAL",
                 "swimlane_diagram and flowchart_diagram are identical")

    # ── Gate 6: Language Compliance ────────────────────────────────────────────

    def _g6_policy(self, draft: PolicyDraftOutput, schema: dict, F: list[QAFinding]):
        fail = lambda c, m: F.append(QAFinding("LANGUAGE_COMPLIANCE", "FAIL", c, m))
        s = schema["policy_document_schema"]
        # Policy: Arabic primary — ensure primary content fields are non-empty
        if not draft.title_en:
            fail("TITLE_MISSING", "title_en is empty — primary language title required")
        # Objectives must reference CIA triad (schema requires it)
        obj = draft.objectives_en.lower()
        if not any(w in obj for w in ("confidentiality", "integrity", "availability")):
            fail("CIA_NOT_MENTIONED",
                 "objectives_en does not mention Confidentiality, Integrity, or Availability")

    def _g6_standard(self, draft: StandardDraftOutput, schema: dict, F: list[QAFinding]):
        fail = lambda c, m: F.append(QAFinding("LANGUAGE_COMPLIANCE", "FAIL", c, m))
        if not draft.title_en:
            fail("TITLE_MISSING", "title_en is empty")
        obj = draft.objectives_en.lower()
        if not any(w in obj for w in ("confidentiality", "integrity", "availability")):
            fail("CIA_NOT_MENTIONED",
                 "objectives_en does not mention Confidentiality, Integrity, or Availability")

    def _g6_procedure(self, draft: ProcedureDraftOutput, schema: dict, F: list[QAFinding]):
        fail = lambda c, m: F.append(QAFinding("LANGUAGE_COMPLIANCE", "FAIL", c, m))
        if not draft.title_en:
            fail("TITLE_MISSING", "title_en is empty")

    # ── Gate 7: Governance Completeness ───────────────────────────────────────

    def _g7_policy(self, draft: PolicyDraftOutput, F: list[QAFinding]):
        fail = lambda c, m: F.append(QAFinding("GOVERNANCE_COMPLETENESS", "FAIL", c, m))
        warn = lambda c, m: F.append(QAFinding("GOVERNANCE_COMPLETENESS", "WARN", c, m))
        if not draft.owner:
            fail("OWNER_MISSING", "owner is empty")
        if not draft.effective_date:
            warn("EFFECTIVE_DATE_MISSING", "effective_date not set")
        if len(draft.compliance_clauses) < 3:
            fail("COMPLIANCE_TOO_FEW",
                 f"compliance_clauses: {len(draft.compliance_clauses)}, required=3")
        if not draft.exceptions_en:
            fail("EXCEPTIONS_MISSING", "exceptions_en is empty — schema requires exceptions section")

    def _g7_standard(self, draft: StandardDraftOutput, F: list[QAFinding]):
        fail = lambda c, m: F.append(QAFinding("GOVERNANCE_COMPLETENESS", "FAIL", c, m))
        warn = lambda c, m: F.append(QAFinding("GOVERNANCE_COMPLETENESS", "WARN", c, m))
        if not draft.owner:
            fail("OWNER_MISSING", "owner is empty")
        if not draft.review_update_en:
            fail("REVIEW_UPDATE_MISSING", "review_update_en (Section 7) is empty")
        if len(draft.compliance_en) < 3:
            fail("COMPLIANCE_TOO_FEW",
                 f"compliance_en: {len(draft.compliance_en)}, min=3")
        if not draft.closing_note_en:
            warn("CLOSING_NOTE_MISSING", "closing_note_en is empty")

    def _g7_procedure(self, draft: ProcedureDraftOutput, F: list[QAFinding]):
        fail = lambda c, m: F.append(QAFinding("GOVERNANCE_COMPLETENESS", "FAIL", c, m))
        warn = lambda c, m: F.append(QAFinding("GOVERNANCE_COMPLETENESS", "WARN", c, m))
        if not draft.owner:
            fail("OWNER_MISSING", "owner is empty")
        if not draft.exception_handling_en:
            fail("EXCEPTION_HANDLING_MISSING",
                 "exception_handling_en is empty — schema requires exceptions section")
        if not draft.parent_policy_id:
            warn("PARENT_POLICY_MISSING",
                 "parent_policy_id not set — procedure should reference its parent policy")
        if not draft.parent_standard_id:
            warn("PARENT_STANDARD_MISSING",
                 "parent_standard_id not set — procedure should reference its parent standard")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _print_summary(report: QAReport) -> None:
    fails  = sum(1 for f in report.findings if f.severity == "FAIL")
    warns  = sum(1 for f in report.findings if f.severity == "WARN")
    status = "PASS" if report.passed else f"FAIL ({fails} failures)"
    print(f"[QAValidator] {report.doc_type.upper()} — {status} | {warns} warnings")
    for f in report.findings:
        if f.severity == "FAIL":
            print(f"  ✗ [{f.gate_id}] {f.check}: {f.message}")
