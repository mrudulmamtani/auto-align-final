"""
Golden Procedure QA — deterministic hard-gate checks for PRC-* documents.
No LLM involved. All checks are pure Python against ProcedureDraftOutput.

QA Gates (16 total):
  1.  document_type must be "procedure"
  2.  objective_en: non-empty and substantive (> 80 chars)
  3.  scope_en: mentions target systems or personnel categories
  4.  Roles: minimum 3, each with non-empty role_title and responsibilities
  5.  Prerequisites: minimum 3 items
  6.  Tools: minimum 1 item
  7.  Phases: minimum 4 phases (Preparation, Implementation, Verification, Documentation)
  8.  Steps: minimum 15 total steps across all phases
  9.  Each step: action and expected_output must be non-empty
  10. Citations validity: all cited chunk_ids must exist in the retrieved bundle
  11. Citation coverage: at least 30% of steps must carry citations
  12. Verification: minimum 6 checks, each with non-empty description + evidence_artifact
  13. Evidence collection: minimum 4 artifacts
  14. Exception handling: non-empty and substantive (> 80 chars)
  15. Swimlane diagram: present, valid Mermaid, contains arrows
  16. Flowchart diagram: present, valid Mermaid, distinct from swimlane

Returns ProcedureQAReport (passed, findings[], step_count, cited_step_count, diagram_count).
"""
from .models import ProcedureDraftOutput, ProcedureQAReport, ProcedureQAFinding, ControlBundle


def review_procedure(
    draft: ProcedureDraftOutput,
    bundles: list[ControlBundle],
) -> ProcedureQAReport:
    """
    Run all QA gates on a PRC-* procedure draft.
    Returns ProcedureQAReport.
    """
    findings: list[ProcedureQAFinding] = []
    bundle_chunk_ids = {b.chunk_id for b in bundles}

    def fail(check: str, msg: str):
        findings.append(ProcedureQAFinding(check=check, severity="FAIL", message=msg))

    def warn(check: str, msg: str):
        findings.append(ProcedureQAFinding(check=check, severity="WARN", message=msg))

    # ── Gate 1: Document type ─────────────────────────────────────────────────
    if draft.document_type != "procedure":
        fail("DOCUMENT_TYPE",
             f"Expected document_type='procedure', got '{draft.document_type}'")

    # ── Gate 2: Objective — substantive ───────────────────────────────────────
    if not draft.objective_en.strip():
        fail("OBJECTIVE_EMPTY", "objective_en must not be empty")
    elif len(draft.objective_en.strip()) < 80:
        warn("OBJECTIVE_SHALLOW",
             f"objective_en is too brief ({len(draft.objective_en.strip())} chars) — "
             "provide a substantive description of the procedure's purpose")

    # ── Gate 3: Scope — systems/personnel coverage ────────────────────────────
    scope_lower = draft.scope_en.lower()
    has_systems = any(
        kw in scope_lower for kw in
        ["system", "asset", "network", "application", "device", "server",
         "workstation", "infrastructure", "environment"]
    )
    has_personnel = any(
        kw in scope_lower for kw in
        ["personnel", "staff", "user", "administrator", "operator",
         "employee", "contractor", "engineer", "analyst"]
    )
    if not has_systems and not has_personnel:
        fail("SCOPE_COVERAGE",
             "scope_en must mention target systems/assets or personnel categories")

    # ── Gate 4: Roles — minimum 3, each fully defined ─────────────────────────
    if len(draft.roles_responsibilities) < 3:
        fail("ROLES_MINIMUM",
             f"Minimum 3 roles required, got {len(draft.roles_responsibilities)}")

    for i, role in enumerate(draft.roles_responsibilities):
        if not role.role_title.strip():
            fail("ROLE_TITLE_EMPTY", f"Role {i + 1} has empty role_title")
        if not role.responsibilities:
            fail("ROLE_RESPONSIBILITIES_EMPTY",
                 f"Role '{role.role_title}' has no responsibilities listed")

    # ── Gate 5: Prerequisites — minimum 3 ────────────────────────────────────
    if len(draft.prerequisites) < 3:
        fail("PREREQUISITES_MINIMUM",
             f"Minimum 3 prerequisites required, got {len(draft.prerequisites)}")

    # ── Gate 6: Tools — minimum 1 ────────────────────────────────────────────
    if len(draft.tools_required) < 1:
        fail("TOOLS_MINIMUM", "At least one tool must be listed in tools_required")

    # ── Gate 7: Phases — minimum 4 ───────────────────────────────────────────
    if len(draft.phases) < 4:
        fail("PHASES_MINIMUM",
             f"Minimum 4 phases required (Preparation, Implementation, Verification, Documentation), "
             f"got {len(draft.phases)}")

    # ── Gate 8: Steps — minimum 15 total ─────────────────────────────────────
    all_steps = [step for phase in draft.phases for step in phase.steps]
    step_count = len(all_steps)
    if step_count < 15:
        fail("STEPS_MINIMUM",
             f"Minimum 15 steps required across all phases, got {step_count}")

    # ── Gate 9: Each step — action and expected_output non-empty ─────────────
    for step in all_steps:
        if not step.action.strip():
            fail("STEP_ACTION_EMPTY",
                 f"Step {step.step_no} (phase: {step.phase}) has empty action")
        if not step.expected_output.strip():
            fail("STEP_OUTPUT_EMPTY",
                 f"Step {step.step_no} (phase: {step.phase}) has empty expected_output")

    # ── Gate 10: Citations validity — no fabricated chunk_ids ────────────────
    cited_step_count = 0
    for step in all_steps:
        if step.citations:
            cited_step_count += 1
            unknown = [c for c in step.citations if c not in bundle_chunk_ids]
            if unknown:
                fail("UNKNOWN_CITATION",
                     f"Step {step.step_no} cites chunk_ids not in retrieved bundle: "
                     f"{unknown[:3]} — do not fabricate chunk IDs")

    # ── Gate 11: Citation coverage — at least 30% of steps cited ─────────────
    if step_count > 0:
        coverage = cited_step_count / step_count
        if coverage < 0.30:
            warn("CITATION_COVERAGE_LOW",
                 f"Only {cited_step_count}/{step_count} steps carry citations "
                 f"({coverage:.0%}). At least 30% should be grounded in control chunks.")

    # ── Gate 12: Verification — minimum 6 checks, each with evidence ─────────
    if len(draft.verification_checks) < 6:
        fail("VERIFICATION_MINIMUM",
             f"Minimum 6 verification checks required, got {len(draft.verification_checks)}")

    for chk in draft.verification_checks:
        if not chk.description.strip():
            fail("VERIFICATION_DESCRIPTION_EMPTY",
                 f"Verification check {chk.check_id} has empty description")
        if not chk.evidence_artifact.strip():
            fail("VERIFICATION_EVIDENCE_EMPTY",
                 f"Verification check {chk.check_id} has no evidence_artifact specified")

    # ── Gate 13: Evidence collection — minimum 4 artifacts ───────────────────
    if len(draft.evidence_collection) < 4:
        fail("EVIDENCE_MINIMUM",
             f"Minimum 4 evidence artifacts required, got {len(draft.evidence_collection)}")

    # ── Gate 14: Exception handling — substantive ─────────────────────────────
    if not draft.exception_handling_en.strip():
        fail("EXCEPTION_HANDLING_EMPTY",
             "exception_handling_en must not be empty")
    elif len(draft.exception_handling_en.strip()) < 80:
        warn("EXCEPTION_HANDLING_SHALLOW",
             "exception_handling_en appears too brief — provide substantive guidance "
             "on how to escalate or manage deviations from this procedure")

    # ── Gate 15: Swimlane diagram ─────────────────────────────────────────────
    swimlane = draft.swimlane_diagram.strip()
    if not swimlane:
        fail("SWIMLANE_MISSING",
             "swimlane_diagram is empty — a Mermaid flowchart LR diagram is required")
    else:
        first_line = swimlane.lower().split("\n")[0]
        if not (first_line.startswith("flowchart") or first_line.startswith("graph")):
            fail("SWIMLANE_INVALID_SYNTAX",
                 "swimlane_diagram must start with 'flowchart' or 'graph' (Mermaid syntax)")
        elif "-->" not in swimlane and "---" not in swimlane:
            warn("SWIMLANE_NO_EDGES",
                 "swimlane_diagram appears to have no edges — diagram may be incomplete")
        if "lr" not in first_line and "td" not in first_line:
            warn("SWIMLANE_NO_DIRECTION",
                 "swimlane_diagram should specify direction (LR recommended for swimlanes)")

    # ── Gate 16: Flowchart diagram — present and distinct ────────────────────
    flowchart = draft.flowchart_diagram.strip()
    if not flowchart:
        fail("FLOWCHART_MISSING",
             "flowchart_diagram is empty — a Mermaid flowchart TD diagram is required")
    else:
        first_line_fc = flowchart.lower().split("\n")[0]
        if not (first_line_fc.startswith("flowchart") or first_line_fc.startswith("graph")):
            fail("FLOWCHART_INVALID_SYNTAX",
                 "flowchart_diagram must start with 'flowchart' or 'graph' (Mermaid syntax)")
        elif "-->" not in flowchart and "---" not in flowchart:
            warn("FLOWCHART_NO_EDGES",
                 "flowchart_diagram appears to have no edges — diagram may be incomplete")

    if swimlane and flowchart and swimlane == flowchart:
        fail("DIAGRAMS_IDENTICAL",
             "swimlane_diagram and flowchart_diagram must be distinct — "
             "swimlane shows actors (LR), flowchart shows decision logic (TD)")

    # ── Summary ───────────────────────────────────────────────────────────────
    diagram_count = sum([
        bool(swimlane and "-->" in swimlane),
        bool(flowchart and "-->" in flowchart),
    ])

    passed = not any(f.severity == "FAIL" for f in findings)
    fail_n = sum(1 for f in findings if f.severity == "FAIL")
    warn_n = sum(1 for f in findings if f.severity == "WARN")

    print(f"[ProcedureQA] {'PASS' if passed else 'FAIL'} | {fail_n} FAILs, {warn_n} WARNs | "
          f"steps={step_count}, cited={cited_step_count}, diagrams={diagram_count}")

    return ProcedureQAReport(
        passed           = passed,
        findings         = findings,
        step_count       = step_count,
        cited_step_count = cited_step_count,
        diagram_count    = diagram_count,
    )
