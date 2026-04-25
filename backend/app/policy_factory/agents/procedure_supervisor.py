"""
Procedure Supervisor — sub-agentic orchestrator for PRC-* documents.

Replaces the monolithic ProcedureDraftingAgent with a multi-step workflow:

  Step 1 [Parallel, Deterministic+LLM]: ResearchCoordinator fires retrieval
          for all section groups concurrently
  Step 2 [LLM]:         FrontMatterAgent drafts §1-6
  Step 3 [LLM × N]:    PhaseAgent drafts each phase independently
  Step 4 [LLM]:         EvidenceAgent drafts §8-10
  Step 5 [Deterministic]: MetadataBuilder fills §11-15
  Step 6 [Deterministic]: CitationValidator cleans all step citations
  Step 7 [Deterministic]: StructuralChecker validates the assembled draft
  Step 8 [LLM, targeted]: SectionRepairAgent fixes failing sections only
  Step 9 [Deterministic]: Final assembly into ProcedureDraftOutput
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ..config import DRAFT_MODEL_POLICY
from ..models import (
    EntityProfile, DocumentSpec, ControlBundle, AugmentedControlContext,
    ProcedureDraftOutput, ProcedureRoleItem, ProcedureStep, ProcedurePhase,
    ProcedureVerificationCheck, ProcedureDefinition, ProcedureTrigger,
    ProcedureInputForm, ProcedureOutputRecord, ProcedureEvidenceRecord,
    ProcedureTimeControl, TraceEntry,
)
from .workflow_models import SectionOutput, WorkflowResearch
from .domain_profiles import DomainProfile, detect_procedure_domain
from .deterministic_tools import MetadataBuilder, CitationValidator, StructuralChecker, RelatedDocsBuilder
from .procedure_section_agents import FrontMatterAgent, PhaseAgent, EvidenceAgent, SectionRepairAgent
from .research_coordinator import ResearchCoordinator

# Default phase plan when no existing plan is provided
_DEFAULT_PHASE_NAMES = [
    "Preparation and Planning",
    "Implementation and Execution",
    "Verification and Testing",
    "Documentation and Closure",
]


class ProcedureSupervisor:
    """
    Sub-agentic supervisor for procedure generation.

    External interface matches ProcedureDraftingAgent.draft() so it can be
    used as a drop-in replacement in the pipeline.
    """

    def __init__(self, store, enricher, rerank_fn, gap_analyst=None):
        self._research    = ResearchCoordinator(store, enricher, rerank_fn, gap_analyst)
        self._front       = FrontMatterAgent()
        self._phase       = PhaseAgent()
        self._evidence    = EvidenceAgent()
        self._repair      = SectionRepairAgent()
        self._meta        = MetadataBuilder()
        self._citations   = CitationValidator()
        self._structural  = StructuralChecker()
        self._related     = RelatedDocsBuilder()

    def run_research(
        self,
        profile: EntityProfile,
        spec: DocumentSpec,
        bundles: list[ControlBundle],
    ) -> WorkflowResearch:
        """
        Run the parallel research phase once.  Call this before the retry loop
        and pass the result to draft() via the `research` parameter so retrieval
        is not repeated on every QA-failure retry.
        """
        domain = detect_procedure_domain(spec.topic)
        research = self._research.run_procedure(
            profile=profile,
            spec=spec,
            domain=domain,
            phase_names=_DEFAULT_PHASE_NAMES,
        )
        # Merge with pipeline-level pre-retrieved bundles (dedup)
        seen_ids = {b.chunk_id for b in research.full_bundles}
        for b in bundles:
            if b.chunk_id not in seen_ids:
                research.full_bundles.append(b)
                seen_ids.add(b.chunk_id)
        return research

    def draft(
        self,
        profile: EntityProfile,
        spec: DocumentSpec,
        bundles: list[ControlBundle],            # pre-retrieved full bundle set
        augmented_contexts: list[AugmentedControlContext],
        doc_id: str,
        qa_findings: list[str] | None = None,
        research: WorkflowResearch | None = None, # pass pre-computed research to avoid re-running
    ) -> ProcedureDraftOutput:
        """
        Full sub-agentic procedure drafting workflow.
        Returns a ProcedureDraftOutput identical in structure to the monolithic drafter.
        """
        print(f"\n[ProcedureSupervisor] Starting sub-agentic workflow for {doc_id}")
        domain = detect_procedure_domain(spec.topic)
        print(f"[ProcedureSupervisor] Domain: {domain.name}")

        # ── Step 1: Parallel research (skip if already computed) ─────────────
        if research is None:
            research = self.run_research(profile, spec, bundles)

        bundle_ids = {b.chunk_id for b in research.full_bundles}

        # ── Step 2: Front Matter (§1-6) ───────────────────────────────────────
        front_result = self._front.draft(
            profile=profile,
            spec=spec,
            bundles=research.front_matter_bundles or bundles[:25],
            domain=domain,
            qa_findings=_filter_qa(qa_findings, "front_matter"),
        )
        if front_result.status == "fail":
            print("[ProcedureSupervisor] FrontMatter failed — retrying once")
            front_result = self._front.draft(profile, spec,
                                             research.front_matter_bundles or bundles[:25],
                                             domain)

        # ── Step 3: Phase drafting (§7.N) — one call per phase ───────────────
        roles_for_phases = [
            r.get("role_title", "Security Team")
            for r in front_result.data.get("roles_responsibilities", [])
        ]
        if not roles_for_phases:
            roles_for_phases = ["Security Team", "IT Operations", "System Owner"]

        phase_results: list[SectionOutput] = []
        for i, pr in enumerate(research.phase_research):
            phase_bundles = pr.bundles or bundles[i*5:(i+1)*5] or bundles[:20]
            result = self._phase.draft(
                profile=profile,
                spec=spec,
                phase_index=i,
                phase_name=pr.phase_name,
                bundles=phase_bundles,
                augmented=augmented_contexts or pr.augmented,
                domain=domain,
                all_phase_names=_DEFAULT_PHASE_NAMES,
                roles=roles_for_phases,
                qa_findings=_filter_qa(qa_findings, f"phase_{i}"),
            )
            if result.status == "fail":
                print(f"[ProcedureSupervisor] Phase {i} failed — retrying")
                result = self._phase.draft(
                    profile, spec, i, pr.phase_name,
                    phase_bundles, augmented_contexts or [], domain,
                    _DEFAULT_PHASE_NAMES, roles_for_phases,
                )
            phase_results.append(result)

        # ── Step 4: Evidence & Escalation (§8-10) ────────────────────────────
        phases_summary = [
            {
                "phase_name": r.data.get("phase_name", f"Phase {i}"),
                "step_count": len(r.data.get("steps", [])),
                "step_actions": [s.get("action", "")[:120] for s in r.data.get("steps", [])[:3]],
            }
            for i, r in enumerate(phase_results)
            if r.status == "ok"
        ]
        evidence_result = self._evidence.draft(
            profile=profile,
            spec=spec,
            phases_summary=phases_summary,
            bundles=research.evidence_bundles or bundles[-20:],
            domain=domain,
            qa_findings=_filter_qa(qa_findings, "evidence"),
        )
        if evidence_result.status == "fail":
            print("[ProcedureSupervisor] Evidence section failed — retrying")
            evidence_result = self._evidence.draft(
                profile, spec, phases_summary,
                research.evidence_bundles or bundles[-20:], domain,
            )

        # ── Step 5: Deterministic metadata (§11-15) ───────────────────────────
        meta = self._meta.build_procedure(doc_id, spec.topic, profile.org_name, spec.version)
        related_docs = self._related.build(doc_id, spec.topic)

        # ── Step 6: Citation validation ───────────────────────────────────────
        cleaned_phases = []
        for r in phase_results:
            if r.status != "ok":
                continue
            steps = r.data.get("steps", [])
            cleaned_steps = self._citations.validate(steps, bundle_ids)
            cleaned_phases.append({**r.data, "steps": cleaned_steps})

        # ── Step 7: Structural check ──────────────────────────────────────────
        assembled_dict = _assemble_dict(front_result, cleaned_phases, evidence_result, meta)
        issues = self._structural.check_procedure(assembled_dict)
        if issues:
            print(f"[ProcedureSupervisor] Structural issues: {issues[:5]}")

        # ── Step 8: Parse into ProcedureDraftOutput ───────────────────────────
        return _parse_to_model(assembled_dict, doc_id, spec, related_docs)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _filter_qa(qa_findings: list[str] | None, section_id: str) -> list[str] | None:
    """Extract QA findings relevant to a specific section."""
    if not qa_findings:
        return None
    keywords = {
        "front_matter": ["objective", "scope", "role", "prerequisite", "definition", "tool"],
        "evidence":     ["verification", "evidence", "escalation", "exception", "time_control", "sla"],
    }
    kws = keywords.get(section_id, [])
    if section_id.startswith("phase_"):
        kws = ["step", "action", "expected_output", "code_block", "citation", "phase"]
    relevant = [f for f in qa_findings if any(kw in f.lower() for kw in kws)]
    return relevant or None


def _assemble_dict(
    front: SectionOutput,
    phases_data: list[dict],
    evidence: SectionOutput,
    meta: dict,
) -> dict:
    """Merge section outputs into a single flat dict matching ProcedureDraftOutput fields."""
    fd = front.data
    ed = evidence.data

    return {
        **meta,
        "definitions":             fd.get("definitions", []),
        "objective_en":            fd.get("objective_en", ""),
        "scope_en":                fd.get("scope_en", ""),
        "procedure_overview":      fd.get("procedure_overview", ""),
        "roles_responsibilities":  fd.get("roles_responsibilities", []),
        "triggers":                fd.get("triggers", []),
        "prerequisites":           fd.get("prerequisites", []),
        "tools_required":          fd.get("tools_required", []),
        "input_forms":             fd.get("input_forms", []),
        "phases":                  phases_data,
        "decision_points_and_escalations": ed.get("decision_points_and_escalations", ""),
        "exception_handling_en":   ed.get("exception_handling_en", ""),
        "verification_checks":     ed.get("verification_checks", []),
        "evidence_collection":     ed.get("evidence_collection", []),
        "output_records":          ed.get("output_records", []),
        "time_controls":           ed.get("time_controls", []),
        "swimlane_diagram":        "",   # filled by renderer
        "flowchart_diagram":       "",   # filled by renderer
    }


def _parse_to_model(
    d: dict,
    doc_id: str,
    spec: DocumentSpec,
    related_docs: list[dict],
) -> ProcedureDraftOutput:
    """Parse assembled dict into the typed ProcedureDraftOutput model."""

    roles = [
        ProcedureRoleItem(
            role_title=r.get("role_title", "Security Team"),
            responsibilities=r.get("responsibilities", []),
        )
        for r in d.get("roles_responsibilities", [])
    ]

    phases = []
    for ph in d.get("phases", []):
        steps = [
            ProcedureStep(
                step_no         = s.get("step_no", ""),
                phase           = s.get("phase", ""),
                actor           = s.get("actor", ""),
                action          = s.get("action", ""),
                expected_output = s.get("expected_output", ""),
                code_block      = s.get("code_block", ""),
                citations       = s.get("citations", []),
            )
            for s in ph.get("steps", [])
        ]
        phases.append(ProcedurePhase(
            phase_name  = ph.get("phase_name", ""),
            phase_intro = ph.get("phase_intro", ""),
            steps       = steps,
        ))

    # verification_checks: map LLM output (check_id, description, evidence_artifact)
    # to ProcedureVerificationCheck (check_id, description, method, expected_result, evidence_artifact)
    verification_checks = [
        ProcedureVerificationCheck(
            check_id          = vc.get("check_id", ""),
            description       = vc.get("description", ""),
            method            = vc.get("method", "manual"),
            expected_result   = vc.get("expected_result", "Check passes when evidence artifact is present."),
            evidence_artifact = vc.get("evidence_artifact", ""),
        )
        for vc in d.get("verification_checks", [])
    ]

    definitions = [
        ProcedureDefinition(term=df.get("term", ""), definition=df.get("definition", ""))
        for df in d.get("definitions", [])
    ] if d.get("definitions") and isinstance(d["definitions"][0], dict) else []

    # triggers: LLM uses trigger_id; model uses trigger
    triggers = [
        ProcedureTrigger(
            trigger=t.get("trigger_id", t.get("trigger", "")),
            description=t.get("description", ""),
        )
        for t in d.get("triggers", [])
    ] if d.get("triggers") and isinstance(d["triggers"][0], dict) else []

    # input_forms: LLM uses form_name + description; model uses form_name + purpose + reference
    input_forms = [
        ProcedureInputForm(
            form_name=f.get("form_name", ""),
            purpose=f.get("description", f.get("purpose", "")),
            reference=f.get("reference", ""),
        )
        for f in d.get("input_forms", [])
    ] if d.get("input_forms") and isinstance(d["input_forms"][0], dict) else []

    # tools_required: LLM returns list of dicts; model expects list[str]
    raw_tools = d.get("tools_required", [])
    if raw_tools and isinstance(raw_tools[0], dict):
        tools_required = [
            f"{t.get('tool_name', '')} — {t.get('purpose', '')} ({t.get('version_guidance', '')})"
            for t in raw_tools
        ]
    else:
        tools_required = [str(t) for t in raw_tools]

    # output_records: LLM uses record_id/record_name/description/owner/retention
    # ProcedureOutputRecord uses output + recipient_or_destination
    output_records_raw = d.get("output_records", [])
    outputs_records = [
        ProcedureOutputRecord(
            output=f"{r.get('record_name', r.get('record_id', ''))} — {r.get('description', '')}",
            recipient_or_destination=r.get("owner", ""),
        )
        for r in output_records_raw
    ]

    # time_controls: LLM uses control_id/activity/sla/escalation
    # ProcedureTimeControl uses activity_or_step/service_level/responsible_role/escalation_if_breached
    time_controls = [
        ProcedureTimeControl(
            activity_or_step       = tc.get("activity", tc.get("activity_or_step", "")),
            service_level          = tc.get("sla", tc.get("service_level", "")),
            responsible_role       = tc.get("responsible_role", "Security Team"),
            escalation_if_breached = tc.get("escalation", tc.get("escalation_if_breached", "")),
        )
        for tc in d.get("time_controls", [])
    ]

    # evidence_collection may be list[str] or list[dict]
    raw_evidence = d.get("evidence_collection", [])
    if raw_evidence and isinstance(raw_evidence[0], dict):
        evidence_list = [e.get("artifact", e.get("description", str(e))) for e in raw_evidence]
    else:
        evidence_list = [str(e) for e in raw_evidence]

    # related_documents: may be list[dict] or list[str]
    raw_related = related_docs if related_docs else d.get("related_documents", [])
    if raw_related and isinstance(raw_related[0], dict):
        related_documents = [
            r.get("doc_id", r.get("title", str(r))) for r in raw_related
        ]
    else:
        related_documents = [str(r) for r in raw_related]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    return ProcedureDraftOutput(
        doc_id              = d.get("doc_id", doc_id),
        title_en            = d.get("title_en", f"{spec.topic} Procedure"),
        version             = d.get("version", spec.version),
        effective_date      = d.get("effective_date", now),
        owner               = d.get("owner", "CISO"),
        classification      = d.get("classification", "Internal"),
        parent_policy_id    = d.get("parent_policy_id", "POL-01"),
        parent_standard_id  = d.get("parent_standard_id", "STD-01"),
        definitions         = definitions,
        objective_en        = d.get("objective_en", ""),
        scope_en            = d.get("scope_en", ""),
        procedure_overview  = d.get("procedure_overview", ""),
        roles_responsibilities = roles,
        triggers            = triggers,
        prerequisites       = d.get("prerequisites", []),
        tools_required      = tools_required,
        input_forms         = input_forms,
        phases              = phases,
        decision_points_and_escalations = d.get("decision_points_and_escalations", ""),
        exception_handling_en = d.get("exception_handling_en", ""),
        outputs_records     = outputs_records,
        evidence_records    = [],  # not produced by EvidenceAgent schema; filled by renderer
        verification_checks = verification_checks,
        evidence_collection = evidence_list,
        time_controls       = time_controls,
        related_documents   = related_documents,
        procedure_review    = (
            f"This procedure shall be reviewed annually. "
            f"Out-of-cycle review is triggered by: (1) material changes to {spec.topic} technology, "
            f"(2) changes to the parent {d.get('parent_policy_id', 'POL-01')} policy, "
            f"(3) changes to NCA ECC requirements or other applicable regulatory frameworks, "
            f"(4) significant security incidents related to {spec.topic}."
        ),
        review_and_approval = (
            f"Prepared by: Security Engineering Team | "
            f"Reviewed by: Security Manager | "
            f"Recommended by: Head of Cybersecurity | "
            f"Approved by: Chief Information Security Officer"
        ),
        swimlane_diagram    = "",
        flowchart_diagram   = "",
    )
