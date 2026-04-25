"""
Research Coordinator — parallel retrieval + enrichment before any drafting begins.

Fires NCA + NIST retrieval for multiple section topics concurrently using
ThreadPoolExecutor (since store.retrieve_* are synchronous).  Enriches and
reranks each bundle set, then packages results as WorkflowResearch.
"""
from __future__ import annotations

import concurrent.futures
from typing import Callable

from ..config import RETRIEVAL_TOP_K_PER_QUERY, RERANK_TOP_K
from ..models import (
    EntityProfile, DocumentSpec, ControlChunk, ControlBundle,
    AugmentedControlContext, RetrievalPacket,
)
from .workflow_models import WorkflowResearch, PhaseResearch
from .domain_profiles import DomainProfile


class ResearchCoordinator:
    """
    Orchestrates parallel retrieval + enrichment for all document sections.

    Usage:
        coordinator = ResearchCoordinator(store, enricher, rerank_fn, gap_analyst)
        research = coordinator.run_procedure(profile, spec, domain, phases_plan)
        # research.front_matter_bundles, research.phase_research[n].bundles, etc.
    """

    def __init__(self, store, enricher, rerank_fn: Callable, gap_analyst=None):
        self._store      = store
        self._enricher   = enricher
        self._rerank     = rerank_fn   # rerank_with_scores(query, chunks, top_k) -> list[(score, chunk)]
        self._gap_analyst = gap_analyst

    # ── Procedure ──────────────────────────────────────────────────────────────

    def run_procedure(
        self,
        profile: EntityProfile,
        spec: DocumentSpec,
        domain: DomainProfile,
        phase_names: list[str],
    ) -> WorkflowResearch:
        """
        Run parallel retrieval for:
          - front matter (§1-6): governance, roles, prerequisites
          - each phase (§7.N): phase-specific technical controls
          - evidence section (§8-10): verification, evidence, escalation
        Then run gap analysis once on the merged bundle set (if existing_document provided).
        """
        print(f"[ResearchCoordinator] Starting parallel procedure research "
              f"({len(phase_names)} phases + front_matter + evidence)")

        # Build query sets
        front_matter_queries = [
            f"{spec.topic} cybersecurity procedure roles responsibilities prerequisites",
            f"{spec.topic} scope applicability systems assets personnel",
            f"{spec.topic} NCA ECC mandatory requirements controls",
        ] + domain.extra_retrieval_queries[:2]

        phase_query_sets = []
        for pname in phase_names:
            phase_query_sets.append([
                f"{spec.topic} {pname} implementation steps configuration commands",
                f"{spec.topic} {pname} technical controls security requirements",
                f"{spec.topic} {pname} verification testing validation evidence",
            ] + domain.extra_retrieval_queries[2:4])

        evidence_queries = [
            f"{spec.topic} verification checks evidence artifacts audit compliance",
            f"{spec.topic} exception escalation rollback decision points",
            f"{spec.topic} SLA time controls service level agreement",
            "cybersecurity incident escalation CISO notification regulatory",
        ]

        # Fire all queries in parallel
        all_query_sets = (
            [("front_matter", front_matter_queries)]
            + [(f"phase_{i}", qs) for i, qs in enumerate(phase_query_sets)]
            + [("evidence", evidence_queries)]
        )

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            futures = {
                pool.submit(self._retrieve_and_enrich, label, queries, spec.topic): label
                for label, queries in all_query_sets
            }
            results: dict[str, list[ControlBundle]] = {}
            for future in concurrent.futures.as_completed(futures):
                label = futures[future]
                try:
                    results[label] = future.result()
                    print(f"[ResearchCoordinator] {label}: {len(results[label])} bundles")
                except Exception as exc:
                    print(f"[ResearchCoordinator] {label} failed: {exc}")
                    results[label] = []

        # Full bundle set = deduplicated union of all results
        seen: set[str] = set()
        full_bundles: list[ControlBundle] = []
        for bundles in results.values():
            for b in bundles:
                if b.chunk_id not in seen:
                    seen.add(b.chunk_id)
                    full_bundles.append(b)

        print(f"[ResearchCoordinator] Total unique bundles: {len(full_bundles)}")

        # Gap analysis (optional — only when existing_document provided)
        augmented: list[AugmentedControlContext] = []
        if self._gap_analyst and spec.existing_document:
            print("[ResearchCoordinator] Running gap analysis on existing document...")
            try:
                augmented = self._gap_analyst.analyze(
                    bundles=full_bundles,
                    topic=spec.topic,
                    doc_type="procedure",
                    existing_document=spec.existing_document,
                )
                print(f"[ResearchCoordinator] Gap analysis: {len(augmented)} contexts")
            except Exception as exc:
                print(f"[ResearchCoordinator] Gap analysis failed: {exc}")

        # Build per-phase research packages
        phase_research = [
            PhaseResearch(
                phase_index=i,
                phase_name=pname,
                bundles=results.get(f"phase_{i}", []),
                augmented=[a for a in augmented
                           if any(kw in spec.topic.lower() or kw in pname.lower()
                                  for kw in (a.gap_type or "").lower().split())],
            )
            for i, pname in enumerate(phase_names)
        ]

        return WorkflowResearch(
            full_bundles=full_bundles,
            front_matter_bundles=results.get("front_matter", []),
            phase_research=phase_research,
            evidence_bundles=results.get("evidence", []),
            augmented_contexts=augmented,
        )

    # ── Policy ─────────────────────────────────────────────────────────────────

    def run_policy(
        self,
        profile: EntityProfile,
        spec: DocumentSpec,
        domain: DomainProfile,
    ) -> WorkflowResearch:
        """Run parallel retrieval for policy sections."""
        query_sets = [
            ("objectives_scope", [
                f"cybersecurity governance policy program {spec.topic}",
                "information security policy objectives confidentiality integrity availability",
                "cybersecurity risk management regulatory compliance requirements",
            ] + domain.extra_retrieval_queries),
            ("elements", [
                f"{spec.topic} cybersecurity policy elements mandatory controls",
                "cybersecurity policy suite roles responsibilities compliance",
                "cybersecurity awareness training incident management vulnerability",
            ]),
            ("compliance", [
                "cybersecurity policy compliance monitoring disciplinary consequences",
                "cybersecurity policy exception process risk acceptance",
            ]),
        ]

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(self._retrieve_and_enrich, label, queries, spec.topic): label
                for label, queries in query_sets
            }
            results: dict[str, list[ControlBundle]] = {}
            for future in concurrent.futures.as_completed(futures):
                label = futures[future]
                try:
                    results[label] = future.result()
                except Exception as exc:
                    print(f"[ResearchCoordinator] Policy {label} failed: {exc}")
                    results[label] = []

        seen: set[str] = set()
        full_bundles: list[ControlBundle] = []
        for bundles in results.values():
            for b in bundles:
                if b.chunk_id not in seen:
                    seen.add(b.chunk_id)
                    full_bundles.append(b)

        return WorkflowResearch(
            full_bundles=full_bundles,
            front_matter_bundles=results.get("objectives_scope", []),
            phase_research=[],
            evidence_bundles=results.get("compliance", []),
            augmented_contexts=[],
        )

    # ── Standard ───────────────────────────────────────────────────────────────

    def run_standard(
        self,
        profile: EntityProfile,
        spec: DocumentSpec,
        domain: DomainProfile,
    ) -> WorkflowResearch:
        """Run parallel retrieval for standard sections."""
        query_sets = [
            ("definitions_scope", [
                f"{spec.topic} cybersecurity standard definitions terminology scope",
                f"{spec.topic} NCA ECC controls regulatory compliance mandatory",
            ] + domain.extra_retrieval_queries),
            ("domains", [
                f"{spec.topic} cybersecurity standard requirements controls implementation",
                f"{spec.topic} security risks threats CIA triad controls",
                f"{spec.topic} technical requirements configuration hardening",
            ]),
            ("compliance", [
                "cybersecurity standard compliance monitoring review update triggers",
                "cybersecurity standard roles responsibilities compliance disciplinary",
            ]),
        ]

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(self._retrieve_and_enrich, label, queries, spec.topic): label
                for label, queries in query_sets
            }
            results: dict[str, list[ControlBundle]] = {}
            for future in concurrent.futures.as_completed(futures):
                label = futures[future]
                try:
                    results[label] = future.result()
                except Exception as exc:
                    print(f"[ResearchCoordinator] Standard {label} failed: {exc}")
                    results[label] = []

        seen: set[str] = set()
        full_bundles: list[ControlBundle] = []
        for bundles in results.values():
            for b in bundles:
                if b.chunk_id not in seen:
                    seen.add(b.chunk_id)
                    full_bundles.append(b)

        return WorkflowResearch(
            full_bundles=full_bundles,
            front_matter_bundles=results.get("definitions_scope", []),
            phase_research=[],
            evidence_bundles=results.get("compliance", []),
            augmented_contexts=[],
        )

    # ── Internal ───────────────────────────────────────────────────────────────

    def _retrieve_and_enrich(
        self,
        label: str,
        queries: list[str],
        topic: str,
    ) -> list[ControlBundle]:
        """Retrieve + rerank + wrap as bundles (no enrichment LLM call).

        Supervisors use _bundle_summary() which only reads chunk_id, control_id,
        framework, title, and statement — implementation_notes/evidence_examples
        are never consumed, so the enrichment LLM call is skipped entirely.
        """
        seen: set[str] = set()
        all_chunks: list[ControlChunk] = []

        for q in queries:
            for c in self._store.retrieve_nca(q, top_k=RETRIEVAL_TOP_K_PER_QUERY // 2).chunks:
                if c.chunk_id not in seen:
                    seen.add(c.chunk_id)
                    all_chunks.append(c)
            for c in self._store.retrieve_nist(q, top_k=RETRIEVAL_TOP_K_PER_QUERY // 3).chunks:
                if c.chunk_id not in seen:
                    seen.add(c.chunk_id)
                    all_chunks.append(c)

        if not all_chunks:
            return []

        rerank_q = f"Cybersecurity {label.replace('_', ' ')}: {topic}"
        scored   = self._rerank(rerank_q, all_chunks, top_k=RERANK_TOP_K)
        chunk_scores = {c.chunk_id: s for s, c in scored}

        # Wrap directly — no LLM enrichment needed for supervisor paths
        return [
            ControlBundle(
                chunk_id=c.chunk_id,
                control_id=c.control_id,
                title=c.title,
                statement=c.statement,
                domain=c.domain,
                framework=c.framework,
                uae_ia_id=getattr(c, "uae_ia_id", None),
                nca_id=getattr(c, "nca_id", None),
                rerank_score=chunk_scores.get(c.chunk_id),
            )
            for _, c in scored
        ]
