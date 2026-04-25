"""
Policy Drafting Agent — Big4 consulting grade, Fortune500 audience.

Dedicated agent for POL-* documents. Generates governance-level cybersecurity
policies aligned to NCA ECC, ISO/IEC 27001:2022, NIST CSF 2.0, and CIS Controls v8.
Every normative 'shall' statement carries NCA trace entries from the control bundles.
"""
from __future__ import annotations

import json
from .rate_limited_client import get_openai_client

from ..config import DRAFT_MODEL_POLICY
from .domain_profiles import detect_policy_domain
from ..schema_loader import schema_as_prompt_text
from ..models import (
    EntityProfile, DocumentSpec, ControlBundle,
    PolicyDraftOutput, PolicyElement, Subprogram, RolesResponsibilities, TraceEntry,
    SUBPROGRAM_CATALOG,
)

# ── OpenAI Structured Output schema ────────────────────────────────────────────

_TRACE_ENTRY = {
    "type": "object",
    "properties": {
        "framework":  {"type": "string"},
        "control_id": {"type": "string"},
        "source_ref": {"type": "string"},
    },
    "required": ["framework", "control_id", "source_ref"],
    "additionalProperties": False,
}

_POLICY_SCHEMA = {
    "name": "PolicyDraftOutput",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "doc_id":         {"type": "string"},
            "title_en":       {"type": "string"},
            "version":        {"type": "string"},
            "effective_date": {"type": "string"},
            "owner":          {"type": "string"},
            "classification": {"type": "string"},
            "objectives_en":          {"type": "string"},
            "scope_applicability_en": {"type": "string"},
            "policy_elements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "element_no":   {"type": "string"},
                        "statement_en": {"type": "string"},
                        "trace": {"type": "array", "items": _TRACE_ENTRY},
                    },
                    "required": ["element_no", "statement_en", "trace"],
                    "additionalProperties": False,
                }
            },
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
                }
            },
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
                    "HR", "cybersecurity", "other_departments", "all_staff"
                ],
                "additionalProperties": False,
            },
            "compliance_clauses": {"type": "array", "items": {"type": "string"}},
            "exceptions_en":      {"type": "string"},
            "closing_note_en":    {"type": "string"},
        },
        "required": [
            "doc_id", "title_en", "version", "effective_date", "owner", "classification",
            "objectives_en", "scope_applicability_en", "policy_elements",
            "policy_subprograms", "roles_responsibilities",
            "compliance_clauses", "exceptions_en", "closing_note_en",
        ],
        "additionalProperties": False,
    }
}


class PolicyDraftingAgent:
    """
    Big4-grade Policy Authoring Agent.

    Produces ministry-grade Cybersecurity Governance Policies suitable for
    Fortune500 organizations and government ministries. Every normative statement
    traces to an NCA control. Multi-framework alignment: NCA ECC, ISO 27001:2022,
    NIST CSF 2.0, CIS Controls v8, NIST SP 800-53 Rev 5.
    """

    def __init__(self):
        self._client = get_openai_client()

    def draft(
        self,
        profile: EntityProfile,
        spec: DocumentSpec,
        bundles: list[ControlBundle],
        doc_id: str,
        qa_findings: list[str] | None = None,
    ) -> PolicyDraftOutput:
        print(f"[PolicyDrafter] Compiling {doc_id} | {spec.topic} | "
              f"{len(bundles)} bundles | model={DRAFT_MODEL_POLICY}")
        domain = detect_policy_domain(spec.topic)
        print(f"[PolicyDrafter] Domain profile: {domain.name}")

        schema_text = schema_as_prompt_text("policy")
        catalog_prompt = "\n".join(f"  {no}: {name}" for no, name in SUBPROGRAM_CATALOG)
        bundle_list = _bundle_list(bundles)

        system_msg = f"""\
You are a Principal Cybersecurity Governance Consultant at a Big4 advisory firm.
You author ENTERPRISE CYBERSECURITY POLICIES for Fortune500 corporations and
government ministries. Your work is reviewed at Board and C-suite level and forms
the basis for external regulatory audits (NCA ECC, ISO 27001, SOC 2, NIST CSF).

CLIENT: {profile.org_name} | Sector: {profile.sector} | Jurisdiction: {profile.jurisdiction}
Hosting: {profile.hosting_model} | SOC model: {profile.soc_model}
Critical systems: {', '.join(profile.critical_systems) or 'Not specified'}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AUTHORITATIVE DOCUMENT SCHEMA (overrides all templates)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{schema_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMPILER WORKFLOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. AST Construction:
   DocumentAST {{
     Metadata → Cover → TOC → DocumentInfo
     § 1  Definitions          (4–10 terms, definition table)
     § 2  Policy Objective     (1–2 paragraphs, CIA triad, NCA ECC regulatory basis)
     § 3  Policy Scope         (1–2 paragraphs, all personnel + assets)
     § 4  Policy Statement     ← DOMINANT (40–55% of document, 7–25 clauses)
     § 5  Roles & Responsibilities
     § 6  Related Documents
     § 7  Effective Date
     § 8  Policy Review        (cadence + 3 trigger events)
     § 9  Review & Approval    (prepared → reviewed → recommended → approved)
     § 10 Version Control      (table)
     Optional: Control Mapping Matrix
   }}
2. Section 4 MUST be the dominant section — more substantive than all other sections combined.
3. Generate each section node from its schema blueprint.
4. Apply QA gates before output.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FRAMEWORK HIERARCHY (non-negotiable)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRIMARY (NCA controls — must anchor every 'shall'):
  NCA_ECC, NCA_CSCC, NCA_CCC, NCA_DCC, NCA_TCC, NCA_OSMACC, NCA_NCS

SUPPLEMENTARY (cite only where NCA needs depth):
  NIST_80053 (SP 800-53 Rev 5), UAE_IA

CROSS-REFERENCE FRAMEWORKS (name in text but do not fabricate trace IDs):
  ISO/IEC 27001:2022 (Annex A controls), NIST CSF 2.0 (Govern/Identify/Protect/Detect/Respond/Recover),
  CIS Controls v8 (Implementation Groups 1–3), PCI-DSS v4.0 (where relevant to sector)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ABSOLUTE RULES (violation = document rejected)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. EVERY 'shall' in policy_elements MUST have ≥1 trace entry with framework starting 'NCA_'.
   source_ref = chunk_id of the cited bundle. No fabricated IDs.
2. objectives_en MUST mention Confidentiality, Integrity, and Availability AND reference
   NCA ECC as the regulatory basis (e.g., "ECC 1-3-1").
3. scope_applicability_en MUST cover all personnel categories (employees, contractors,
   consultants, third-party vendors, visitors) AND all asset types AND state this policy
   drives all subsidiary policies, standards, and procedures.
4. policy_elements MUST include elements 1, 2, and 3 as specified.
5. policy_subprograms MUST include ALL 34 catalog items (2-1 through 2-34).
6. compliance_clauses MUST be exactly 3 (monitoring → staff compliance → disciplinary/legal).
7. exceptions_en: no exception without prior written authorization from Cybersecurity + CSC.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BIG4 WRITING STANDARDS (Fortune500 board-level quality)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Authoritative, enforceable, precise — no ambiguous language
• Policy clauses are obligations, not guidelines
• Integrate risk language: "to mitigate the risk of...", "to ensure the confidentiality of..."
• Reference specific NCA ECC control families (1-1, 1-2, 1-3, 2-x, 3-x, 4-x)
• Align to ISO 27001:2022 where appropriate (name clause/Annex A reference)
• Minimum content depth:
  - objectives_en: 400+ words | scope_applicability_en: 300+ words
  - Each policy_element statement_en: 400+ words with rationale and operationalisation
  - Each subprogram objective_en: 90+ words
  - Each role group: 7–10 specific, distinct responsibilities
  - Each compliance_clause: 75+ words
  - exceptions_en: 225+ words with formal exception request process
• Document must render as 7–10 Word pages minimum

{domain.system_prompt_extension}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REQUIRED ELEMENT CONTENT (exact wording for elements 1–3)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Element 1: The Cybersecurity function shall define, document, and maintain cybersecurity
requirements, policies, and programs based on risk assessment, approved by the Authority
or Authorized Official (or delegate), and communicated to all relevant parties.
Element 2: The Cybersecurity function shall develop and implement the cybersecurity policy
suite comprising the 34 sub-programs listed below.
Element 3: The Cybersecurity function shall have the right to access information systems
and collect evidence to verify compliance with this policy and all related sub-policies.
(Add 8–22 additional elements covering risk management, access control, incident response,
asset protection, third-party governance, cloud security, awareness, BCP/DR, etc.)

SUBPROGRAM CATALOG (use exact sub_no and name_en):
{catalog_prompt}
"""

        user_payload: dict = {
            "doc_id":          doc_id,
            "org_name":        profile.org_name,
            "sector":          profile.sector,
            "jurisdiction":    profile.jurisdiction,
            "doc_type":        "policy",
            "topic":           spec.topic,
            "version":         spec.version,
            "control_bundles": bundle_list,
        }
        if qa_findings:
            user_payload["qa_findings_to_fix"] = qa_findings

        resp = self._client.chat.completions.create(
            model=DRAFT_MODEL_POLICY,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": (
                    f"Compile the complete 30-page Cybersecurity Policy for {profile.org_name}. "
                    "Every policy element must be a detailed 'shall' statement with full regulatory rationale. "
                    "Subprograms must be exhaustive. Output valid JSON."
                )},
                {"role": "user", "content": json.dumps(user_payload)},
            ],
            response_format={"type": "json_schema", "json_schema": _POLICY_SCHEMA},
            temperature=0.3,
        )

        raw = json.loads(resp.choices[0].message.content)

        elements = [
            PolicyElement(
                element_no   = e["element_no"],
                statement_en = e["statement_en"],
                trace        = [TraceEntry(**t) for t in e["trace"]],
            )
            for e in raw["policy_elements"]
        ]
        subprograms = [
            Subprogram(
                sub_no       = s["sub_no"],
                name_en      = s["name_en"],
                objective_en = s["objective_en"],
                references   = s.get("references", []),
            )
            for s in raw["policy_subprograms"]
        ]
        rr = raw["roles_responsibilities"]
        roles = RolesResponsibilities(
            authority_owner_delegates = rr["authority_owner_delegates"],
            legal                     = rr["legal"],
            internal_audit            = rr["internal_audit"],
            HR                        = rr["HR"],
            cybersecurity             = rr["cybersecurity"],
            other_departments         = rr["other_departments"],
            all_staff                 = rr["all_staff"],
        )

        draft = PolicyDraftOutput(
            doc_id                 = raw.get("doc_id", doc_id),
            title_en               = raw["title_en"],
            version                = raw.get("version", spec.version),
            effective_date         = raw.get("effective_date", "TBD"),
            owner                  = raw.get("owner", "Chief Information Security Officer"),
            classification         = raw.get("classification", "Internal"),
            objectives_en          = raw["objectives_en"],
            scope_applicability_en = raw["scope_applicability_en"],
            policy_elements        = elements,
            policy_subprograms     = subprograms,
            roles_responsibilities = roles,
            compliance_clauses     = raw["compliance_clauses"],
            exceptions_en          = raw["exceptions_en"],
            closing_note_en        = raw["closing_note_en"],
        )

        print(f"[PolicyDrafter] Complete: {len(elements)} elements, "
              f"{len(subprograms)} subprograms.")
        return draft


def _bundle_list(bundles: list[ControlBundle]) -> list[dict]:
    return [
        {
            "chunk_id":     b.chunk_id,
            "control_id":   b.control_id,
            "framework":    b.framework,
            "title":        b.title,
            "statement":    b.statement[:500],
            "rerank_score": round(b.rerank_score, 4) if b.rerank_score is not None else None,
        }
        for b in bundles
    ]
