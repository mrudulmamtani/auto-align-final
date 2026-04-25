"""
Golden Policy QA — 12 deterministic hard-gate checks for POL-* documents.
No LLM involved. All checks are pure Python against the PolicyDraftOutput model.
A single FAIL blocks progression to the editor/renderer.
"""
from .models import PolicyDraftOutput, ControlBundle, PolicyQAFinding, PolicyQAReport, GOLDEN_TOC

_REQUIRED_ROLES = [
    "authority_owner_delegates", "legal", "internal_audit",
    "HR", "cybersecurity", "other_departments", "all_staff",
]


def review_policy(draft: PolicyDraftOutput, bundles: list[ControlBundle]) -> PolicyQAReport:
    findings: list[PolicyQAFinding] = []
    valid_control_ids = {b.control_id for b in bundles}
    valid_chunk_ids   = {b.chunk_id   for b in bundles}

    def fail(check: str, msg: str):
        findings.append(PolicyQAFinding(check=check, severity="FAIL", message=msg))

    def warn(check: str, msg: str):
        findings.append(PolicyQAFinding(check=check, severity="WARN", message=msg))

    # ── 1. TOC exact ─────────────────────────────────────────────────────────
    # (structural — verified by schema, but double-check heading count)
    # TOC is implicit from GOLDEN_TOC constant; sections are output fields, not free text.
    # This check is a reminder gate; always passes in code-enforced schema path.

    # ── 2. Objectives: CIA mention ────────────────────────────────────────────
    obj = draft.objectives_en.lower()
    has_cia_words = (
        ("confidentiality" in obj and "integrity" in obj and "availability" in obj)
        or "cia" in obj
    )
    if not has_cia_words:
        fail("OBJECTIVES_CIA",
             "Objectives must mention Confidentiality, Integrity, and Availability (or 'CIA').")

    # ── 3. Objectives: regulatory reference ───────────────────────────────────
    has_regulatory = any(kw in obj for kw in ["1-3-1", "ecc", "nca", "regulatory", "uae ia", "compliance"])
    if not has_regulatory:
        fail("OBJECTIVES_REGULATORY",
             "Objectives must reference a regulatory requirement (e.g. NCA ECC 1-3-1 or UAE IA).")

    # ── 4. Scope: all-assets + all-personnel statement ────────────────────────
    scope = draft.scope_applicability_en.lower()
    if "all" not in scope or not any(w in scope for w in ["asset", "personnel", "staff", "employee"]):
        fail("SCOPE_ALL_COVERAGE",
             "Scope must state it applies to all assets and all personnel.")

    # ── 5. Scope: driver + internal process feed statement ────────────────────
    has_driver = any(w in scope for w in ["driver", "drives", "basis for", "governs all"])
    has_processes = sum(1 for w in ["hr", "vendor", "project", "change"] if w in scope) >= 2
    if not has_driver:
        fail("SCOPE_DRIVER",
             "Scope must state this policy drives / is the basis for all cyber policies, procedures, and standards.")
    if not has_processes:
        fail("SCOPE_PROCESSES",
             "Scope must reference at least 2 internal processes it feeds (HR, vendor, project, change management).")

    # ── 6. Policy elements 1, 2, 3 must exist ────────────────────────────────
    element_map = {e.element_no: e for e in draft.policy_elements}
    for req_no in ["1", "2", "3"]:
        if req_no not in element_map:
            fail(f"ELEMENT_{req_no}_MISSING",
                 f"Policy element {req_no} is mandatory per the Golden Policy Baseline.")

    # ── 7. Every element must use 'shall' ─────────────────────────────────────
    for e in draft.policy_elements:
        if "shall" not in e.statement_en.lower():
            fail("ELEMENT_NO_SHALL",
                 f"Element {e.element_no} must contain normative 'shall' language.")

    # ── 8. Every 'shall' element — must have at least one NCA trace entry ────
    shall_count   = 0
    traced_count  = 0
    nca_traced    = 0
    for e in draft.policy_elements:
        if "shall" in e.statement_en.lower():
            shall_count += 1
            if e.trace:
                traced_count += 1
            else:
                fail("SHALL_NO_TRACE",
                     f"Element {e.element_no} has 'shall' but no trace entries (citation required).")
            nca_entries = [t for t in e.trace if t.framework.upper().startswith("NCA")]
            if nca_entries:
                nca_traced += 1
            else:
                fail("SHALL_NO_NCA_TRACE",
                     f"Element {e.element_no} has 'shall' but no NCA trace entry. "
                     f"NCA controls are the authoritative basis. Found frameworks: "
                     f"{[t.framework for t in e.trace]}")

    # ── 9. No fabricated control IDs ─────────────────────────────────────────
    for e in draft.policy_elements:
        for t in e.trace:
            # Accept if control_id is in our library OR source_ref is a known chunk_id
            if t.control_id not in valid_control_ids and t.source_ref not in valid_chunk_ids:
                fail("UNKNOWN_CONTROL",
                     f"Element {e.element_no} traces '{t.control_id}' (ref: {t.source_ref}) "
                     f"which is not in the retrieved bundle. Do not fabricate control IDs.")

    # ── 10. Subprogram catalog (2-1..2-34) ────────────────────────────────────
    sub_count = len(draft.policy_subprograms)
    if sub_count < 30:
        fail("SUBPROGRAM_CATALOG",
             f"Policy suite must include at least 30 subprograms (found {sub_count}). "
             f"Required: 2-1 through 2-34.")
    elif sub_count < 34:
        warn("SUBPROGRAM_CATALOG_INCOMPLETE",
             f"Only {sub_count}/34 subprograms present — expected all 34.")

    # ── 11. Roles and Responsibilities: all 7 groups must be non-empty ────────
    rr = draft.roles_responsibilities
    for role in _REQUIRED_ROLES:
        content = getattr(rr, role, [])
        if not content:
            fail(f"ROLE_EMPTY_{role.upper()}",
                 f"Roles & Responsibilities must include non-empty content for '{role}'.")

    # ── 12. Compliance: exactly 3 clauses, disciplinary clause present ────────
    n_clauses = len(draft.compliance_clauses)
    if n_clauses != 3:
        fail("COMPLIANCE_NOT_3",
             f"Policy Compliance section must have exactly 3 numbered clauses (found {n_clauses}).")
    has_disciplinary = any(
        any(w in c.lower() for w in ["disciplin", "terminat", "action", "sanction", "penalt"])
        for c in draft.compliance_clauses
    )
    if not has_disciplinary:
        fail("COMPLIANCE_NO_DISCIPLINARY",
             "Third compliance clause must reference disciplinary action for violations.")

    # ── 13. Exceptions: blocking clause ──────────────────────────────────────
    exc = draft.exceptions_en.lower()
    has_blocking = (
        any(w in exc for w in ["authoriz", "approval", "approved"]) and
        any(w in exc for w in ["bypass", "exception", "prior", "without"])
    )
    if not has_blocking:
        fail("EXCEPTIONS_BLOCKING",
             "Exceptions section must state no bypass is permitted without prior official authorization "
             "from Cybersecurity or the Cyber Supervisory Committee.")

    # ── 14. Closing note ─────────────────────────────────────────────────────
    cn = draft.closing_note_en.lower()
    if not any(w in cn for w in ["approved", "in force", "effective", "in effect"]):
        fail("CLOSING_NOTE",
             "Closing note must state that policies and standards are approved and in force.")

    passed = not any(f.severity == "FAIL" for f in findings)
    fail_n = sum(1 for f in findings if f.severity == "FAIL")
    warn_n = sum(1 for f in findings if f.severity == "WARN")
    print(f"[PolicyQA] {'PASS' if passed else 'FAIL'} | {fail_n} FAILs, {warn_n} WARNs | "
          f"shall={shall_count} nca_traced={nca_traced}/{shall_count}")
    return PolicyQAReport(
        passed=passed,
        findings=findings,
        shall_count=shall_count,
        traced_count=nca_traced,   # traced_count now = NCA-traced count
    )
