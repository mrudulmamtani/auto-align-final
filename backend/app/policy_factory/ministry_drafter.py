"""
Ministry Drafter — generates Arabic-primary policy/standard/procedure documents
using GPT-4o structured outputs following the three ministry schemas.

Dependency context is injected as system context so that generated documents
are aware of and consistent with their parent/sibling documents.
"""
from __future__ import annotations
import json
import os
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


def _chat(system: str, user: str, model: str = _MODEL) -> str:
    """Simple chat completion returning the assistant message content."""
    resp = _get_client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        temperature=0.3,
        max_tokens=8000,
    )
    return resp.choices[0].message.content or ""


def _chat_json(system: str, user: str, model: str = _MODEL) -> Any:
    """Chat completion with JSON mode."""
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
    raw = resp.choices[0].message.content or "{}"
    return json.loads(raw)


# ── Ministry system prompt base ────────────────────────────────────────────────

_MINISTRY_SYSTEM = """أنت خبير في صياغة الوثائق الحكومية للأمن السيبراني على المستوى الوزاري.
تعمل بإطار ClientX للأمن السيبراني وتُنتج وثائق باللغة العربية أولاً مع مصطلحات إنجليزية تقنية محدودة بين قوسين عند الضرورة.

القواعد الأساسية:
- اللغة العربية أولاً: جميع النصوص التشغيلية بالعربية الفصحى الرسمية
- النبرة: رسمية، مباشرة، حكومية، موثوقة
- أسلوب الالتزام: يجب / يُحظر (للمتطلبات الإلزامية)، ينبغي (للتوجيه)
- لا تكتب إجراءات تشغيلية مفصّلة في السياسات والمعايير
- جميع المخرجات بصيغة JSON صحيحة
"""


# ══════════════════════════════════════════════════════════════════════════════
# POLICY DRAFTER
# ══════════════════════════════════════════════════════════════════════════════

def draft_policy(
    doc_id: str,
    name_en: str,
    name_ar: str,
    dependency_context: str = "",
    org_name: str = "الوزارة",
) -> MinistryPolicyDraft:
    """Draft a full ministry policy document in Arabic."""

    dep_block = ""
    if dependency_context:
        dep_block = f"""
## سياق الوثائق المرجعية (استخدمه لضمان الاتساق):
{dependency_context}
"""

    system = _MINISTRY_SYSTEM + """
أنت تصيغ **سياسة** (Policy) وزارية للأمن السيبراني.
السياسة هي "الماذا ولماذا" — إطار الحوكمة العليا، ليست إجراءات تفصيلية.
القسم 4 (بنود السياسة) يجب أن يكون المقطع الأطول والأكثر شمولاً.
العدد المطلوب من البنود: 12 إلى 20 بند.
"""

    user = f"""أنشئ وثيقة سياسة وزارية كاملة للأمن السيبراني بالمعطيات التالية:

- معرّف الوثيقة: {doc_id}
- العنوان الإنجليزي: {name_en}
- العنوان العربي: {name_ar}
- الجهة: {org_name}
{dep_block}

أنتج JSON صحيح يحتوي على المفاتيح التالية تماماً:
{{
  "definitions": [
    {{"term_ar": "...", "term_en": "...", "definition_ar": "..."}}
  ],
  "objective_ar": "...",
  "scope_ar": "...",
  "policy_clauses": [
    {{"clause_no": 1, "text_ar": "يجب أن ...", "sub_bullets_ar": []}}
  ],
  "roles_ar": "...",
  "related_docs": [
    {{"title_ar": "...", "title_en": "...", "ref_type": "..."}}
  ],
  "effective_date_ar": "تسري هذه السياسة اعتباراً من تاريخ اعتمادها.",
  "review_ar": "...",
  "approval_stages": [
    {{"stage_ar": "أعدّه", "role_ar": "مدير إدارة الأمن السيبراني", "name_ar": "[الاسم]", "date_ar": "[التاريخ]"}},
    {{"stage_ar": "راجعه", "role_ar": "نائب الوزير للشؤون التقنية", "name_ar": "[الاسم]", "date_ar": "[التاريخ]"}},
    {{"stage_ar": "وافق عليه", "role_ar": "الوزير", "name_ar": "[الاسم]", "date_ar": "[التاريخ]"}}
  ],
  "version_rows": [
    {{"version": "1.0", "update_type_ar": "إصدار أوّلي", "summary_ar": "الإصدار الأوّلي من الوثيقة", "updated_by_ar": "إدارة الأمن السيبراني", "approval_date": ""}}
  ],
  "control_mapping": {{}}
}}

متطلبات مهمة:
- التعريفات: 6-10 مصطلحات تشمل الوزارة والوزير وموظفو الوزارة والسياسة وأي مصطلحات تقنية أساسية
- بنود السياسة: 12-20 بند، كل بند جملة إلزامية تبدأ بـ "يجب" أو "يُحظر"
- القسم 4 يجب أن يكون مهيمناً وشاملاً
- الأسلوب: رسمي حكومي فصيح
"""

    raw = _chat_json(system, user)

    meta = MinistryMeta(
        doc_id=doc_id,
        doc_type="policy",
        title_ar=name_ar,
        title_en=name_en,
        reference_number=doc_id,
    )

    definitions = [DefinitionEntry(**d) for d in raw.get("definitions", [])]
    clauses = [PolicyClause(**c) for c in raw.get("policy_clauses", [])]
    related = [PolicyRelatedDoc(**r) for r in raw.get("related_docs", [])]
    approvals = [ApprovalStage(**a) for a in raw.get("approval_stages", [])]
    versions = [VersionRow(**v) for v in raw.get("version_rows", [])]

    return MinistryPolicyDraft(
        meta=meta,
        definitions=definitions,
        objective_ar=raw.get("objective_ar", ""),
        scope_ar=raw.get("scope_ar", ""),
        policy_clauses=clauses,
        roles_ar=raw.get("roles_ar", ""),
        related_docs=related,
        effective_date_ar=raw.get("effective_date_ar", ""),
        review_ar=raw.get("review_ar", ""),
        approval_stages=approvals,
        version_rows=versions,
        control_mapping=raw.get("control_mapping", {}),
        dependency_summary=dependency_context[:500] if dependency_context else "",
    )


# ══════════════════════════════════════════════════════════════════════════════
# STANDARD DRAFTER
# ══════════════════════════════════════════════════════════════════════════════

def draft_standard(
    doc_id: str,
    name_en: str,
    name_ar: str,
    dependency_context: str = "",
    org_name: str = "الوزارة",
) -> MinistryStandardDraft:
    """Draft a full ministry standard document in Arabic."""

    dep_block = ""
    if dependency_context:
        dep_block = f"""
## سياق الوثائق المرجعية:
{dependency_context}
"""

    system = _MINISTRY_SYSTEM + """
أنت تصيغ **معياراً** (Standard) وزارياً للأمن السيبراني.
المعيار هو "الماذا ومَن" — المتطلبات التشغيلية المفصّلة ضمن مجموعات موضوعية.
القسم 4 (المعايير) هو المحور الرئيسي: يجب أن يحتوي على 3-4 مجموعات موضوعية (clusters).
كل مجموعة تحتوي: هدف + مخاطر محتملة + بنود تشغيلية مرقّمة (على الأقل 5 بنود لكل مجموعة).
إجمالي البنود التشغيلية: 20-35 بند.
"""

    user = f"""أنشئ معياراً وزارياً كاملاً للأمن السيبراني بالمعطيات التالية:

- معرّف الوثيقة: {doc_id}
- العنوان الإنجليزي: {name_en}
- العنوان العربي: {name_ar}
- الجهة: {org_name}
{dep_block}

أنتج JSON صحيح يحتوي على المفاتيح التالية تماماً:
{{
  "notice_ar": "هذه الوثيقة ملكية حصرية للوزارة. يُحظر نسخها أو الإفصاح عنها دون إذن مسبق من إدارة الأمن السيبراني.",
  "notice_en": "This document is the exclusive property of the Ministry. Reproduction or disclosure without prior written consent of the Cybersecurity Department is prohibited.",
  "definitions": [
    {{"term_ar": "...", "term_en": "...", "definition_ar": "..."}}
  ],
  "objective_ar": "...",
  "scope_intro_ar": "...",
  "scope_systems_ar": ["..."],
  "scope_roles_ar": ["..."],
  "scope_processes_ar": ["..."],
  "scope_persons_ar": ["..."],
  "domain_clusters": [
    {{
      "cluster_id": "4.1",
      "title_ar": "...",
      "objective_ar": "...",
      "potential_risks_ar": "...",
      "clauses": [
        {{"clause_id": "4.1.1", "text_ar": "يجب أن ...", "guidance_ar": "", "is_mandatory": true}}
      ]
    }}
  ],
  "exceptions_ar": "...",
  "roles_responsibilities": {{"إدارة الأمن السيبراني": "...", "أصحاب الأنظمة": "...", "المراجعة الداخلية": "..."}},
  "update_review_ar": "...",
  "compliance_ar": "...",
  "version_rows": [{{"version": "1.0", "update_type_ar": "إصدار أوّلي", "summary_ar": "الإصدار الأوّلي", "updated_by_ar": "إدارة الأمن السيبراني", "approval_date": ""}}],
  "approval_stages": [
    {{"stage_ar": "أعدّه", "role_ar": "مدير إدارة الأمن السيبراني", "name_ar": "[الاسم]", "date_ar": "[التاريخ]"}},
    {{"stage_ar": "راجعه", "role_ar": "نائب الوزير للشؤون التقنية", "name_ar": "[الاسم]", "date_ar": "[التاريخ]"}},
    {{"stage_ar": "وافق عليه", "role_ar": "الوزير", "name_ar": "[الاسم]", "date_ar": "[التاريخ]"}}
  ]
}}

متطلبات مهمة:
- التعريفات: 8-15 مصطلح تقني مرتبط بموضوع المعيار
- مجموعات القسم 4: 3-4 مجموعات على الأقل، كل مجموعة 5-10 بنود
- البنود الإلزامية تبدأ بـ "يجب أن" والإرشادية تبدأ بـ "ينبغي"
- ترقيم البنود: 4.1.1 و 4.1.2 ... 4.2.1 و 4.2.2 ... إلخ
"""

    raw = _chat_json(system, user)

    meta = MinistryMeta(
        doc_id=doc_id,
        doc_type="standard",
        title_ar=name_ar,
        title_en=name_en,
        reference_number=doc_id,
    )

    definitions = [DefinitionEntry(**d) for d in raw.get("definitions", [])]
    clusters = []
    for c in raw.get("domain_clusters", []):
        clauses = [StandardClause(**cl) for cl in c.get("clauses", [])]
        clusters.append(StandardDomainCluster(
            cluster_id=c.get("cluster_id", "4.1"),
            title_ar=c.get("title_ar", ""),
            objective_ar=c.get("objective_ar", ""),
            potential_risks_ar=c.get("potential_risks_ar", ""),
            clauses=clauses,
        ))
    approvals = [ApprovalStage(**a) for a in raw.get("approval_stages", [])]
    versions = [VersionRow(**v) for v in raw.get("version_rows", [])]

    return MinistryStandardDraft(
        meta=meta,
        notice_ar=raw.get("notice_ar", ""),
        notice_en=raw.get("notice_en", ""),
        definitions=definitions,
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
        version_rows=versions,
        approval_stages=approvals,
        dependency_summary=dependency_context[:500] if dependency_context else "",
    )


# ══════════════════════════════════════════════════════════════════════════════
# PROCEDURE DRAFTER
# ══════════════════════════════════════════════════════════════════════════════

def draft_procedure(
    doc_id: str,
    name_en: str,
    name_ar: str,
    dependency_context: str = "",
    org_name: str = "الوزارة",
    parent_policy_id: str = "",
    parent_standard_id: str = "",
) -> MinistryProcedureDraft:
    """Draft a full ministry procedure document in Arabic."""

    dep_block = ""
    if dependency_context:
        dep_block = f"""
## سياق الوثائق المرجعية:
{dependency_context}
"""

    system = _MINISTRY_SYSTEM + """
أنت تصيغ **إجراءً** (Procedure) وزارياً للأمن السيبراني.
الإجراء هو "الكيف" — خطوات تنفيذية تفصيلية قابلة للتدقيق ومحددة الأدوار.
القسم 7 (خطوات الإجراء التفصيلية) هو المحور الرئيسي: 2-6 مراحل، كل مرحلة تحتوي على 3-8 خطوات.
كل خطوة يجب أن تحدد: المنفّذ، الإجراء، النظام، المخرج، والدليل.
"""

    user = f"""أنشئ إجراءً وزارياً كاملاً للأمن السيبراني بالمعطيات التالية:

- معرّف الوثيقة: {doc_id}
- العنوان الإنجليزي: {name_en}
- العنوان العربي: {name_ar}
- الجهة: {org_name}
- السياسة الأم: {parent_policy_id or 'غير محدد'}
- المعيار الأم: {parent_standard_id or 'غير محدد'}
{dep_block}

أنتج JSON صحيح يحتوي على المفاتيح التالية تماماً:
{{
  "definitions": [{{"term_ar": "...", "term_en": "...", "definition_ar": "..."}}],
  "objective_ar": "...",
  "scope_ar": "...",
  "roles": [
    {{"role_ar": "...", "responsibilities_ar": ["...", "..."]}}
  ],
  "overview_ar": "...",
  "triggers_ar": ["..."],
  "prerequisites_ar": ["..."],
  "inputs_ar": ["..."],
  "tools_ar": ["..."],
  "phases": [
    {{
      "phase_id": "7.1",
      "phase_title_ar": "...",
      "phase_objective_ar": "...",
      "steps": [
        {{
          "step_id": "7.1.1",
          "step_title_ar": "...",
          "actor_ar": "...",
          "action_ar": "...",
          "system_ar": "...",
          "output_ar": "...",
          "evidence_ar": "...",
          "timing_ar": "...",
          "sub_steps_ar": [],
          "decision_ar": ""
        }}
      ]
    }}
  ],
  "decision_points_ar": ["..."],
  "exceptions_ar": "...",
  "escalation_ar": "...",
  "outputs_ar": ["..."],
  "records_ar": ["..."],
  "evidence_ar": ["..."],
  "forms_ar": ["..."],
  "time_controls_ar": ["..."],
  "related_docs": [{{"title_ar": "...", "title_en": "...", "ref_type": "..."}}],
  "effective_date_ar": "يسري هذا الإجراء اعتباراً من تاريخ اعتماده.",
  "review_ar": "...",
  "approval_stages": [
    {{"stage_ar": "أعدّه", "role_ar": "مدير إدارة الأمن السيبراني", "name_ar": "[الاسم]", "date_ar": "[التاريخ]"}},
    {{"stage_ar": "راجعه", "role_ar": "نائب الوزير للشؤون التقنية", "name_ar": "[الاسم]", "date_ar": "[التاريخ]"}},
    {{"stage_ar": "وافق عليه", "role_ar": "الوزير", "name_ar": "[الاسم]", "date_ar": "[التاريخ]"}}
  ],
  "version_rows": [{{"version": "1.0", "update_type_ar": "إصدار أوّلي", "summary_ar": "الإصدار الأوّلي", "updated_by_ar": "إدارة الأمن السيبراني", "approval_date": ""}}]
}}

متطلبات مهمة:
- مراحل القسم 7: 3-5 مراحل، كل مرحلة 3-6 خطوات
- كل خطوة يجب أن تحدد المنفّذ والإجراء والمخرج
- الترقيم التسلسلي: 7.1.1 → 7.1.2 → 7.2.1 → 7.2.2 إلخ
- التعريفات: 6-10 مصطلحات
- الأدوار: 3-5 أدوار موضّحة مسؤولياتها
"""

    raw = _chat_json(system, user)

    meta = MinistryMeta(
        doc_id=doc_id,
        doc_type="procedure",
        title_ar=name_ar,
        title_en=name_en,
        reference_number=doc_id,
    )

    definitions = [DefinitionEntry(**d) for d in raw.get("definitions", [])]
    roles = [ProcedureRoleItem(**r) for r in raw.get("roles", [])]
    phases = []
    for ph in raw.get("phases", []):
        steps = [ProcedureStep(**s) for s in ph.get("steps", [])]
        phases.append(ProcedurePhase(
            phase_id=ph.get("phase_id", "7.1"),
            phase_title_ar=ph.get("phase_title_ar", ""),
            phase_objective_ar=ph.get("phase_objective_ar", ""),
            steps=steps,
        ))
    from .ministry_models import PolicyRelatedDoc as _PRD
    related = [_PRD(**r) for r in raw.get("related_docs", [])]
    approvals = [ApprovalStage(**a) for a in raw.get("approval_stages", [])]
    versions = [VersionRow(**v) for v in raw.get("version_rows", [])]

    return MinistryProcedureDraft(
        meta=meta,
        parent_policy_id=parent_policy_id,
        parent_standard_id=parent_standard_id,
        definitions=definitions,
        objective_ar=raw.get("objective_ar", ""),
        scope_ar=raw.get("scope_ar", ""),
        roles=roles,
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
        related_docs=related,
        effective_date_ar=raw.get("effective_date_ar", ""),
        review_ar=raw.get("review_ar", ""),
        approval_stages=approvals,
        version_rows=versions,
        dependency_summary=dependency_context[:500] if dependency_context else "",
    )


# ── Dependency summary extractor ───────────────────────────────────────────────

def extract_dependency_summary(doc: MinistryPolicyDraft | MinistryStandardDraft | MinistryProcedureDraft) -> str:
    """Extract a concise Arabic summary of a generated document for use as dependency context."""
    if isinstance(doc, MinistryPolicyDraft):
        clauses_preview = "\n".join(
            f"- {c.text_ar}" for c in doc.policy_clauses[:8]
        )
        return (
            f"[{doc.meta.doc_id}] {doc.meta.title_ar}\n"
            f"الهدف: {doc.objective_ar[:300]}\n"
            f"النطاق: {doc.scope_ar[:200]}\n"
            f"أبرز بنود السياسة:\n{clauses_preview}"
        )
    elif isinstance(doc, MinistryStandardDraft):
        clusters_preview = "\n".join(
            f"- {c.cluster_id}: {c.title_ar} ({len(c.clauses)} بند)"
            for c in doc.domain_clusters
        )
        return (
            f"[{doc.meta.doc_id}] {doc.meta.title_ar}\n"
            f"الهدف: {doc.objective_ar[:300]}\n"
            f"المجموعات الموضوعية:\n{clusters_preview}"
        )
    else:
        phases_preview = "\n".join(
            f"- {p.phase_id}: {p.phase_title_ar} ({len(p.steps)} خطوة)"
            for p in doc.phases
        )
        return (
            f"[{doc.meta.doc_id}] {doc.meta.title_ar}\n"
            f"الهدف: {doc.objective_ar[:300]}\n"
            f"مراحل الإجراء:\n{phases_preview}"
        )
