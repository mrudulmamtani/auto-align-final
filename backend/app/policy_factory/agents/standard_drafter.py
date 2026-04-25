"""
Standard Drafting Agent — Big4 consulting grade, Fortune500 audience.

Dedicated agent for STD-* documents. Generates operational cybersecurity standards
with enforceable numbered requirements per domain cluster. Every 'shall' statement
carries NCA trace entries. Multi-framework cross-reference included in domain objectives.
"""
from __future__ import annotations

import json
from .rate_limited_client import get_openai_client

from ..config import DRAFT_MODEL_POLICY
from .domain_profiles import detect_standard_domain
from ..schema_loader import schema_as_prompt_text
from ..models import (
    EntityProfile, DocumentSpec, ControlBundle,
    StandardDraftOutput, StandardDefinition, StandardRequirement,
    StandardDomain, StandardRoleItem, TraceEntry, EXCEPTIONS_CLAUSE,
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

_STANDARD_SCHEMA = {
    "name": "StandardDraftOutput",
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
                }
            },
            "objectives_en": {"type": "string"},
            "scope_en":      {"type": "string"},
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
                                    "trace": {"type": "array", "items": _TRACE_ENTRY},
                                },
                                "required": ["req_id", "statement_en", "placeholders", "trace"],
                                "additionalProperties": False,
                            }
                        },
                    },
                    "required": ["domain_number", "title_en", "objective_en",
                                 "potential_risks_en", "requirements"],
                    "additionalProperties": False,
                }
            },
            "roles_responsibilities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item_no": {"type": "string"},
                        "text_en": {"type": "string"},
                    },
                    "required": ["item_no", "text_en"],
                    "additionalProperties": False,
                }
            },
            "review_update_en": {"type": "string"},
            "compliance_en":    {"type": "array", "items": {"type": "string"}},
            "closing_note_en":  {"type": "string"},
        },
        "required": [
            "doc_id", "title_en", "version", "effective_date", "owner", "classification",
            "definitions", "objectives_en", "scope_en", "domains",
            "roles_responsibilities", "review_update_en", "compliance_en", "closing_note_en",
        ],
        "additionalProperties": False,
    }
}


class StandardDraftingAgent:
    """
    Big4-grade Standard Authoring Agent.

    Produces technically precise, implementation-ready cybersecurity standards
    for Fortune500 and government ministry clients. Domain clusters follow the
    schema's 4.1–4.N structure with objective → risks → numbered requirements.
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
    ) -> StandardDraftOutput:
        print(f"[StandardDrafter] Compiling {doc_id} | {spec.topic} | "
              f"{len(bundles)} bundles | model={DRAFT_MODEL_POLICY}")
        domain = detect_standard_domain(spec.topic)
        print(f"[StandardDrafter] Domain profile: {domain.name}")

        schema_text = schema_as_prompt_text("standard")
        bundle_list = _bundle_list(bundles)

        system_msg = f"""\
You are a Principal Cybersecurity Standards Architect at a Big4 advisory firm.
You author ENTERPRISE CYBERSECURITY STANDARDS for Fortune500 corporations and
government ministries. Your standards serve as the technical backbone for
regulatory audits (NCA ECC, ISO 27001, SOC 2, PCI-DSS) and are implemented
by enterprise security engineering teams.

CLIENT: {profile.org_name} | Sector: {profile.sector} | Jurisdiction: {profile.jurisdiction}
Hosting: {profile.hosting_model} | SOC: {profile.soc_model}
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
     Metadata → Cover → Notice → DocumentInfo → TOC
     § 1  Abbreviations & Definitions   (6–15 operational terms)
     § 2  Objective                     (2–4 paragraphs, CIA, regulatory basis, risk rationale)
     § 3  Scope of Work & Applicability (intro + categorised sub-scope bullets)
     § 4  Standards                     ← DOMINANT (45–60% of document)
          § 4.1  Governance & Management
          § 4.2  Mandatory Requirements
          § 4.3  Time-Based Controls & Periodic Reviews
          § 4.4  Implementation Guidance (add 4.5+ as domain warrants)
     § 5  Exceptions
     § 6  Roles & Responsibilities      (table: role | accountability)
     § 7  Update & Review
     § 8  Compliance with the Standard
   }}
2. Section 4 MUST contain 45–60% of total document words.
3. Each Section 4 cluster MUST have: title → objective → potential_risks → numbered requirements.
4. Requirements numbered N.M (e.g. 1.1, 1.2, 2.1) — sequential per domain.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FRAMEWORK HIERARCHY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRIMARY  : NCA_ECC, NCA_CSCC, NCA_CCC, NCA_DCC, NCA_TCC, NCA_OSMACC, NCA_NCS
SECONDARY: NIST_80053 (SP 800-53 Rev 5) — supplement NCA where depth is needed
NAME ONLY (no fabricated trace IDs):
  ISO/IEC 27001:2022 Annex A | NIST CSF 2.0 | CIS Controls v8 | PCI-DSS v4.0

EVERY 'shall' requirement MUST carry ≥1 NCA_ trace entry. NIST may be added as
secondary. No fabricated control IDs. source_ref = chunk_id of cited bundle.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ABSOLUTE RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. EVERY 'shall' → ≥1 NCA_ trace. No invented IDs.
2. objectives_en: cite CIA triad + NCA ECC (e.g., ECC 1-3-1) as regulatory basis.
3. scope_en: all employees / contractors / consultants / service providers / visitors AND
   all information assets / systems / technology. Include EXACT exceptions clause:
   "{EXCEPTIONS_CLAUSE}"
4. Min 7 domain clusters; each has objective_en (250+ words), potential_risks_en (250+ words),
   and min 9 requirements with 'shall' language.
5. definitions: min 12 terms; each description_en 90+ words, operationally focused.
6. roles_responsibilities: exactly 3 items — item_no "1-" = Document Sponsor/Owner,
   "2-" = Review & Update Owner, "3-" = Implementation Owner.
7. review_update_en: must mention all 3 triggers (major technology changes; changes in
   policies/procedures; regulatory/legislative changes).
8. compliance_en: exactly 3 clauses (monitoring; staff compliance; disciplinary/legal).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BIG4 TECHNICAL STANDARDS (Fortune500 quality)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Each requirement is an auditable control statement: "The Ministry shall…"
• Measurable where possible: specify timescales (e.g., "within 24 hours"), thresholds
  (e.g., "password complexity of minimum 14 characters"), and frequencies (e.g., "quarterly")
• Domain-aware requirements that reflect the technical realities of {spec.topic}
• Risk-based sequencing: governance → mandatory controls → time-based → implementation
• Cross-reference ISO 27001 Annex A and NIST CSF functions in domain objectives
• Evidence requirements: what artifact proves compliance (log, report, configuration export)
• Domain 4.4+ Implementation Guidance: reference enterprise tools by name where appropriate
  for {profile.sector} sector (do not mandate specific vendors, but name examples)
• Minimum content depth:
  - objectives_en: 400+ words | scope_en: 400+ words
  - Each domain objective_en: 250+ words | potential_risks_en: 250+ words
  - Each requirement statement_en: 90+ words, full normative sentence
  - Each role text_en: 180+ words with specific accountabilities
  - review_update_en: 300+ words covering all 3 triggers
  - Each compliance_en clause: 90+ words
• Document renders as 14–20 Word pages

{domain.system_prompt_extension}

TOPIC-SPECIFIC DOMAIN GUIDANCE for: {spec.topic}
Generate domain clusters that logically decompose the technical control area into:
  4.1 — Governance and accountability framework
  4.2 — Core mandatory technical and process controls
  4.3 — Time-bound and periodic control activities
  4.4 — Implementation guidance, tooling, and evidence requirements
  4.5+ — Additional specialised sub-domains where warranted
"""

        user_payload: dict = {
            "doc_id":          doc_id,
            "org_name":        profile.org_name,
            "sector":          profile.sector,
            "jurisdiction":    profile.jurisdiction,
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
                    f"Compile the complete Cybersecurity Standard for {profile.org_name}. "
                    f"Topic: {spec.topic}. "
                    "Section 4 must be 45–60% of content with min 5 domain clusters. "
                    "Trace every 'shall' to real NCA control_ids. Min 8 definitions. "
                    "Output valid JSON. Enterprise audit-ready quality required."
                )},
                {"role": "user", "content": json.dumps(user_payload)},
            ],
            response_format={"type": "json_schema", "json_schema": _STANDARD_SCHEMA},
            temperature=0.2,
        )

        raw = json.loads(resp.choices[0].message.content)

        definitions = [
            StandardDefinition(term_en=d["term_en"], description_en=d["description_en"])
            for d in raw["definitions"]
        ]
        domains = []
        for dom in raw["domains"]:
            reqs = [
                StandardRequirement(
                    req_id       = r["req_id"],
                    statement_en = r["statement_en"],
                    placeholders = r.get("placeholders", []),
                    trace        = [TraceEntry(**t) for t in r["trace"]],
                )
                for r in dom["requirements"]
            ]
            domains.append(StandardDomain(
                domain_number      = dom["domain_number"],
                title_en           = dom["title_en"],
                objective_en       = dom["objective_en"],
                potential_risks_en = dom["potential_risks_en"],
                requirements       = reqs,
            ))
        roles = [
            StandardRoleItem(item_no=r["item_no"], text_en=r["text_en"])
            for r in raw["roles_responsibilities"]
        ]

        draft = StandardDraftOutput(
            doc_id             = raw.get("doc_id", doc_id),
            title_en           = raw["title_en"],
            version            = raw.get("version", spec.version),
            effective_date     = raw.get("effective_date", "TBD"),
            owner              = raw.get("owner", "Chief Information Security Officer"),
            classification     = raw.get("classification", "Internal"),
            definitions        = definitions,
            objectives_en      = raw["objectives_en"],
            scope_en           = raw["scope_en"],
            domains            = domains,
            roles_responsibilities = roles,
            review_update_en   = raw["review_update_en"],
            compliance_en      = raw["compliance_en"],
            closing_note_en    = raw["closing_note_en"],
        )

        total_reqs = sum(len(d.requirements) for d in domains)
        print(f"[StandardDrafter] Complete: {len(domains)} domains, {total_reqs} requirements.")
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
