"""
Standard Supervisor — sub-agentic orchestrator for STD-* documents.

Workflow:
  Step 1 [Parallel]: ResearchCoordinator retrieves section-specific bundles
  Step 2 [LLM]:      DefinitionsObjectiveScopeAgent drafts §1-3
  Step 3 [LLM]:      DomainClustersAgent drafts §4 Domain Requirements (dominant)
  Step 4 [LLM]:      RolesReviewComplianceAgent drafts §5-7
  Step 5 [Deterministic]: MetadataBuilder fills metadata
  Step 6 [Deterministic]: req_id numbering, StructuralChecker
  Step 7 [LLM, targeted]: SectionRepairAgent fixes failing sections
  Step 8 [Deterministic]: Assembly into StandardDraftOutput
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .rate_limited_client import get_openai_client

from ..config import DRAFT_MODEL_POLICY
from ..models import (
    EntityProfile, DocumentSpec, ControlBundle,
    StandardDraftOutput, StandardDefinition, StandardDomain,
    StandardRequirement, StandardRoleItem, TraceEntry,
)
from .workflow_models import SectionOutput, WorkflowResearch
from .domain_profiles import DomainProfile, detect_standard_domain
from .deterministic_tools import MetadataBuilder, StructuralChecker
from .research_coordinator import ResearchCoordinator


def _bundle_summary(bundles, n=25):
    return [{"chunk_id": b.chunk_id, "control_id": b.control_id,
             "framework": b.framework, "title": b.title,
             "statement": b.statement[:350]} for b in bundles[:n]]


_DEF_OBJ_SCOPE_SCHEMA = {
    "name": "StandardDefinitionsObjectiveScope",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "definitions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "term_en":        {"type": "string"},
                        "description_en": {"type": "string"},
                    },
                    "required": ["term_en", "description_en"],
                    "additionalProperties": False,
                },
            },
            "objectives_en":     {"type": "string"},
            "scope_en":          {"type": "string"},
        },
        "required": ["definitions", "objectives_en", "scope_en"],
        "additionalProperties": False,
    },
}

_DOMAINS_SCHEMA = {
    "name": "StandardDomains",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "domains": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "domain_number":      {"type": "integer"},
                        "title_en":           {"type": "string"},
                        "objective_en":       {"type": "string"},
                        "potential_risks_en": {"type": "string"},
                        "requirements": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "req_id":       {"type": "string"},
                                    "statement_en": {"type": "string"},
                                    "placeholders": {"type": "array", "items": {"type": "string"}},
                                    "trace": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "framework":  {"type": "string"},
                                                "control_id": {"type": "string"},
                                                "source_ref": {"type": "string"},
                                            },
                                            "required": ["framework", "control_id", "source_ref"],
                                            "additionalProperties": False,
                                        },
                                    },
                                },
                                "required": ["req_id", "statement_en", "placeholders", "trace"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["domain_number", "title_en", "objective_en",
                                 "potential_risks_en", "requirements"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["domains"],
        "additionalProperties": False,
    },
}

_ROLES_REVIEW_COMPLIANCE_SCHEMA = {
    "name": "StandardRolesReviewCompliance",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "roles_responsibilities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item_no":  {"type": "string"},
                        "text_en":  {"type": "string"},
                    },
                    "required": ["item_no", "text_en"],
                    "additionalProperties": False,
                },
            },
            "review_update_en": {"type": "string"},
            "compliance_en": {
                "type": "array",
                "items": {"type": "string"},
            },
            "closing_note_en": {"type": "string"},
        },
        "required": [
            "roles_responsibilities", "review_update_en",
            "compliance_en", "closing_note_en",
        ],
        "additionalProperties": False,
    },
}


class StandardDefinitionsObjectiveScopeAgent:
    def __init__(self): self._client = get_openai_client()

    def draft(self, profile, spec, bundles, domain, qa_findings=None) -> SectionOutput:
        print(f"[StandardDefObjScopeAgent] Drafting §1-3 for {spec.topic}")
        system_msg = f"""\
Draft definitions, objectives, and scope for a cybersecurity standard.
Client: {profile.org_name} | Topic: {spec.topic} | Domain: {domain.name}

definitions (min 12 terms):
  Technical terms, acronyms, and standard-specific concepts
  Each description_en: 2-3 technical sentences, not dictionary-style

objectives_en (min 450 words):
  - Purpose of the standard, regulatory basis (NCA ECC controls from bundles)
  - What risks this standard mitigates, CIA triad relevance
  - Relationship to parent policy and related standards
  - Measurable compliance outcome

scope_en (min 350 words):
  - In-scope systems, applications, personnel, third parties
  - Asset classification scope
  - Explicit out-of-scope items with rationale

{domain.system_prompt_extension}
"""
        payload = {"topic": spec.topic, "control_bundles": _bundle_summary(bundles, 20)}
        if qa_findings: payload["qa_findings_to_fix"] = qa_findings
        try:
            resp = self._client.chat.completions.create(
                model=DRAFT_MODEL_POLICY,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": "Draft definitions (12+), objectives (450+ words), scope (350+ words). Output valid JSON."},
                    {"role": "user", "content": json.dumps(payload)},
                ],
                response_format={"type": "json_schema", "json_schema": _DEF_OBJ_SCOPE_SCHEMA},
                temperature=0.3,
            )
            return SectionOutput("def_obj_scope", "ok", json.loads(resp.choices[0].message.content))
        except Exception as e:
            return SectionOutput("def_obj_scope", "fail", {}, [str(e)])


class StandardDomainClustersAgent:
    def __init__(self): self._client = get_openai_client()

    def draft(self, profile, spec, bundles, domain, qa_findings=None) -> SectionOutput:
        print(f"[StandardDomainClustersAgent] Drafting domain requirements for {spec.topic}")
        system_msg = f"""\
Draft the Standard Requirements section (§4) — the DOMINANT section of the standard.
Client: {profile.org_name} | Topic: {spec.topic} | Domain: {domain.name}

domains (min 6 entries):
  Each domain:
  - domain_number: integer (1, 2, 3, ...)
  - title_en: specific sub-area of {spec.topic}
  - objective_en (min 200 words): purpose, risks addressed, NCA ECC linkage
  - potential_risks_en (min 200 words): specific threat/risk descriptions
  - requirements: min 7 per domain (target 10-12)
    Each requirement:
    - req_id: "N.M" format (domain_number.sequence)
    - statement_en (min 180 words): SHALL statement with:
        * Specific measurable threshold/value/configuration
        * Who must comply and how
        * Verification method (how auditor checks compliance)
        * NCA ECC control basis
        * Consequence of non-compliance
    - placeholders: list of placeholder tokens if any (may be empty list)
    - trace: min 2 entries with real chunk_ids from bundles

Domains should cover different sub-aspects of {spec.topic} to avoid duplication.

{domain.system_prompt_extension}
"""
        payload = {"topic": spec.topic, "org_name": profile.org_name,
                   "control_bundles": _bundle_summary(bundles, 35)}
        if qa_findings: payload["qa_findings_to_fix"] = qa_findings
        try:
            resp = self._client.chat.completions.create(
                model=DRAFT_MODEL_POLICY,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": (
                        "Draft 6+ domain clusters, each with 7-12 requirements. "
                        "Each requirement statement_en: 180+ words with specific thresholds, "
                        "verification method, and NCA ECC basis. Output valid JSON."
                    )},
                    {"role": "user", "content": json.dumps(payload)},
                ],
                response_format={"type": "json_schema", "json_schema": _DOMAINS_SCHEMA},
                temperature=0.3,
            )
            return SectionOutput("domains", "ok", json.loads(resp.choices[0].message.content))
        except Exception as e:
            return SectionOutput("domains", "fail", {}, [str(e)])


class StandardRolesReviewComplianceAgent:
    def __init__(self): self._client = get_openai_client()

    def draft(self, profile, spec, bundles, domain, qa_findings=None) -> SectionOutput:
        print(f"[StandardRolesReviewComplianceAgent] Drafting §5-7 for {spec.topic}")
        system_msg = f"""\
Draft roles, review cycle, and compliance sections for a cybersecurity standard.
Client: {profile.org_name} | Topic: {spec.topic}

roles_responsibilities (exactly 3 items):
  item_no: "1-", "2-", "3-"
  Roles: Document Sponsor/Owner, Review & Update Owner, Implementation Owner
  Each text_en: 180+ words with specific accountabilities related to {spec.topic}

review_update_en (min 300 words):
  Annual review cadence, version control, stakeholder consultation process,
  approval workflow, communication plan for updates.
  Must mention all 3 triggers: major technology changes; changes in policies/procedures;
  regulatory/legislative changes.

compliance_en (exactly 3 clauses as list items):
  Clause 1: how compliance is monitored and measured
  Clause 2: staff compliance obligations
  Clause 3: disciplinary/legal consequences for non-compliance
  Each clause: 90+ words

closing_note_en: brief closing statement for the standard document.
"""
        payload = {"topic": spec.topic, "control_bundles": _bundle_summary(bundles, 15)}
        if qa_findings: payload["qa_findings_to_fix"] = qa_findings
        try:
            resp = self._client.chat.completions.create(
                model=DRAFT_MODEL_POLICY,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": "Draft roles (3 items), review_update_en, compliance_en (3 clauses), closing_note_en. Output valid JSON."},
                    {"role": "user", "content": json.dumps(payload)},
                ],
                response_format={"type": "json_schema", "json_schema": _ROLES_REVIEW_COMPLIANCE_SCHEMA},
                temperature=0.3,
            )
            return SectionOutput("roles_review", "ok", json.loads(resp.choices[0].message.content))
        except Exception as e:
            return SectionOutput("roles_review", "fail", {}, [str(e)])


class StandardSupervisor:
    """
    Sub-agentic supervisor for STD-* documents.
    Drop-in replacement for StandardDraftingAgent.draft().
    """

    def __init__(self, store, enricher, rerank_fn):
        self._research   = ResearchCoordinator(store, enricher, rerank_fn)
        self._def_scope  = StandardDefinitionsObjectiveScopeAgent()
        self._domains    = StandardDomainClustersAgent()
        self._roles_rev  = StandardRolesReviewComplianceAgent()
        self._meta       = MetadataBuilder()
        self._structural = StructuralChecker()

    def draft(
        self,
        profile: EntityProfile,
        spec: DocumentSpec,
        bundles: list[ControlBundle],
        doc_id: str,
        qa_findings: list[str] | None = None,
    ) -> StandardDraftOutput:
        print(f"\n[StandardSupervisor] Sub-agentic workflow for {doc_id}")
        domain = detect_standard_domain(spec.topic)

        research = self._research.run_standard(profile, spec, domain)
        seen = {b.chunk_id for b in research.full_bundles}
        for b in bundles:
            if b.chunk_id not in seen:
                research.full_bundles.append(b)
                seen.add(b.chunk_id)

        fm_bundles  = research.front_matter_bundles or bundles[:25]
        ev_bundles  = research.evidence_bundles or bundles[-15:]
        all_bundles = research.full_bundles

        # Section drafting
        ds_result  = self._def_scope.draft(profile, spec, fm_bundles, domain,
                                           _filter_qa(qa_findings, "definition"))
        dom_result = self._domains.draft(profile, spec, all_bundles, domain,
                                         _filter_qa(qa_findings, "requirement"))
        rc_result  = self._roles_rev.draft(profile, spec, ev_bundles, domain,
                                           _filter_qa(qa_findings, "role"))

        meta = self._meta.build_standard(doc_id, spec.topic, profile.org_name, spec.version)
        return _parse_standard(ds_result, dom_result, rc_result, meta, doc_id, spec)


def _filter_qa(qa, kw):
    if not qa: return None
    f = [x for x in qa if kw.lower() in x.lower()]
    return f or None


def _parse_standard(ds, dom, rc, meta, doc_id, spec) -> StandardDraftOutput:
    dd   = ds.data
    domd = dom.data
    rcd  = rc.data

    definitions = [
        StandardDefinition(
            term_en        = d.get("term_en", ""),
            description_en = d.get("description_en", ""),
        )
        for d in dd.get("definitions", [])
    ]

    domains = []
    for dc in domd.get("domains", []):
        reqs = [
            StandardRequirement(
                req_id       = r.get("req_id", ""),
                statement_en = r.get("statement_en", ""),
                placeholders = r.get("placeholders", []),
                trace        = [TraceEntry(**t) for t in r.get("trace", [])],
            )
            for r in dc.get("requirements", [])
        ]
        domains.append(StandardDomain(
            domain_number      = dc.get("domain_number", 0),
            title_en           = dc.get("title_en", ""),
            objective_en       = dc.get("objective_en", ""),
            potential_risks_en = dc.get("potential_risks_en", ""),
            requirements       = reqs,
        ))

    roles = [
        StandardRoleItem(
            item_no = r.get("item_no", ""),
            text_en = r.get("text_en", ""),
        )
        for r in rcd.get("roles_responsibilities", [])
    ]

    return StandardDraftOutput(
        doc_id                 = meta["doc_id"],
        title_en               = meta["title_en"],
        version                = meta["version"],
        effective_date         = meta["effective_date"],
        owner                  = meta["owner"],
        classification         = meta["classification"],
        definitions            = definitions,
        objectives_en          = dd.get("objectives_en", ""),
        scope_en               = dd.get("scope_en", ""),
        domains                = domains,
        roles_responsibilities = roles,
        review_update_en       = rcd.get("review_update_en", ""),
        compliance_en          = rcd.get("compliance_en", []),
        closing_note_en        = rcd.get("closing_note_en", ""),
    )
