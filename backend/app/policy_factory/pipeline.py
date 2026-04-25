"""
Policy Factory Pipeline — orchestrates all agents in order:

  Planner (o3)
    -> per section:
        Retriever (dense, top-30 per query)
        -> Cross-encoder Reranker (top-20)
        -> Enricher
        -> Drafter (section-by-section)
        -> Deterministic Validator (per section)
        -> [re-draft loop if gates fail]
    -> Reviewer (full document, LLM)
    -> Editor
    -> Renderer

Benefits of section-by-section approach:
  - Smaller context per LLM call -> tighter citation discipline
  - Citation spillover eliminated (IR control can't bleed into AC section)
  - Failed sections re-drafted in isolation without touching passing sections
  - Reranker applied per-section query so scores are calibrated to section topic
"""
import json
import os
from datetime import datetime, timezone

from .config import OUTPUT_DIR, MAX_DRAFT_RETRIES, RETRIEVAL_TOP_K_PER_QUERY, RERANK_TOP_K
from .models import (
    EntityProfile, DocumentSpec, SectionBlueprint,
    DraftOutput, DraftSection, ValidationReport, RetrievalPacket, ControlChunk, ControlBundle,
    PolicyDraftOutput, StandardDraftOutput, ProcedureDraftOutput,
)
from .control_store import ControlStore
from .reranker import rerank, rerank_with_scores
from .validation import validate
from .agents.qa_validator import QAValidator
from .agents.planner          import PlannerAgent
from .agents.enricher         import EnrichmentAgent
from .agents.drafter          import DraftingAgent          # generic (non-golden) docs
from .agents.policy_drafter   import PolicyDraftingAgent    # POL-* dedicated
from .agents.standard_drafter import StandardDraftingAgent  # STD-* dedicated
from .agents.procedure_drafter import ProcedureDraftingAgent # PRC-* dedicated (15 sections)
from .agents.procedure_supervisor import ProcedureSupervisor   # sub-agentic PRC-* orchestrator
from .agents.policy_supervisor    import PolicySupervisor       # sub-agentic POL-* orchestrator
from .agents.standard_supervisor  import StandardSupervisor     # sub-agentic STD-* orchestrator
from .agents.reviewer         import ReviewerAgent
from .agents.editor           import EditorialAgent
from .agents.gap_analyst      import GapAnalysisAgent
from .agents.diagram_agent    import DiagramAgent
from .agents.domain_profiles  import detect_procedure_domain, detect_policy_domain, detect_standard_domain
from .renderer import render, render_policy, render_standard, render_procedure


class PolicyFactory:
    def __init__(self):
        print("[Pipeline] Initialising control store...")
        self._store             = ControlStore()
        self._planner           = PlannerAgent()
        self._enricher          = EnrichmentAgent()
        self._drafter           = DraftingAgent()            # generic (non-golden) docs
        self._policy_drafter    = PolicyDraftingAgent()      # POL-* dedicated
        self._standard_drafter  = StandardDraftingAgent()    # STD-* dedicated
        self._procedure_drafter = ProcedureDraftingAgent()   # PRC-* 15-section dedicated
        self._reviewer          = ReviewerAgent()
        self._editor            = EditorialAgent()
        self._gap_analyst       = GapAnalysisAgent()
        self._diagram_agent     = DiagramAgent()
        self._qa_validator      = QAValidator()              # 7-gate schema validator
        # Sub-agentic supervisors (section-level parallel drafting)
        self._procedure_supervisor = ProcedureSupervisor(
            store=self._store,
            enricher=self._enricher,
            rerank_fn=rerank_with_scores,
            gap_analyst=self._gap_analyst,
        )
        self._policy_supervisor = PolicySupervisor(
            store=self._store,
            enricher=self._enricher,
            rerank_fn=rerank_with_scores,
        )
        self._standard_supervisor = StandardSupervisor(
            store=self._store,
            enricher=self._enricher,
            rerank_fn=rerank_with_scores,
        )

    # ── Public entry point ────────────────────────────────────────────────────

    def run(
        self,
        profile: EntityProfile,
        spec: DocumentSpec,
        output_dir: str = OUTPUT_DIR,
    ) -> dict:
        os.makedirs(output_dir, exist_ok=True)
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        import re as _re
        safe_topic = _re.sub(r'[^\w\-]', '_', spec.topic)[:60]
        prefix = os.path.join(
            output_dir,
            f"{spec.doc_type}_{safe_topic}_{run_id}"
        )

        print(f"\n{'='*60}")
        print(f"[Pipeline] {spec.doc_type.upper()} | {spec.topic} | {profile.org_name}")
        print(f"{'='*60}\n")

        # ── Route: Golden Policy Baseline for POL-* documents ─────────────────
        doc_id = getattr(spec, "doc_id", None) or f"POL-{spec.topic[:3].upper()}"
        if spec.doc_type == "policy" and doc_id.startswith("POL-"):
            return self._run_golden_policy(profile, spec, doc_id, output_dir, prefix)

        # ── Route: Golden Standard Baseline for STD-* documents ───────────────
        if spec.doc_type == "standard" and doc_id.startswith("STD-"):
            return self._run_golden_standard(profile, spec, doc_id, output_dir, prefix)

        # ── Route: Golden Procedure Baseline for PRC-* documents ──────────────
        if spec.doc_type == "procedure" and doc_id.startswith("PRC-"):
            return self._run_golden_procedure(profile, spec, doc_id, output_dir, prefix)

        # ── Stage 1: Plan ─────────────────────────────────────────────────────
        plan = self._planner.plan(profile, spec)
        _save_json(f"{prefix}_1_plan.json", plan.model_dump())
        print(f"[Pipeline] Plan: {len(plan.sections)} sections.\n")

        # ── Stage 2: Section-by-section retrieve → rerank → enrich → draft ───
        all_sections: list[DraftSection] = []
        all_bundles_map: dict[str, ControlBundle] = {}   # chunk_id -> bundle (dedup)

        for sec_idx, blueprint in enumerate(plan.sections, start=1):
            print(f"\n[Pipeline] --- Section {sec_idx}/{len(plan.sections)}: {blueprint.title} ---")

            # 2a. Dense retrieval (all queries for this section, deduped)
            section_chunks = self._retrieve_for_section(blueprint, plan.required_control_ids if sec_idx == 1 else [])

            # 2b. Cross-encoder reranking (with scores)
            rerank_query   = f"{blueprint.title}: {blueprint.purpose}"
            scored_chunks  = rerank_with_scores(rerank_query, section_chunks, top_k=RERANK_TOP_K)
            chunk_scores   = {c.chunk_id: s for s, c in scored_chunks}
            reranked       = [c for _, c in scored_chunks]

            # 2c. Enrich reranked chunks
            section_packet  = RetrievalPacket(query_topic=blueprint.title, chunks=reranked)
            section_bundles = self._enricher.enrich(section_packet)

            # Propagate cross-encoder scores to bundles
            for b in section_bundles:
                b.rerank_score = chunk_scores.get(b.chunk_id)
                all_bundles_map[b.chunk_id] = b

            # 2d. Draft section with per-section retry loop
            section = self._draft_section_loop(
                profile, spec, blueprint, section_bundles, sec_idx, prefix
            )
            all_sections.append(section)

            _save_json(f"{prefix}_2_section{sec_idx}.json", section.model_dump())

        # ── Stage 3: Assemble full DraftOutput ───────────────────────────────
        all_bundles = list(all_bundles_map.values())
        draft = DraftOutput(
            doc_id       = f"DOC-{spec.doc_type[:3].upper()}-{run_id[-6:]}",
            doc_type     = spec.doc_type,
            topic        = spec.topic,
            org_name     = profile.org_name,
            version      = spec.version,
            sections     = all_sections,
        )
        _save_json(f"{prefix}_3_assembled_draft.json", draft.model_dump())

        # Full document validation
        full_packet          = _bundles_to_packet(spec.topic, all_bundles)
        validation_report    = validate(draft, full_packet)
        _save_json(f"{prefix}_3_validation.json", validation_report.model_dump())

        # ── Stage 4: LLM Reviewer (full document) ────────────────────────────
        review_passed, fail_msgs = self._reviewer.review(draft, all_bundles, validation_report)
        _save_json(f"{prefix}_4_review.json", {"passed": review_passed, "fail_messages": fail_msgs})

        if not review_passed:
            print(f"[Pipeline] Reviewer flagged {len(fail_msgs)} issue(s) — proceeding to editorial pass.")

        # ── Stage 5: Editorial polish ─────────────────────────────────────────
        draft = self._editor.edit(draft)
        _save_json(f"{prefix}_5_final_draft.json", draft.model_dump())

        # ── Stage 6: Render ───────────────────────────────────────────────────
        main_path, annex_path = render(draft, all_bundles, output_dir)

        result = {
            "run_id":                   run_id,
            "doc_id":                   draft.doc_id,
            "doc_type":                 draft.doc_type,
            "topic":                    draft.topic,
            "org_name":                 draft.org_name,
            "version":                  draft.version,
            "sections":                 len(draft.sections),
            "total_requirements":       len(draft.all_requirements),
            "normative_requirements":   sum(1 for r in draft.all_requirements if r.is_normative),
            "citation_coverage_pct":    validation_report.citation_coverage_pct,
            "control_coverage_pct":     validation_report.control_coverage_pct,
            "validation_passed":        validation_report.passed,
            "reviewer_passed":          review_passed,
            "main_docx":                main_path,
            "traceability_docx":        annex_path,
            "artifacts_prefix":         prefix,
        }
        _save_json(f"{prefix}_0_result.json", result)

        print(f"\n{'='*60}")
        print(f"[Pipeline] COMPLETE")
        print(f"  Sections:     {result['sections']}")
        print(f"  Requirements: {result['total_requirements']} ({result['normative_requirements']} normative)")
        print(f"  Citation cov: {result['citation_coverage_pct']:.0%}")
        print(f"  Validation:   {'PASS' if result['validation_passed'] else 'FAIL'}")
        print(f"  Main DOCX:    {main_path}")
        print(f"  Traceability: {annex_path}")
        print(f"{'='*60}\n")
        return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _retrieve_for_section(
        self,
        blueprint: SectionBlueprint,
        required_control_ids: list[str] | None = None,
    ) -> list[ControlChunk]:
        """Dense retrieval for all queries in a section blueprint, deduplicated."""
        seen: set[str] = set()
        chunks: list[ControlChunk] = []

        for query in blueprint.retrieval_queries:
            packet = self._store.retrieve(query=query, top_k=RETRIEVAL_TOP_K_PER_QUERY)
            for c in packet.chunks:
                if c.chunk_id not in seen:
                    seen.add(c.chunk_id)
                    chunks.append(c)

        # Pin any required controls for this section's domains
        if required_control_ids:
            for c in self._store.retrieve_by_ids(required_control_ids):
                if c.chunk_id not in seen:
                    seen.add(c.chunk_id)
                    chunks.append(c)

        print(f"[Pipeline] Retrieved {len(chunks)} unique chunks for '{blueprint.title}'.")
        return chunks

    def _draft_section_loop(
        self,
        profile: EntityProfile,
        spec: DocumentSpec,
        blueprint: SectionBlueprint,
        bundles: list[ControlBundle],
        section_num: int,
        prefix: str,
    ) -> DraftSection:
        """Draft a single section with retry on validation failure."""
        reviewer_findings: list[str] | None = None

        for attempt in range(MAX_DRAFT_RETRIES + 1):
            if attempt > 0:
                print(f"[Pipeline] Re-drafting section {section_num}, attempt {attempt + 1}...")

            section = self._drafter.draft_section(
                profile=profile,
                spec=spec,
                blueprint=blueprint,
                bundles=bundles,
                section_num=section_num,
                reviewer_findings=reviewer_findings,
            )

            # Validate this section in isolation
            temp_draft  = DraftOutput(
                doc_id=f"TEMP-S{section_num}", doc_type=spec.doc_type,
                topic=spec.topic, org_name=profile.org_name,
                version=spec.version, sections=[section],
            )
            section_packet = _bundles_to_packet(blueprint.title, bundles)
            report         = validate(temp_draft, section_packet)

            _save_json(
                f"{prefix}_2_section{section_num}_attempt{attempt+1}_validation.json",
                report.model_dump()
            )

            if report.passed:
                if attempt > 0:
                    print(f"[Pipeline] Section {section_num} passed on attempt {attempt + 1}.")
                return section

            # Collect FAIL messages for re-draft prompt
            reviewer_findings = [
                f"{f.severity}|{f.check}: {f.message}"
                for f in report.findings if f.severity == "FAIL"
            ]

            if attempt == MAX_DRAFT_RETRIES:
                fails = len([f for f in report.findings if f.severity == "FAIL"])
                print(f"[Pipeline] WARNING: Section {section_num} still has {fails} FAIL(s) "
                      f"after {MAX_DRAFT_RETRIES + 1} attempts. Proceeding.")

        return section

    # ── Golden Policy Baseline flow ───────────────────────────────────────────

    def _run_golden_policy(
        self,
        profile: EntityProfile,
        spec: DocumentSpec,
        doc_id: str,
        output_dir: str,
        prefix: str,
    ) -> dict:
        """Full pipeline for POL-* documents following the Golden Policy Baseline."""
        print(f"[Pipeline] Golden Policy Baseline mode for {doc_id}\n")

        # 1. Targeted retrieval — NCA primary (25/query) + NIST supplementary + domain-specific
        domain = detect_policy_domain(spec.topic)
        print(f"[Pipeline] Policy domain: {domain.name}")
        policy_queries = [
            f"cybersecurity governance policy program {spec.topic}",
            "information security policy objectives confidentiality integrity availability",
            "cybersecurity policy suite roles responsibilities compliance",
            "cybersecurity risk management regulatory compliance requirements",
            "cybersecurity awareness training incident management vulnerability",
        ] + domain.extra_retrieval_queries
        seen: set[str] = set()
        all_chunks: list[ControlChunk] = []
        for q in policy_queries:
            for c in self._store.retrieve_nca(q, top_k=25).chunks:   # NCA first — authoritative
                if c.chunk_id not in seen:
                    seen.add(c.chunk_id)
                    all_chunks.append(c)
            for c in self._store.retrieve_nist(q, top_k=10).chunks:  # NIST supplementary
                if c.chunk_id not in seen:
                    seen.add(c.chunk_id)
                    all_chunks.append(c)

        print(f"[Pipeline] Policy retrieval: {len(all_chunks)} unique chunks "
              f"({sum(1 for c in all_chunks if c.framework.startswith('NCA_'))} NCA + "
              f"{sum(1 for c in all_chunks if c.framework == 'NIST_80053')} NIST).")

        # 2. Cross-encoder rerank against the policy topic
        rerank_query  = f"Cybersecurity governance policy: {spec.topic}"
        scored_chunks = rerank_with_scores(rerank_query, all_chunks, top_k=RERANK_TOP_K)
        chunk_scores  = {c.chunk_id: s for s, c in scored_chunks}

        # 3. Wrap as bundles — no enrichment LLM call (policy supervisor doesn't use
        #    implementation_notes/evidence_examples; _bundle_summary strips them)
        bundles = [
            ControlBundle(
                chunk_id=c.chunk_id, control_id=c.control_id, title=c.title,
                statement=c.statement, domain=c.domain, framework=c.framework,
                uae_ia_id=getattr(c, "uae_ia_id", None),
                nca_id=getattr(c, "nca_id", None),
                rerank_score=chunk_scores.get(c.chunk_id),
            )
            for _, c in scored_chunks
        ]
        _save_json(f"{prefix}_1_bundles.json", [b.model_dump() for b in bundles])

        # 4. Draft → QA → re-draft loop
        qa_findings: list[str] | None = None
        draft: PolicyDraftOutput | None = None
        qa_report = None

        for attempt in range(MAX_DRAFT_RETRIES + 1):
            print(f"\n[Pipeline] Policy draft attempt {attempt + 1}/{MAX_DRAFT_RETRIES + 1}")
            draft = self._policy_supervisor.draft(
                profile=profile,
                spec=spec,
                bundles=bundles,
                doc_id=doc_id,
                qa_findings=qa_findings,
            )
            _save_json(f"{prefix}_2_draft_attempt{attempt+1}.json", draft.model_dump())

            qa_report = self._qa_validator.validate_policy(draft)
            _save_json(f"{prefix}_2_qa_attempt{attempt+1}.json", qa_report.model_dump())

            if qa_report.passed:
                print(f"[Pipeline] Policy QA PASS on attempt {attempt + 1}.")
                break

            qa_findings = [
                f"{f.severity}|{f.check}: {f.message}"
                for f in qa_report.findings if f.severity == "FAIL"
            ]
            if attempt == MAX_DRAFT_RETRIES:
                fails = sum(1 for f in qa_report.findings if f.severity == "FAIL")
                print(f"[Pipeline] WARNING: Policy QA still has {fails} FAIL(s) after "
                      f"{MAX_DRAFT_RETRIES + 1} attempts. Proceeding.")

        # 5. Render
        main_path, annex_path = render_policy(draft, bundles, output_dir)

        result = {
            "run_id":            prefix.split("_")[-1] if "_" in prefix else "unknown",
            "doc_id":            draft.doc_id,
            "document_type":     "policy",
            "title":             draft.title_en,
            "version":           draft.version,
            "policy_elements":   len(draft.policy_elements),
            "subprograms":       len(draft.policy_subprograms),
            "qa_passed":         qa_report.passed if qa_report else False,
            "shall_count":       qa_report.shall_count if qa_report else 0,
            "traced_count":      qa_report.traced_count if qa_report else 0,
            "main_docx":         main_path,
            "traceability_docx": annex_path,
            "artifacts_prefix":  prefix,
        }
        _save_json(f"{prefix}_0_result.json", result)

        print(f"\n{'='*60}")
        print(f"[Pipeline] GOLDEN POLICY COMPLETE")
        print(f"  Doc ID:       {draft.doc_id}")
        print(f"  Title:        {draft.title_en}")
        print(f"  Elements:     {len(draft.policy_elements)}")
        print(f"  Subprograms:  {len(draft.policy_subprograms)}/34")
        print(f"  Policy QA:    {'PASS' if qa_report.passed else 'FAIL'}")
        print(f"  Main DOCX:    {main_path}")
        print(f"  Traceability: {annex_path}")
        print(f"{'='*60}\n")
        return result


    # ── Golden Standard Baseline flow ─────────────────────────────────────────

    def _run_golden_standard(
        self,
        profile: EntityProfile,
        spec: DocumentSpec,
        doc_id: str,
        output_dir: str,
        prefix: str,
    ) -> dict:
        """Full pipeline for STD-* documents following the Golden Standard Baseline."""
        print(f"[Pipeline] Golden Standard Baseline mode for {doc_id}\n")

        # 1. Targeted retrieval — NCA primary (25/query) + NIST supplementary + domain-specific
        domain = detect_standard_domain(spec.topic)
        print(f"[Pipeline] Standard domain: {domain.name}")
        standard_queries = [
            f"{spec.topic} cybersecurity standard requirements controls",
            f"{spec.topic} security risks confidentiality integrity availability",
            f"{spec.topic} NCA ECC controls regulatory compliance",
            f"{spec.topic} implementation requirements shall mandatory",
            f"cybersecurity standard roles responsibilities compliance disciplinary",
        ] + domain.extra_retrieval_queries
        seen: set[str] = set()
        all_chunks: list[ControlChunk] = []
        for q in standard_queries:
            for c in self._store.retrieve_nca(q, top_k=25).chunks:   # NCA first — authoritative
                if c.chunk_id not in seen:
                    seen.add(c.chunk_id)
                    all_chunks.append(c)
            for c in self._store.retrieve_nist(q, top_k=10).chunks:  # NIST supplementary
                if c.chunk_id not in seen:
                    seen.add(c.chunk_id)
                    all_chunks.append(c)

        print(f"[Pipeline] Standard retrieval: {len(all_chunks)} unique chunks "
              f"({sum(1 for c in all_chunks if c.framework.startswith('NCA_'))} NCA + "
              f"{sum(1 for c in all_chunks if c.framework == 'NIST_80053')} NIST).")

        # 2. Cross-encoder rerank
        rerank_query  = f"Cybersecurity standard: {spec.topic}"
        scored_chunks = rerank_with_scores(rerank_query, all_chunks, top_k=RERANK_TOP_K)
        chunk_scores  = {c.chunk_id: s for s, c in scored_chunks}

        # 3. Wrap as bundles — no enrichment LLM call (standard supervisor doesn't use
        #    implementation_notes/evidence_examples; _bundle_summary strips them)
        bundles = [
            ControlBundle(
                chunk_id=c.chunk_id, control_id=c.control_id, title=c.title,
                statement=c.statement, domain=c.domain, framework=c.framework,
                uae_ia_id=getattr(c, "uae_ia_id", None),
                nca_id=getattr(c, "nca_id", None),
                rerank_score=chunk_scores.get(c.chunk_id),
            )
            for _, c in scored_chunks
        ]
        _save_json(f"{prefix}_1_bundles.json", [b.model_dump() for b in bundles])

        # 4. Draft → QA → re-draft loop
        qa_findings: list[str] | None = None
        draft: StandardDraftOutput | None = None
        qa_report = None

        for attempt in range(MAX_DRAFT_RETRIES + 1):
            print(f"\n[Pipeline] Standard draft attempt {attempt + 1}/{MAX_DRAFT_RETRIES + 1}")
            draft = self._standard_supervisor.draft(
                profile=profile,
                spec=spec,
                bundles=bundles,
                doc_id=doc_id,
                qa_findings=qa_findings,
            )
            _save_json(f"{prefix}_2_draft_attempt{attempt+1}.json", draft.model_dump())

            qa_report = self._qa_validator.validate_standard(draft)
            _save_json(f"{prefix}_2_qa_attempt{attempt+1}.json", qa_report.model_dump())

            if qa_report.passed:
                print(f"[Pipeline] Standard QA PASS on attempt {attempt + 1}.")
                break

            qa_findings = [
                f"{f.severity}|{f.check}: {f.message}"
                for f in qa_report.findings if f.severity == "FAIL"
            ]
            if attempt == MAX_DRAFT_RETRIES:
                fails = sum(1 for f in qa_report.findings if f.severity == "FAIL")
                print(f"[Pipeline] WARNING: Standard QA still has {fails} FAIL(s) after "
                      f"{MAX_DRAFT_RETRIES + 1} attempts. Proceeding.")

        # 5. Render
        main_path, annex_path = render_standard(draft, bundles, output_dir)

        total_reqs = sum(len(d.requirements) for d in draft.domains)
        shall_n    = sum(
            1 for d in draft.domains for r in d.requirements
            if "shall" in r.statement_en.lower()
        )

        result = {
            "run_id":           prefix.split("_")[-1] if "_" in prefix else "unknown",
            "doc_id":           draft.doc_id,
            "document_type":    "standard",
            "title":            draft.title_en,
            "version":          draft.version,
            "definitions":      len(draft.definitions),
            "domains":          len(draft.domains),
            "total_reqs":       total_reqs,
            "shall_count":      qa_report.shall_count if qa_report else 0,
            "traced_count":     qa_report.traced_count if qa_report else 0,
            "qa_passed":        qa_report.passed if qa_report else False,
            "main_docx":        main_path,
            "traceability_docx": annex_path,
            "artifacts_prefix": prefix,
        }
        _save_json(f"{prefix}_0_result.json", result)

        print(f"\n{'='*60}")
        print(f"[Pipeline] GOLDEN STANDARD COMPLETE")
        print(f"  Doc ID:       {draft.doc_id}")
        print(f"  Title:        {draft.title_en}")
        print(f"  Definitions:  {len(draft.definitions)}")
        print(f"  Domains:      {len(draft.domains)}")
        print(f"  Requirements: {total_reqs} ({shall_n} shall)")
        print(f"  Standard QA:  {'PASS' if qa_report.passed else 'FAIL'}")
        print(f"  SHALL traced: {qa_report.traced_count}/{qa_report.shall_count}")
        print(f"  Main DOCX:    {main_path}")
        print(f"  Traceability: {annex_path}")
        print(f"{'='*60}\n")
        return result


    # ── Golden Procedure Baseline flow ────────────────────────────────────────

    def _run_golden_procedure(
        self,
        profile: EntityProfile,
        spec: DocumentSpec,
        doc_id: str,
        output_dir: str,
        prefix: str,
    ) -> dict:
        """Full pipeline for PRC-* documents following the Golden Procedure Baseline.

        Execution order:
          1. Targeted retrieval   — NCA primary (25/query) + NIST supplementary (10/query)
          2. Cross-encoder rerank — top-40
          3. Enrich               — implementation notes + evidence examples
          4. Gap Analysis         — detect missing operational context, fill from NIST
          5. Draft → QA → retry  — procedure draft with augmented contexts
             5a. On diagram FAIL  — DiagramAgent regenerates diagrams before full retry
          6. Render               — DOCX + traceability annex
        """
        print(f"[Pipeline] Golden Procedure Baseline mode for {doc_id}\n")

        # 1. Targeted retrieval — NCA primary + NIST supplementary + domain-specific
        domain = detect_procedure_domain(spec.topic)
        print(f"[Pipeline] Procedure domain: {domain.name}")
        procedure_queries = [
            f"{spec.topic} implementation procedure steps configuration",
            f"{spec.topic} security controls NCA ECC mandatory requirements",
            f"{spec.topic} technical controls verification testing validation",
            f"{spec.topic} roles responsibilities prerequisites tools",
            f"cybersecurity procedure evidence logging audit compliance",
        ] + domain.extra_retrieval_queries
        seen: set[str] = set()
        all_chunks: list[ControlChunk] = []
        for q in procedure_queries:
            for c in self._store.retrieve_nca(q, top_k=25).chunks:
                if c.chunk_id not in seen:
                    seen.add(c.chunk_id)
                    all_chunks.append(c)
            for c in self._store.retrieve_nist(q, top_k=10).chunks:
                if c.chunk_id not in seen:
                    seen.add(c.chunk_id)
                    all_chunks.append(c)

        nca_n  = sum(1 for c in all_chunks if c.framework.startswith("NCA_"))
        nist_n = sum(1 for c in all_chunks if c.framework == "NIST_80053")
        print(f"[Pipeline] Procedure retrieval: {len(all_chunks)} unique chunks "
              f"({nca_n} NCA + {nist_n} NIST).")

        # 2. Cross-encoder rerank
        rerank_query  = f"Cybersecurity procedure: {spec.topic}"
        scored_chunks = rerank_with_scores(rerank_query, all_chunks, top_k=RERANK_TOP_K)
        chunk_scores  = {c.chunk_id: s for s, c in scored_chunks}

        # 3. Wrap as bundles — no enrichment LLM call (procedure supervisor doesn't use
        #    implementation_notes/evidence_examples; _bundle_summary strips them)
        bundles = [
            ControlBundle(
                chunk_id=c.chunk_id, control_id=c.control_id, title=c.title,
                statement=c.statement, domain=c.domain, framework=c.framework,
                uae_ia_id=getattr(c, "uae_ia_id", None),
                nca_id=getattr(c, "nca_id", None),
                rerank_score=chunk_scores.get(c.chunk_id),
            )
            for _, c in scored_chunks
        ]
        _save_json(f"{prefix}_1_bundles.json", [b.model_dump() for b in bundles])

        # 4. Gap Analysis — only when an existing artifact is provided for comparison
        if spec.existing_document:
            print(f"[Pipeline] Gap Analysis: existing artifact provided — running gap analysis.")
            augmented_contexts = self._gap_analyst.analyze(
                bundles=bundles,
                topic=spec.topic,
                doc_type="procedure",
                existing_document=spec.existing_document,
            )
            _save_json(f"{prefix}_2_gap_analysis.json",
                       [a.model_dump() for a in augmented_contexts])
        else:
            augmented_contexts = []
            print(f"[Pipeline] Gap Analysis skipped — no existing artifact provided.")

        # 5. Research once, then Draft → QA → retry loop
        # Research is run ONCE outside the loop so parallel retrieval isn't
        # repeated on every QA-failure retry (each retry = 8-10 LLM enrich calls).
        print("[Pipeline] Running parallel research (once)...")
        procedure_research = self._procedure_supervisor.run_research(
            profile=profile,
            spec=spec,
            bundles=bundles,
        )

        qa_findings: list[str] | None = None
        draft: ProcedureDraftOutput | None = None
        qa_report = None

        for attempt in range(MAX_DRAFT_RETRIES + 1):
            print(f"\n[Pipeline] Procedure draft attempt {attempt + 1}/{MAX_DRAFT_RETRIES + 1}")
            draft = self._procedure_supervisor.draft(
                profile            = profile,
                spec               = spec,
                bundles            = bundles,
                augmented_contexts = augmented_contexts,
                doc_id             = doc_id,
                qa_findings        = qa_findings,
                research           = procedure_research,
            )
            _save_json(f"{prefix}_3_draft_attempt{attempt+1}.json", draft.model_dump())

            qa_report = self._qa_validator.validate_procedure(draft)
            _save_json(f"{prefix}_3_qa_attempt{attempt+1}.json", qa_report.model_dump())

            if qa_report.passed:
                print(f"[Pipeline] Procedure QA PASS on attempt {attempt + 1}.")
                break

            # Check if only diagram gates failed — use DiagramAgent for targeted repair
            fail_checks = {f.check for f in qa_report.findings if f.severity == "FAIL"}
            diagram_only_fails = fail_checks.issubset({
                "SWIMLANE_MISSING", "SWIMLANE_INVALID_SYNTAX", "SWIMLANE_NO_EDGES",
                "FLOWCHART_MISSING", "FLOWCHART_INVALID_SYNTAX", "FLOWCHART_NO_EDGES",
                "DIAGRAMS_IDENTICAL",
            })
            if diagram_only_fails and attempt < MAX_DRAFT_RETRIES:
                print(f"[Pipeline] Only diagram gates failed — running DiagramAgent repair.")
                try:
                    swimlane, flowchart = self._diagram_agent.generate(
                        title  = draft.title_en,
                        phases = draft.phases,
                        roles  = draft.roles_responsibilities,
                        topic  = spec.topic,
                    )
                    # Patch diagrams into draft without full re-draft
                    draft = ProcedureDraftOutput(
                        **{**draft.model_dump(),
                           "swimlane_diagram":  swimlane,
                           "flowchart_diagram": flowchart}
                    )
                    qa_report = self._qa_validator.validate_procedure(draft)
                    _save_json(f"{prefix}_3_qa_diagram_repair.json", qa_report.model_dump())
                    if qa_report.passed:
                        print(f"[Pipeline] Procedure QA PASS after diagram repair.")
                        break
                except Exception as exc:
                    print(f"[Pipeline] DiagramAgent repair failed: {exc}")

            qa_findings = [
                f"{f.severity}|{f.check}: {f.message}"
                for f in qa_report.findings if f.severity == "FAIL"
            ]
            if attempt == MAX_DRAFT_RETRIES:
                fails = sum(1 for f in qa_report.findings if f.severity == "FAIL")
                print(f"[Pipeline] WARNING: Procedure QA still has {fails} FAIL(s) after "
                      f"{MAX_DRAFT_RETRIES + 1} attempts. Proceeding.")

        # 6. Render
        main_path, annex_path = render_procedure(draft, bundles, output_dir)

        total_steps  = sum(len(ph.steps) for ph in draft.phases)
        cited_steps  = sum(
            1 for ph in draft.phases for st in ph.steps if st.citations
        )

        result = {
            "run_id":            prefix.split("_")[-1] if "_" in prefix else "unknown",
            "doc_id":            draft.doc_id,
            "document_type":     "procedure",
            "title":             draft.title_en,
            "version":           draft.version,
            "parent_policy_id":  draft.parent_policy_id,
            "parent_standard_id": draft.parent_standard_id,
            "phases":            len(draft.phases),
            "total_steps":       total_steps,
            "cited_steps":       cited_steps,
            "verification_checks": len(draft.verification_checks),
            "evidence_artifacts": len(draft.evidence_collection),
            "diagram_count":     qa_report.diagram_count if qa_report else 0,
            "qa_passed":         qa_report.passed if qa_report else False,
            "main_docx":         main_path,
            "traceability_docx": annex_path,
            "artifacts_prefix":  prefix,
        }
        _save_json(f"{prefix}_0_result.json", result)

        print(f"\n{'='*60}")
        print(f"[Pipeline] GOLDEN PROCEDURE COMPLETE")
        print(f"  Doc ID:          {draft.doc_id}")
        print(f"  Title:           {draft.title_en}")
        print(f"  Phases:          {len(draft.phases)}")
        print(f"  Steps:           {total_steps} ({cited_steps} cited)")
        print(f"  Verifications:   {len(draft.verification_checks)}")
        print(f"  Diagrams:        {result['diagram_count']}/2")
        print(f"  Procedure QA:    {'PASS' if qa_report.passed else 'FAIL'}")
        print(f"  Main DOCX:       {main_path}")
        print(f"  Traceability:    {annex_path}")
        print(f"{'='*60}\n")
        return result


# ── Module-level helpers ──────────────────────────────────────────────────────

def _save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    print(f"[Pipeline] Artifact -> {os.path.basename(path)}")


def _bundles_to_packet(topic: str, bundles: list[ControlBundle]) -> RetrievalPacket:
    """Reconstruct a RetrievalPacket from bundles for validation."""
    chunks = [
        ControlChunk(
            chunk_id   = b.chunk_id,
            framework  = b.framework,
            control_id = b.control_id,
            title      = b.title,
            statement  = b.statement,
            domain     = b.domain,
            uae_ia_id  = b.uae_ia_id,
            nca_id     = b.nca_id,
        )
        for b in bundles
    ]
    return RetrievalPacket(query_topic=topic, chunks=chunks)
