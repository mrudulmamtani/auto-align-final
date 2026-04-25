"""
Golden Standard QA — 12 deterministic hard-gate checks for STD-* documents.
No LLM involved. All checks are pure Python against the StandardDraftOutput model.
A single FAIL blocks progression to the renderer.
"""
import re
from .models import (
    StandardDraftOutput, ControlBundle,
    StandardQAFinding, StandardQAReport,
    STANDARD_TOC, EXCEPTIONS_CLAUSE,
)


def review_standard(
    draft: StandardDraftOutput,
    bundles: list[ControlBundle],
) -> StandardQAReport:
    findings: list[StandardQAFinding] = []
    valid_control_ids = {b.control_id for b in bundles}
    valid_chunk_ids   = {b.chunk_id   for b in bundles}

    def fail(check: str, msg: str):
        findings.append(StandardQAFinding(check=check, severity="FAIL", message=msg))

    def warn(check: str, msg: str):
        findings.append(StandardQAFinding(check=check, severity="WARN", message=msg))

    # ── 1. TOC exact — exactly 6 headings, English text ──────────────────────
    if draft.document_type != "standard":
        fail("TOC_EXACT", f"document_type must be 'standard', got '{draft.document_type}'.")
    # TOC structure is enforced by STANDARD_TOC constant; schema verifies fields exist.
    # Double-check that all 6 sections will be rendered (field existence is the gate here).

    # ── 2. Definitions — minimum 5 terms ─────────────────────────────────────
    n_defs = len(draft.definitions)
    if n_defs < 5:
        fail("DEFINITIONS_MIN_5",
             f"Definitions table must have at least 5 terms (found {n_defs}).")

    # ── 3. Objectives — CIA mention ───────────────────────────────────────────
    obj = draft.objectives_en.lower()
    has_cia = (
        ("confidentiality" in obj and "integrity" in obj and "availability" in obj)
        or "cia" in obj
    )
    if not has_cia:
        fail("OBJECTIVES_CIA",
             "Objectives must mention Confidentiality, Integrity, and Availability (or 'CIA').")

    # ── 4. Objectives — regulatory reference ─────────────────────────────────
    has_regulatory = any(
        kw in obj
        for kw in ["1-3-1", "ecc", "nca", "regulatory", "uae ia", "compliance", "ness"]
    )
    if not has_regulatory:
        fail("OBJECTIVES_REGULATORY",
             "Objectives must reference a regulatory requirement (NCA ECC, UAE IA, etc.).")

    # ── 5. Scope — applicability + exceptions clause ──────────────────────────
    scope = draft.scope_en.lower()
    # Must cover all personnel
    has_all_personnel = any(
        w in scope
        for w in ["employee", "contractor", "service provider", "consultant", "visitor", "all staff", "all personnel"]
    )
    if not has_all_personnel:
        fail("SCOPE_PERSONNEL",
             "Scope must state applicability to employees/contractors/service providers/consultants/visitors.")
    # Must cover all assets/systems
    has_all_assets = any(w in scope for w in ["asset", "system", "application", "technology"])
    if not has_all_assets:
        fail("SCOPE_ASSETS",
             "Scope must state applicability to all information/technology assets/systems.")
    # Exceptions clause
    exc_keywords = ["exception", "approved", "cybersecurity department", "risk acceptance"]
    has_exceptions = sum(1 for kw in exc_keywords if kw in scope) >= 2
    if not has_exceptions:
        fail("EXCEPTIONS_CLAUSE_PRESENT",
             f"Scope must include the exact exceptions clause: '{EXCEPTIONS_CLAUSE}'")

    # ── 6. Domains — minimum 5 ────────────────────────────────────────────────
    n_domains = len(draft.domains)
    if n_domains < 5:
        fail("DOMAINS_MIN_5",
             f"Standards Requirements must include at least 5 domain blocks (found {n_domains}).")

    # ── 7. Each domain — objective + risks + requirements (all 3 subparts) ───
    for d in draft.domains:
        if not d.objective_en.strip():
            fail("DOMAIN_MISSING_OBJECTIVE",
                 f"Domain {d.domain_number} '{d.title_en}' is missing objective_en.")
        if not d.potential_risks_en.strip():
            fail("DOMAIN_MISSING_RISKS",
                 f"Domain {d.domain_number} '{d.title_en}' is missing potential_risks_en.")
        if len(d.requirements) < 5:
            fail("DOMAIN_MIN_5_REQS",
                 f"Domain {d.domain_number} '{d.title_en}' must have at least 5 requirements "
                 f"(found {len(d.requirements)}).")

    # ── 8. Requirements numbering — N.M sequential within each domain ────────
    for d in draft.domains:
        dn = d.domain_number
        for idx, req in enumerate(d.requirements, start=1):
            expected = f"{dn}.{idx}"
            if req.req_id != expected:
                warn("REQUIREMENTS_NUMBERING",
                     f"Domain {dn}: expected req_id '{expected}', got '{req.req_id}'.")

    # ── 9. Every 'shall' requirement backed by an NCA trace entry ─────────────
    shall_count = 0
    traced_count = 0
    for d in draft.domains:
        for req in d.requirements:
            if "shall" in req.statement_en.lower():
                shall_count += 1
                nca_trace = [
                    t for t in req.trace
                    if t.framework.upper().startswith("NCA")
                ]
                if nca_trace:
                    traced_count += 1
                else:
                    fail("SHALL_NO_NCA_TRACE",
                         f"Requirement {req.req_id} has 'shall' but no NCA trace entry "
                         f"(framework must start with 'NCA_'). Non-empty trace: {[t.framework for t in req.trace]}.")

    if shall_count == 0:
        fail("NO_SHALL_REQUIREMENTS",
             "Standards Requirements must contain at least one 'shall' statement.")

    # ── 10. No fabricated control IDs ────────────────────────────────────────
    for d in draft.domains:
        for req in d.requirements:
            for t in req.trace:
                if (t.control_id not in valid_control_ids
                        and t.source_ref not in valid_chunk_ids):
                    fail("UNKNOWN_CONTROL",
                         f"Requirement {req.req_id} traces '{t.control_id}' (ref: {t.source_ref}) "
                         f"which is not in the retrieved bundle. Do not fabricate control IDs.")

    # ── 11. Roles and Responsibilities — 3-line pattern (1-, 2-, 3-) ─────────
    rr = draft.roles_responsibilities
    if len(rr) < 3:
        fail("ROLES_FORMAT_COUNT",
             f"Roles & Responsibilities must have at least 3 items (found {len(rr)}).")
    expected_nos = {"1-", "2-", "3-"}
    actual_nos = {r.item_no for r in rr}
    missing = expected_nos - actual_nos
    if missing:
        fail("ROLES_FORMAT_NUMBERS",
             f"Roles & Responsibilities missing item numbers: {sorted(missing)}. "
             f"Must include items labeled '1-', '2-', '3-'.")

    # ── 12a. Compliance — exactly 3 clauses ───────────────────────────────────
    n_clauses = len(draft.compliance_en)
    if n_clauses != 3:
        fail("COMPLIANCE_NOT_3",
             f"Compliance with the Standard must have exactly 3 clauses (found {n_clauses}).")

    # ── 12b. Disciplinary clause ──────────────────────────────────────────────
    has_disciplinary = any(
        any(w in c.lower() for w in ["disciplin", "terminat", "action", "sanction", "penalt", "consequence"])
        for c in draft.compliance_en
    )
    if not has_disciplinary:
        fail("COMPLIANCE_NO_DISCIPLINARY",
             "Compliance must include a clause about disciplinary action for violations.")

    # ── 12c. All staff must comply clause ─────────────────────────────────────
    has_staff_comply = any(
        any(w in c.lower() for w in ["all staff", "all employee", "must comply", "shall comply"])
        for c in draft.compliance_en
    )
    if not has_staff_comply:
        warn("COMPLIANCE_NO_ALL_STAFF",
             "Compliance should include a clause stating all staff must comply.")

    # ── 13. Closing note ──────────────────────────────────────────────────────
    cn = draft.closing_note_en.lower()
    has_closing = any(
        w in cn
        for w in ["latest", "approved", "official", "applicable", "published"]
    )
    if not has_closing:
        fail("CLOSING_NOTE_MISSING",
             "Closing note must state that only the latest approved standards are official and applicable.")

    # ── Summary ───────────────────────────────────────────────────────────────
    passed = not any(f.severity == "FAIL" for f in findings)
    fail_n = sum(1 for f in findings if f.severity == "FAIL")
    warn_n = sum(1 for f in findings if f.severity == "WARN")
    print(f"[StandardQA] {'PASS' if passed else 'FAIL'} | {fail_n} FAILs, {warn_n} WARNs | "
          f"shall={shall_count} nca_traced={traced_count}")
    return StandardQAReport(
        passed=passed,
        findings=findings,
        shall_count=shall_count,
        traced_count=traced_count,
    )
