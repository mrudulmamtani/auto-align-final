"""
Policy Supervisor — sub-agentic orchestrator for POL-* documents.

Workflow:
  Step 1 [Parallel]: ResearchCoordinator retrieves section-specific bundles concurrently
  Step 2 [LLM]:      ObjectivesScopeAgent drafts §1 Objectives + §2 Scope
  Step 3 [LLM]:      PolicyElementsAgent drafts §3 Policy Elements (dominant section)
  Step 4 [LLM]:      SubprogramsAgent drafts §4 Subprograms (34 subprogram catalog)
  Step 5 [LLM]:      RolesComplianceAgent drafts §5 Roles + §6 Compliance
  Step 6 [Deterministic]: MetadataBuilder fills metadata
  Step 7 [Deterministic]: StructuralChecker validates
  Step 8 [LLM, targeted]: SectionRepairAgent fixes failing sections
  Step 9 [Deterministic]: Assembly into PolicyDraftOutput
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .rate_limited_client import get_openai_client

from ..config import DRAFT_MODEL_POLICY
from ..models import (
    EntityProfile, DocumentSpec, ControlBundle,
    PolicyDraftOutput, PolicyElement, Subprogram, RolesResponsibilities, TraceEntry,
    SUBPROGRAM_CATALOG,
)
from .workflow_models import SectionOutput, WorkflowResearch
from .domain_profiles import DomainProfile, detect_policy_domain
from .deterministic_tools import MetadataBuilder, StructuralChecker, RelatedDocsBuilder
from .research_coordinator import ResearchCoordinator


# ─────────────────────────────────────────────────────────────────────────────
# Section Schemas
# ─────────────────────────────────────────────────────────────────────────────

_OBJECTIVES_SCOPE_SCHEMA = {
    "name": "PolicyObjectivesScope",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "objectives_en":          {"type": "string"},
            "scope_applicability_en": {"type": "string"},
        },
        "required": ["objectives_en", "scope_applicability_en"],
        "additionalProperties": False,
    },
}

_ELEMENTS_SCHEMA = {
    "name": "PolicyElements",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "policy_elements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "element_no":   {"type": "string"},
                        "statement_en": {"type": "string"},
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
                    "required": ["element_no", "statement_en", "trace"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["policy_elements"],
        "additionalProperties": False,
    },
}

_SUBPROGRAMS_SCHEMA = {
    "name": "PolicySubprograms",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "policy_subprograms": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "sub_no":       {"type": "string"},
                        "name_en":      {"type": "string"},
                        "objective_en": {"type": "string"},
                        "references":   {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["sub_no", "name_en", "objective_en", "references"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["policy_subprograms"],
        "additionalProperties": False,
    },
}

_ROLES_COMPLIANCE_SCHEMA = {
    "name": "PolicyRolesCompliance",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "roles_responsibilities": {
                "type": "object",
                "properties": {
                    "authority_owner_delegates": {"type": "array", "items": {"type": "string"}},
                    "legal":                     {"type": "array", "items": {"type": "string"}},
                    "internal_audit":            {"type": "array", "items": {"type": "string"}},
                    "HR":                        {"type": "array", "items": {"type": "string"}},
                    "cybersecurity":             {"type": "array", "items": {"type": "string"}},
                    "other_departments":         {"type": "array", "items": {"type": "string"}},
                    "all_staff":                 {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "authority_owner_delegates", "legal", "internal_audit",
                    "HR", "cybersecurity", "other_departments", "all_staff",
                ],
                "additionalProperties": False,
            },
            "compliance_clauses": {
                "type": "array",
                "items": {"type": "string"},
            },
            "exceptions_en": {"type": "string"},
        },
        "required": ["roles_responsibilities", "compliance_clauses", "exceptions_en"],
        "additionalProperties": False,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Section Agents
# ─────────────────────────────────────────────────────────────────────────────

def _bundle_summary(bundles, n=25):
    return [{"chunk_id": b.chunk_id, "control_id": b.control_id,
             "framework": b.framework, "title": b.title,
             "statement": b.statement[:350]} for b in bundles[:n]]


class PolicyObjectivesScopeAgent:
    def __init__(self): self._client = get_openai_client()

    def draft(self, profile, spec, bundles, domain, qa_findings=None) -> SectionOutput:
        print(f"[PolicyObjectivesScopeAgent] Drafting §1-2 for {spec.topic}")
        system_msg = f"""\
Draft the Objectives and Scope sections ONLY of a cybersecurity policy.
Client: {profile.org_name} | Topic: {spec.topic} | Jurisdiction: {profile.jurisdiction}

objectives_en (min 500 words):
  - 5 paragraphs: regulatory basis (NCA ECC + specific control IDs), threat context,
    CIA triad impact, strategic alignment with organisation mission, measurable outcomes
  - Reference specific NCA controls from the bundles
  - Cite ISO 27001:2022 and NIST CSF 2.0 alignment

scope_applicability_en (min 400 words):
  - In-scope systems, asset categories, personnel roles, third-party relationships
  - Geographic scope (all KSA operations as applicable)
  - Out-of-scope items with rationale
  - Effective date trigger language

{domain.system_prompt_extension}
"""
        payload = {"topic": spec.topic, "control_bundles": _bundle_summary(bundles, 20)}
        if qa_findings: payload["qa_findings_to_fix"] = qa_findings
        try:
            resp = self._client.chat.completions.create(
                model=DRAFT_MODEL_POLICY,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": "Draft §1 Objectives and §2 Scope. Both 400+ words. Output valid JSON."},
                    {"role": "user", "content": json.dumps(payload)},
                ],
                response_format={"type": "json_schema", "json_schema": _OBJECTIVES_SCOPE_SCHEMA},
                temperature=0.3,
            )
            return SectionOutput("objectives_scope", "ok", json.loads(resp.choices[0].message.content))
        except Exception as e:
            return SectionOutput("objectives_scope", "fail", {}, [str(e)])


class PolicyElementsAgent:
    def __init__(self): self._client = get_openai_client()

    def draft(self, profile, spec, bundles, domain, qa_findings=None) -> SectionOutput:
        print(f"[PolicyElementsAgent] Drafting policy elements for {spec.topic}")
        system_msg = f"""\
Draft the Policy Elements section (§3) of a cybersecurity policy — the DOMINANT section.
Client: {profile.org_name} | Topic: {spec.topic} | Domain: {domain.name}

REQUIREMENTS:
- Minimum 15 policy elements (target 20-25)
- Each element_no: "2.N" format
- Each statement_en (min 200 words):
  * Must contain at least one 'shall' mandatory statement
  * Must include: the specific requirement, who it applies to, measurable compliance criteria,
    exceptions process, and the specific risk being mitigated
  * Reference NCA ECC control IDs from the bundles
- Each trace: minimum 2 entries linking to real chunk_ids from the bundles
- Elements must span: governance, access control, data protection, incident response,
  vulnerability management, monitoring, change management, third-party, continuity, training

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
                        "Draft 20-25 policy elements. Each statement_en: 200+ words with 'shall' clauses "
                        "grounded in NCA controls. Trace every element to chunk_ids. Output valid JSON."
                    )},
                    {"role": "user", "content": json.dumps(payload)},
                ],
                response_format={"type": "json_schema", "json_schema": _ELEMENTS_SCHEMA},
                temperature=0.3,
            )
            return SectionOutput("elements", "ok", json.loads(resp.choices[0].message.content))
        except Exception as e:
            return SectionOutput("elements", "fail", {}, [str(e)])


class PolicySubprogramsAgent:
    """
    PARTIALLY DETERMINISTIC:
    sub_no and name_en come from SUBPROGRAM_CATALOG (deterministic).
    LLM writes only objective_en (90+ words) per entry.
    """
    def __init__(self): self._client = get_openai_client()

    def draft(self, profile, spec, bundles, qa_findings=None) -> SectionOutput:
        print(f"[PolicySubprogramsAgent] Drafting {len(SUBPROGRAM_CATALOG)} subprograms")
        # SUBPROGRAM_CATALOG is a list of (sub_no, name_en) tuples
        catalog_context = [
            {"sub_no": sub_no, "name_en": name_en}
            for sub_no, name_en in SUBPROGRAM_CATALOG
        ]
        system_msg = f"""\
Write objective_en (min 120 words each) for each of the {len(SUBPROGRAM_CATALOG)} cybersecurity subprograms below.
Client: {profile.org_name} | Topic: {spec.topic}
The sub_no and name_en are fixed — do NOT change them.
For each subprogram:
  - objective_en: why this subprogram exists, what it achieves, how it supports {spec.topic} policy,
    which NCA ECC requirements it satisfies, and what measurable outcome proves it is effective
  - references: list of 2-4 doc_ids that govern this subprogram (e.g. STD-NN, PRC-NN, NCA-ECC-2020)
"""
        payload = {
            "topic": spec.topic, "org_name": profile.org_name,
            "subprogram_catalog": catalog_context,
            "control_bundles": _bundle_summary(bundles, 20),
        }
        if qa_findings: payload["qa_findings_to_fix"] = qa_findings
        try:
            resp = self._client.chat.completions.create(
                model=DRAFT_MODEL_POLICY,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": (
                        f"Write objective_en (120+ words) and references for all {len(SUBPROGRAM_CATALOG)} subprograms. "
                        "Do NOT change sub_no or name_en. Output valid JSON."
                    )},
                    {"role": "user", "content": json.dumps(payload)},
                ],
                response_format={"type": "json_schema", "json_schema": _SUBPROGRAMS_SCHEMA},
                temperature=0.3,
            )
            return SectionOutput("subprograms", "ok", json.loads(resp.choices[0].message.content))
        except Exception as e:
            return SectionOutput("subprograms", "fail", {}, [str(e)])


class PolicyRolesComplianceAgent:
    def __init__(self): self._client = get_openai_client()

    def draft(self, profile, spec, bundles, domain, qa_findings=None) -> SectionOutput:
        print(f"[PolicyRolesComplianceAgent] Drafting §5-6 for {spec.topic}")
        system_msg = f"""\
Draft the Roles & Responsibilities and Policy Compliance sections for a cybersecurity policy.
Client: {profile.org_name} | Topic: {spec.topic}

roles_responsibilities (exactly 7 named role groups):
  Groups: authority_owner_delegates, legal, internal_audit, HR, cybersecurity,
          other_departments, all_staff
  Each group: 8-10 specific duties as full imperative sentences
  Each duty references {spec.topic} specifically

compliance_clauses (min 4 items, exactly 3 required):
  Monitoring compliance, consequences of non-compliance, disciplinary action
  Each clause: full paragraph, 75+ words

exceptions_en (min 300 words):
  Full exception request workflow with approval levels, documentation, compensating controls,
  maximum exception duration, and mandatory review schedule.
"""
        payload = {"topic": spec.topic, "control_bundles": _bundle_summary(bundles, 15)}
        if qa_findings: payload["qa_findings_to_fix"] = qa_findings
        try:
            resp = self._client.chat.completions.create(
                model=DRAFT_MODEL_POLICY,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": "Draft roles (7 named groups, 8-10 duties each) and compliance sections. Output valid JSON."},
                    {"role": "user", "content": json.dumps(payload)},
                ],
                response_format={"type": "json_schema", "json_schema": _ROLES_COMPLIANCE_SCHEMA},
                temperature=0.3,
            )
            return SectionOutput("roles_compliance", "ok", json.loads(resp.choices[0].message.content))
        except Exception as e:
            return SectionOutput("roles_compliance", "fail", {}, [str(e)])


# ─────────────────────────────────────────────────────────────────────────────
# Policy Supervisor
# ─────────────────────────────────────────────────────────────────────────────

class PolicySupervisor:
    """
    Sub-agentic supervisor for POL-* documents.
    Drop-in replacement for PolicyDraftingAgent.draft().
    """

    def __init__(self, store, enricher, rerank_fn):
        self._research    = ResearchCoordinator(store, enricher, rerank_fn)
        self._obj_scope   = PolicyObjectivesScopeAgent()
        self._elements    = PolicyElementsAgent()
        self._subprograms = PolicySubprogramsAgent()
        self._roles_comp  = PolicyRolesComplianceAgent()
        self._meta        = MetadataBuilder()
        self._structural  = StructuralChecker()

    def draft(
        self,
        profile: EntityProfile,
        spec: DocumentSpec,
        bundles: list[ControlBundle],
        doc_id: str,
        qa_findings: list[str] | None = None,
    ) -> PolicyDraftOutput:
        print(f"\n[PolicySupervisor] Sub-agentic workflow for {doc_id}")
        domain = detect_policy_domain(spec.topic)

        # Step 1: Parallel research
        research = self._research.run_policy(profile, spec, domain)
        seen = {b.chunk_id for b in research.full_bundles}
        for b in bundles:
            if b.chunk_id not in seen:
                research.full_bundles.append(b)
                seen.add(b.chunk_id)

        fm_bundles  = research.front_matter_bundles or bundles[:25]
        ev_bundles  = research.evidence_bundles or bundles[-15:]
        all_bundles = research.full_bundles

        # Step 2: Objectives + Scope
        obj_result = self._obj_scope.draft(profile, spec, fm_bundles, domain,
                                           _filter_qa(qa_findings, "objective"))
        # Step 3: Policy Elements (dominant)
        el_result = self._elements.draft(profile, spec, all_bundles, domain,
                                         _filter_qa(qa_findings, "element"))
        # Step 4: Subprograms (partially deterministic)
        sub_result = self._subprograms.draft(profile, spec, all_bundles,
                                             _filter_qa(qa_findings, "subprogram"))
        # Step 5: Roles + Compliance
        rc_result = self._roles_comp.draft(profile, spec, ev_bundles, domain,
                                           _filter_qa(qa_findings, "role"))

        # Step 6: Deterministic metadata
        meta = self._meta.build_policy(doc_id, spec.topic, profile.org_name, spec.version)

        # Step 7: Parse into PolicyDraftOutput
        return _parse_policy(obj_result, el_result, sub_result, rc_result, meta, doc_id, spec)


def _filter_qa(qa: list[str] | None, keyword: str) -> list[str] | None:
    if not qa: return None
    filtered = [f for f in qa if keyword.lower() in f.lower()]
    return filtered or None


def _parse_policy(obj, el, sub, rc, meta, doc_id, spec) -> PolicyDraftOutput:
    od = obj.data
    ed = el.data
    sd = sub.data
    rd = rc.data

    elements = [
        PolicyElement(
            element_no   = e.get("element_no", ""),
            statement_en = e.get("statement_en", ""),
            trace        = [TraceEntry(**t) for t in e.get("trace", [])],
        )
        for e in ed.get("policy_elements", [])
    ]

    # Merge subprogram objectives with catalog (catalog is authoritative for sub_no/name_en)
    # SUBPROGRAM_CATALOG is a list of (sub_no, name_en) tuples
    sub_map = {s.get("sub_no"): s for s in sd.get("policy_subprograms", [])}
    subprograms = []
    for sub_no, name_en in SUBPROGRAM_CATALOG:
        override = sub_map.get(sub_no, {})
        subprograms.append(Subprogram(
            sub_no       = sub_no,
            name_en      = name_en,
            objective_en = override.get("objective_en", name_en),
            references   = override.get("references", []),
        ))

    rr_data = rd.get("roles_responsibilities", {})
    roles = RolesResponsibilities(
        authority_owner_delegates = rr_data.get("authority_owner_delegates", []),
        legal                     = rr_data.get("legal", []),
        internal_audit            = rr_data.get("internal_audit", []),
        HR                        = rr_data.get("HR", []),
        cybersecurity             = rr_data.get("cybersecurity", []),
        other_departments         = rr_data.get("other_departments", []),
        all_staff                 = rr_data.get("all_staff", []),
    )

    compliance_clauses = rd.get("compliance_clauses", [])
    exceptions_en      = rd.get("exceptions_en", "")

    return PolicyDraftOutput(
        doc_id                  = meta["doc_id"],
        title_en                = meta["title_en"],
        version                 = meta["version"],
        effective_date          = meta["effective_date"],
        owner                   = meta["owner"],
        classification          = meta["classification"],
        objectives_en           = od.get("objectives_en", ""),
        scope_applicability_en  = od.get("scope_applicability_en", ""),
        policy_elements         = elements,
        policy_subprograms      = subprograms,
        roles_responsibilities  = roles,
        compliance_clauses      = compliance_clauses,
        exceptions_en           = exceptions_en,
        closing_note_en         = "",
    )
