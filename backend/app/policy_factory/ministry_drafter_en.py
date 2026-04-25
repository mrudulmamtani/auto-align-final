"""
Ministry Drafter (English) — generates English-language ministry
policy/standard/procedure documents using GPT-4o structured outputs.

Mirrors ministry_drafter.py in structure; fields go into the same
MinistryPolicyDraft / MinistryStandardDraft / MinistryProcedureDraft
models — title_en and all *_ar fields are filled with English text
(the models accept English in _ar fields; they are "primary language" fields).
"""
from __future__ import annotations
import json
from typing import Any

from openai import OpenAI

from .config import OPENAI_API_KEY, DRAFT_MODEL_POLICY as _MODEL
from .ministry_models import (
    MinistryMeta, DefinitionEntry, ApprovalStage, VersionRow,
    PolicyClause, PolicyRelatedDoc,
    MinistryPolicyDraft,
    StandardClause, StandardDomainCluster,
    MinistryStandardDraft,
    ProcedureStep, ProcedurePhase, ProcedureRoleItem,
    MinistryProcedureDraft,
)

_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def _chat_json(system: str, user: str, model: str = _MODEL) -> Any:
    resp = _get_client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        temperature=0.3,
        max_tokens=8000,
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content or "{}")


_SYSTEM = """You are an expert government cybersecurity document author.
You produce ministry-grade cybersecurity policies, standards, and procedures
for a Gulf-region government ministry.

Rules:
- Formal, direct, authoritative government tone
- Mandatory language: "must" / "must not" (never "shall" or "should" for mandatory)
- Guidance language: "should" / "is recommended"
- No marketing language, no operational procedures inside policy documents
- All output must be valid JSON
"""

# ══════════════════════════════════════════════════════════════════════════════
# POLICY
# ══════════════════════════════════════════════════════════════════════════════

def draft_policy_en(
    doc_id: str,
    name_en: str,
    dependency_context: str = "",
    org_name: str = "the Ministry",
) -> MinistryPolicyDraft:

    dep_block = f"\n## Related Document Context (for consistency):\n{dependency_context}" if dependency_context else ""

    system = _SYSTEM + "\nYou are drafting a POLICY document — the 'WHY' governing document. Section 4 (policy clauses) must be the dominant section with 12-20 mandatory clauses."

    user = f"""Draft a complete ministry cybersecurity policy with these details:
- Document ID: {doc_id}
- Title: {name_en}
- Organisation: {org_name}
{dep_block}

Return valid JSON with exactly these keys:
{{
  "definitions": [
    {{"term_ar": "Term Name", "term_en": "Term Name", "definition_ar": "Definition text."}}
  ],
  "objective_ar": "2-paragraph objective...",
  "scope_ar": "1-2 paragraph scope...",
  "policy_clauses": [
    {{"clause_no": 1, "text_ar": "The Ministry must...", "sub_bullets_ar": []}}
  ],
  "roles_ar": "Brief roles and responsibilities paragraph...",
  "related_docs": [
    {{"title_ar": "Document Title", "title_en": "Document Title", "ref_type": "National Framework"}}
  ],
  "effective_date_ar": "This policy comes into effect on the date of its approval.",
  "review_ar": "This policy must be reviewed annually...",
  "approval_stages": [
    {{"stage_ar": "Prepared by", "role_ar": "Director, Cybersecurity Department", "name_ar": "[Name]", "date_ar": "[Date]"}},
    {{"stage_ar": "Reviewed by", "role_ar": "Deputy Minister for Technical Affairs", "name_ar": "[Name]", "date_ar": "[Date]"}},
    {{"stage_ar": "Approved by", "role_ar": "Minister", "name_ar": "[Name]", "date_ar": "[Date]"}}
  ],
  "version_rows": [
    {{"version": "1.0", "update_type_ar": "Initial Release", "summary_ar": "Initial version of the document.", "updated_by_ar": "Cybersecurity Department", "approval_date": ""}}
  ],
  "control_mapping": {{}}
}}

Requirements:
- definitions: 6-10 terms (the Ministry, the Minister, ministry personnel, the policy + domain terms)
- policy_clauses: 12-20 clauses, each starting with "The Ministry must" or "The Ministry must not"
- Section 4 must be the dominant substantive section
- professional, government-policy prose throughout
"""

    raw = _chat_json(system, user)

    meta = MinistryMeta(
        doc_id=doc_id, doc_type="policy",
        title_ar=name_en, title_en=name_en,
        reference_number=doc_id,
        classification="Confidential — Internal Use Only",
        owner="Cybersecurity Department",
    )
    return MinistryPolicyDraft(
        meta=meta,
        definitions=[DefinitionEntry(**d) for d in raw.get("definitions", [])],
        objective_ar=raw.get("objective_ar", ""),
        scope_ar=raw.get("scope_ar", ""),
        policy_clauses=[PolicyClause(**c) for c in raw.get("policy_clauses", [])],
        roles_ar=raw.get("roles_ar", ""),
        related_docs=[PolicyRelatedDoc(**r) for r in raw.get("related_docs", [])],
        effective_date_ar=raw.get("effective_date_ar", ""),
        review_ar=raw.get("review_ar", ""),
        approval_stages=[ApprovalStage(**a) for a in raw.get("approval_stages", [])],
        version_rows=[VersionRow(**v) for v in raw.get("version_rows", [])],
        control_mapping=raw.get("control_mapping", {}),
        dependency_summary=dependency_context[:500] if dependency_context else "",
    )


# ══════════════════════════════════════════════════════════════════════════════
# STANDARD
# ══════════════════════════════════════════════════════════════════════════════

def draft_standard_en(
    doc_id: str,
    name_en: str,
    dependency_context: str = "",
    org_name: str = "the Ministry",
) -> MinistryStandardDraft:

    dep_block = f"\n## Related Document Context:\n{dependency_context}" if dependency_context else ""

    system = _SYSTEM + "\nYou are drafting a STANDARD document — the 'WHAT and WHO'. Section 4 must have 3-4 domain clusters, each with objective, potential risks, and 5-8 operative clauses numbered 4.x.y."

    user = f"""Draft a complete ministry cybersecurity standard with these details:
- Document ID: {doc_id}
- Title: {name_en}
- Organisation: {org_name}
{dep_block}

Return valid JSON with exactly these keys:
{{
  "notice_ar": "This document is the exclusive property of the Ministry. Reproduction or disclosure without prior written consent of the Cybersecurity Department is prohibited.",
  "notice_en": "This document is the exclusive property of the Ministry. Reproduction or disclosure without prior written consent of the Cybersecurity Department is prohibited.",
  "definitions": [
    {{"term_ar": "Term", "term_en": "Term", "definition_ar": "Operational definition..."}}
  ],
  "objective_ar": "2-4 paragraphs explaining what this standard regulates, why it exists, what risks it reduces...",
  "scope_intro_ar": "This standard applies to...",
  "scope_systems_ar": ["All information systems...", "Cloud-hosted platforms..."],
  "scope_roles_ar": ["System owners...", "All technical staff..."],
  "scope_processes_ar": ["System provisioning...", "Change management..."],
  "scope_persons_ar": ["All ministry employees...", "Contractors and third parties..."],
  "domain_clusters": [
    {{
      "cluster_id": "4.1",
      "title_ar": "Governance and Management of [domain]",
      "objective_ar": "To establish...",
      "potential_risks_ar": "Failure to comply may result in...",
      "clauses": [
        {{"clause_id": "4.1.1", "text_ar": "The Ministry must...", "guidance_ar": "", "is_mandatory": true}}
      ]
    }}
  ],
  "exceptions_ar": "Any exception to this standard must be documented with justification, risk assessment, compensating controls, and approval by the Cybersecurity Department. Exceptions are time-bound and subject to periodic review.",
  "roles_responsibilities": {{
    "Cybersecurity Department": "Owns this standard; monitors compliance; approves exceptions.",
    "System Owners": "Implement and maintain controls; report deviations.",
    "Internal Audit": "Reviews compliance; reports findings to senior management."
  }},
  "update_review_ar": "This standard must be reviewed annually, or upon material changes to the regulatory environment, significant security incidents, or major technology changes.",
  "compliance_ar": "Compliance with this standard is mandatory. Non-compliance will be subject to corrective action and escalation per the Ministry's disciplinary framework.",
  "version_rows": [{{"version": "1.0", "update_type_ar": "Initial Release", "summary_ar": "Initial version.", "updated_by_ar": "Cybersecurity Department", "approval_date": ""}}],
  "approval_stages": [
    {{"stage_ar": "Prepared by", "role_ar": "Director, Cybersecurity Department", "name_ar": "[Name]", "date_ar": "[Date]"}},
    {{"stage_ar": "Reviewed by", "role_ar": "Deputy Minister for Technical Affairs", "name_ar": "[Name]", "date_ar": "[Date]"}},
    {{"stage_ar": "Approved by", "role_ar": "Minister", "name_ar": "[Name]", "date_ar": "[Date]"}}
  ]
}}

Requirements:
- definitions: 8-15 operational technical terms
- domain_clusters: 3-4 clusters, each with 5-8 numbered clauses (4.1.1, 4.1.2...)
- mandatory clauses start with "The Ministry must" / "must not"
- guidance clauses start with "The Ministry should"
"""

    raw = _chat_json(system, user)
    meta = MinistryMeta(
        doc_id=doc_id, doc_type="standard",
        title_ar=name_en, title_en=name_en,
        reference_number=doc_id,
        classification="Confidential — Internal Use Only",
        owner="Cybersecurity Department",
    )
    clusters = []
    for c in raw.get("domain_clusters", []):
        clusters.append(StandardDomainCluster(
            cluster_id=c.get("cluster_id", "4.1"),
            title_ar=c.get("title_ar", ""),
            objective_ar=c.get("objective_ar", ""),
            potential_risks_ar=c.get("potential_risks_ar", ""),
            clauses=[StandardClause(**cl) for cl in c.get("clauses", [])],
        ))
    return MinistryStandardDraft(
        meta=meta,
        notice_ar=raw.get("notice_ar", ""),
        notice_en=raw.get("notice_en", ""),
        definitions=[DefinitionEntry(**d) for d in raw.get("definitions", [])],
        objective_ar=raw.get("objective_ar", ""),
        scope_intro_ar=raw.get("scope_intro_ar", ""),
        scope_systems_ar=raw.get("scope_systems_ar", []),
        scope_roles_ar=raw.get("scope_roles_ar", []),
        scope_processes_ar=raw.get("scope_processes_ar", []),
        scope_persons_ar=raw.get("scope_persons_ar", []),
        domain_clusters=clusters,
        exceptions_ar=raw.get("exceptions_ar", ""),
        roles_responsibilities=raw.get("roles_responsibilities", {}),
        update_review_ar=raw.get("update_review_ar", ""),
        compliance_ar=raw.get("compliance_ar", ""),
        version_rows=[VersionRow(**v) for v in raw.get("version_rows", [])],
        approval_stages=[ApprovalStage(**a) for a in raw.get("approval_stages", [])],
        dependency_summary=dependency_context[:500] if dependency_context else "",
    )


# ══════════════════════════════════════════════════════════════════════════════
# PROCEDURE
# ══════════════════════════════════════════════════════════════════════════════

def draft_procedure_en(
    doc_id: str,
    name_en: str,
    dependency_context: str = "",
    org_name: str = "the Ministry",
    parent_policy_id: str = "",
    parent_standard_id: str = "",
) -> MinistryProcedureDraft:

    dep_block = f"\n## Related Document Context:\n{dependency_context}" if dependency_context else ""

    system = _SYSTEM + "\nYou are drafting a PROCEDURE document — the 'HOW'. Section 7 (detailed steps) is the dominant section: 3-5 phases, each with 4-7 steps. Each step must specify actor, action, system/tool, output, evidence, and timing."

    user = f"""Draft a complete ministry cybersecurity procedure with these details:
- Document ID: {doc_id}
- Title: {name_en}
- Organisation: {org_name}
- Parent Policy: {parent_policy_id or "N/A"}
- Parent Standard: {parent_standard_id or "N/A"}
{dep_block}

Return valid JSON with exactly these keys:
{{
  "definitions": [{{"term_ar": "Term", "term_en": "Term", "definition_ar": "Definition..."}}],
  "objective_ar": "This procedure establishes...",
  "scope_ar": "This procedure applies to...",
  "roles": [
    {{"role_ar": "Cybersecurity Analyst", "responsibilities_ar": ["Monitors alerts...", "Escalates incidents..."]}}
  ],
  "overview_ar": "High-level description of the procedure flow...",
  "triggers_ar": ["Receipt of a security alert...", "User-reported incident..."],
  "prerequisites_ar": ["Access to SIEM system...", "Completion of training..."],
  "inputs_ar": ["Alert notification...", "Incident ticket..."],
  "tools_ar": ["SIEM Platform", "Ticketing System", "Threat Intelligence Platform"],
  "phases": [
    {{
      "phase_id": "7.1",
      "phase_title_ar": "Phase 1: [Title]",
      "phase_objective_ar": "To [objective]...",
      "steps": [
        {{
          "step_id": "7.1.1",
          "step_title_ar": "Step title",
          "actor_ar": "Role name",
          "action_ar": "Detailed action description...",
          "system_ar": "System/tool name",
          "output_ar": "Output or deliverable",
          "evidence_ar": "Audit evidence (log entry, ticket, record)",
          "timing_ar": "Within X hours/days",
          "sub_steps_ar": [],
          "decision_ar": ""
        }}
      ]
    }}
  ],
  "decision_points_ar": ["If [condition], then [action]..."],
  "exceptions_ar": "Exceptions to this procedure must be approved by...",
  "escalation_ar": "Escalate to [role] when...",
  "outputs_ar": ["Incident report", "Closure notification"],
  "records_ar": ["Incident log entry", "Evidence package"],
  "evidence_ar": ["SIEM logs", "Email trail", "Signed forms"],
  "forms_ar": ["Incident Report Form", "Exception Request Form"],
  "time_controls_ar": ["Initial response within 1 hour", "Closure within 5 business days"],
  "related_docs": [{{"title_ar": "Document Title", "title_en": "Document Title", "ref_type": "Policy"}}],
  "effective_date_ar": "This procedure comes into effect on the date of its approval.",
  "review_ar": "This procedure must be reviewed annually...",
  "approval_stages": [
    {{"stage_ar": "Prepared by", "role_ar": "Director, Cybersecurity Department", "name_ar": "[Name]", "date_ar": "[Date]"}},
    {{"stage_ar": "Reviewed by", "role_ar": "Deputy Minister for Technical Affairs", "name_ar": "[Name]", "date_ar": "[Date]"}},
    {{"stage_ar": "Approved by", "role_ar": "Minister", "name_ar": "[Name]", "date_ar": "[Date]"}}
  ],
  "version_rows": [{{"version": "1.0", "update_type_ar": "Initial Release", "summary_ar": "Initial version.", "updated_by_ar": "Cybersecurity Department", "approval_date": ""}}]
}}

Requirements:
- phases: 3-5 phases, each with 4-6 steps
- Each step must specify actor, action, output, and evidence
- definitions: 6-10 terms
- roles: 3-5 roles with specific responsibilities
"""

    raw = _chat_json(system, user)
    meta = MinistryMeta(
        doc_id=doc_id, doc_type="procedure",
        title_ar=name_en, title_en=name_en,
        reference_number=doc_id,
        classification="Confidential — Internal Use Only",
        owner="Cybersecurity Department",
    )
    phases = []
    for ph in raw.get("phases", []):
        phases.append(ProcedurePhase(
            phase_id=ph.get("phase_id", "7.1"),
            phase_title_ar=ph.get("phase_title_ar", ""),
            phase_objective_ar=ph.get("phase_objective_ar", ""),
            steps=[ProcedureStep(**s) for s in ph.get("steps", [])],
        ))
    from .ministry_models import PolicyRelatedDoc as _PRD
    return MinistryProcedureDraft(
        meta=meta,
        parent_policy_id=parent_policy_id,
        parent_standard_id=parent_standard_id,
        definitions=[DefinitionEntry(**d) for d in raw.get("definitions", [])],
        objective_ar=raw.get("objective_ar", ""),
        scope_ar=raw.get("scope_ar", ""),
        roles=[ProcedureRoleItem(**r) for r in raw.get("roles", [])],
        overview_ar=raw.get("overview_ar", ""),
        triggers_ar=raw.get("triggers_ar", []),
        prerequisites_ar=raw.get("prerequisites_ar", []),
        inputs_ar=raw.get("inputs_ar", []),
        tools_ar=raw.get("tools_ar", []),
        phases=phases,
        decision_points_ar=raw.get("decision_points_ar", []),
        exceptions_ar=raw.get("exceptions_ar", ""),
        escalation_ar=raw.get("escalation_ar", ""),
        outputs_ar=raw.get("outputs_ar", []),
        records_ar=raw.get("records_ar", []),
        evidence_ar=raw.get("evidence_ar", []),
        forms_ar=raw.get("forms_ar", []),
        time_controls_ar=raw.get("time_controls_ar", []),
        related_docs=[_PRD(**r) for r in raw.get("related_docs", [])],
        effective_date_ar=raw.get("effective_date_ar", ""),
        review_ar=raw.get("review_ar", ""),
        approval_stages=[ApprovalStage(**a) for a in raw.get("approval_stages", [])],
        version_rows=[VersionRow(**v) for v in raw.get("version_rows", [])],
        dependency_summary=dependency_context[:500] if dependency_context else "",
    )


def extract_dependency_summary_en(doc) -> str:
    """Extract English dependency summary."""
    from .ministry_models import MinistryPolicyDraft, MinistryStandardDraft
    if isinstance(doc, MinistryPolicyDraft):
        clauses = "\n".join(f"- {c.text_ar}" for c in doc.policy_clauses[:6])
        return f"[{doc.meta.doc_id}] {doc.meta.title_en}\nObjective: {doc.objective_ar[:300]}\nKey clauses:\n{clauses}"
    elif isinstance(doc, MinistryStandardDraft):
        clusters = "\n".join(f"- {c.cluster_id}: {c.title_ar} ({len(c.clauses)} clauses)" for c in doc.domain_clusters)
        return f"[{doc.meta.doc_id}] {doc.meta.title_en}\nObjective: {doc.objective_ar[:300]}\nDomain clusters:\n{clusters}"
    else:
        phases = "\n".join(f"- {p.phase_id}: {p.phase_title_ar} ({len(p.steps)} steps)" for p in doc.phases)
        return f"[{doc.meta.doc_id}] {doc.meta.title_en}\nObjective: {doc.objective_ar[:300]}\nPhases:\n{phases}"
