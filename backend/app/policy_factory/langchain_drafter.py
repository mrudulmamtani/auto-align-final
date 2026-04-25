"""
LangChain-based Ministry Document Drafter
------------------------------------------
Produces BIG4-grade cybersecurity policy / standard / procedure documents
by combining:

  1. Semantic RAG retrieval from the NCA OSCAL catalog (432 controls)
  2. Full parent-document context injection (policy → standard → procedure)
  3. Strict golden-baseline schema enforcement (policy.json / standard.json /
     procedure.json)
  4. Real NCA control traceability on every "shall" / "must" statement

Output models:  PolicySpec, StandardSpec, ProcedureSpec
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from .config import OPENAI_API_KEY
from .control_retriever import get_retriever

_BACKEND = Path(__file__).resolve().parent.parent.parent
_MODEL   = "gpt-4o"

# ══════════════════════════════════════════════════════════════════════════════
# Pydantic output models (strict golden-baseline structure)
# ══════════════════════════════════════════════════════════════════════════════

class ControlTrace(BaseModel):
    framework:   str = Field(description="e.g. 'NCA ECC'")
    control_id:  str = Field(description="e.g. 'ECC 1-3-1'")
    source_ref:  str = Field(description="One-line description of the matched control")


class TermDefinition(BaseModel):
    term:       str
    definition: str


class PolicyElement(BaseModel):
    element_no:  str  = Field(description="'1', '2', '3' …")
    statement:   str  = Field(description="Normative sentence using 'shall'")
    trace:       list[ControlTrace]
    sub_items:   list[str] = Field(default=[], description="Sub-items for element 2 only (2-1 … 2-N)")


class PolicySpec(BaseModel):
    doc_id:      str
    title:       str
    version:     str = "1.0"
    owner:       str = "Cybersecurity Department"
    classification: str = "Confidential — Internal Use Only"

    # Sections (golden policy baseline)
    definitions:          list[TermDefinition]   # 4-10 terms
    objectives:           str                    # CIA + NCA ECC ref
    scope:                str                    # all assets, all personnel
    policy_elements:      list[PolicyElement]    # min 3 elements (1, 2, 3)
    roles_responsibilities: str                  # structured prose
    compliance_clauses:   list[str]              # exactly 3 numbered clauses
    exceptions:           str                    # no bypass without auth
    closing_note:         str                    # approved and in force


class Requirement(BaseModel):
    req_id:    str  = Field(description="'1.1', '1.2' sequential within domain")
    statement: str  = Field(description="Normative sentence using 'shall'")
    guidance:  str  = ""
    trace:     list[ControlTrace]


class DomainBlock(BaseModel):
    domain_no:       int
    title:           str
    objective:       str
    potential_risks: str
    requirements:    list[Requirement]   # min 4 per domain


class StandardSpec(BaseModel):
    doc_id:      str
    title:       str
    version:     str = "1.0"
    owner:       str = "Cybersecurity Department"
    classification: str = "Confidential — Internal Use Only"

    notice:               str   # ownership notice
    definitions:          list[TermDefinition]   # 6-15 terms
    objectives:           str   # CIA + ECC linkage
    scope:                str   # applicability
    exceptions:           str   # written approval required
    domains:              list[DomainBlock]       # min 3 domains
    roles_responsibilities: list[str]             # 3 numbered items
    update_review:        str   # periodic + event triggers
    compliance_clauses:   list[str]               # 3 clauses
    closing_note:         str


class ProcedureStep(BaseModel):
    step_id:    str  = Field(description="'7.1.1', '7.1.2' …")
    actor:      str
    action:     str  = Field(description="Explicit executable action")
    system:     str  = Field(description="System or form used")
    output:     str  = Field(description="Deliverable produced")
    evidence:   str  = Field(description="Audit record generated")
    timing:     str  = Field(description="SLA or deadline")
    next_step:  str  = Field(description="Next step ID or 'Phase complete'")


class ProcedurePhase(BaseModel):
    phase_id:   str   = Field(description="'7.1', '7.2' …")
    title:      str
    objective:  str
    steps:      list[ProcedureStep]   # min 4 steps per phase


class RoleRow(BaseModel):
    role:           str
    responsibility: str


class ProcedureSpec(BaseModel):
    doc_id:           str
    title:            str
    parent_policy:    str
    parent_standard:  str
    version:          str = "1.0"
    owner:            str = "Cybersecurity Department"
    classification:   str = "Confidential — Internal Use Only"

    definitions:    list[TermDefinition]     # 5-15 terms
    objective:      str
    scope:          str
    roles:          list[RoleRow]            # 4-8 roles
    overview:       str
    triggers:       list[str]
    prerequisites:  list[str]
    inputs:         list[str]
    tools:          list[str]
    phases:         list[ProcedurePhase]     # 3-5 phases
    decision_points: list[str]
    exceptions:     str
    escalation:     str
    outputs:        list[str]
    records:        list[str]
    time_controls:  list[str]
    related_docs:   list[str]
    effective_date: str
    review:         str


# ══════════════════════════════════════════════════════════════════════════════
# LangChain drafters
# ══════════════════════════════════════════════════════════════════════════════

def _llm() -> ChatOpenAI:
    return ChatOpenAI(model=_MODEL, temperature=0.2,
                      api_key=OPENAI_API_KEY, max_tokens=8000)


def _load_parent_context(doc_ids: list[str]) -> str:
    """Load summaries from already-generated _en.json files."""
    out_dir = _BACKEND / "policy_output"
    parts = []
    for did in doc_ids:
        # Try big4 first, then _en fallback
        for suffix in (f"{did}_big4.json", f"{did}_en.json", f"{did}.json"):
            p = out_dir / suffix
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    doc_type = data.get("doc_type") or data.get("meta", {}).get("doc_type", "")
                    title    = (data.get("title") or data.get("meta", {}).get("title_en", did))
                    obj      = (data.get("objectives") or data.get("objective_ar", ""))[:500]

                    if doc_type == "policy" or "policy_elements" in data:
                        elems = data.get("policy_elements", [])[:6]
                        body  = "\n".join(f"  - {e.get('statement',e.get('text_ar',''))[:180]}" for e in elems)
                        parts.append(f"[{did}] POLICY: {title}\nObjective: {obj}\nKey policy elements:\n{body}")
                    elif doc_type == "standard" or "domains" in data or "domain_clusters" in data:
                        domains = data.get("domains", data.get("domain_clusters", []))
                        body = "\n".join(f"  - Domain {d.get('domain_no','')}: {d.get('title',d.get('title_ar',''))}" for d in domains)
                        parts.append(f"[{did}] STANDARD: {title}\nObjective: {obj}\nDomains:\n{body}")
                    else:
                        phases = data.get("phases", [])
                        body = "\n".join(f"  - {ph.get('phase_id','')}: {ph.get('title',ph.get('phase_title_ar',''))}" for ph in phases)
                        parts.append(f"[{did}] PROCEDURE: {title}\nObjective: {obj}\nPhases:\n{body}")
                    break
                except Exception:
                    pass
    return "\n\n" + ("─" * 60 + "\n").join(parts) if parts else ""


# ── POLICY ────────────────────────────────────────────────────────────────────

_POLICY_SYSTEM = """\
You are a senior cybersecurity governance consultant at a Big4 firm drafting
ministry-grade cybersecurity policy documents.

Golden Baseline Rules (non-negotiable):
1. TOC must have exactly these 6 sections in order:
   Objectives | Scope and Applicability | Policy Elements |
   Roles and Responsibilities | Policy Compliance | Exceptions
2. Objectives MUST mention Confidentiality, Integrity, Availability (CIA) and
   reference at least one NCA ECC control by ID.
3. Scope MUST state: applies to all information/technology assets and all
   ministry personnel, contractors, and third parties.
4. Policy Elements MUST include at minimum:
   - Element 1: Cybersecurity function defines/documents cyber requirements
   - Element 2: Cybersecurity function develops the policy suite (list 8+ sub-items
     like 2-1 IAM, 2-2 Data Protection, 2-3 Incident Response, etc.)
   - Element 3: Cybersecurity has right to access info to verify compliance
5. Every "shall" statement MUST be traced to a real NCA control from the list provided.
6. Policy Compliance: exactly 3 clauses (continuous compliance / all staff comply /
   violations subject to disciplinary action).
7. Exceptions: "No exception to this policy may be implemented without prior written
   authorization from the Cybersecurity Department or the Cyber Supervisory Committee."
8. Closing note: "This policy and all related cybersecurity policies and standards
   are officially approved and currently in force."
9. Use formal, direct, authoritative government tone. "shall" for obligations.
"""

_POLICY_USER = """\
Draft a complete cybersecurity POLICY document with these parameters:
- Document ID: {doc_id}
- Title: {title}
- Organisation: Ministry of Communications and Information Technology

## Parent Document Context (maintain consistency)
{parent_context}

## Retrieved NCA Controls (you MUST cite real control IDs from this list)
{controls_block}

Produce the full PolicySpec JSON strictly following the schema.
- definitions: 6-10 terms including "the Ministry", "the Minister",
  "ministry personnel", "the policy", "authorized official"
- objectives: 2 paragraphs, mention CIA, cite NCA ECC control IDs
- scope: 1-2 paragraphs covering people, systems, assets
- policy_elements: minimum 4 elements; element 2 must list 10+ sub-items
  (2-1 Governance, 2-2 Risk Management, 2-3 IAM, 2-4 Data Protection,
   2-5 Incident Response, 2-6 Physical Security, 2-7 Network Security,
   2-8 Application Security, 2-9 Business Continuity, 2-10 Third-Party, …)
- Each "shall" statement must have 1-3 trace entries with REAL control IDs
- roles_responsibilities: cover authority/legal/audit/HR/cybersecurity/staff
- compliance_clauses: exactly 3 items
"""


def draft_policy_lc(doc_id: str, title: str,
                    depends_on: list[str] | None = None) -> PolicySpec:
    retriever     = get_retriever()
    controls      = retriever.search(title, top_k=20)
    controls_block = retriever.format_for_prompt(controls)
    parent_ctx    = _load_parent_context(depends_on or [])

    llm    = _llm()
    prompt = ChatPromptTemplate.from_messages([
        ("system", _POLICY_SYSTEM),
        ("human",  _POLICY_USER),
    ])
    chain = prompt | llm.with_structured_output(PolicySpec)

    return chain.invoke({
        "doc_id":          doc_id,
        "title":           title,
        "parent_context":  parent_ctx or "None (this is a foundation document).",
        "controls_block":  controls_block,
    })


# ── STANDARD ──────────────────────────────────────────────────────────────────

_STD_SYSTEM = """\
You are a senior cybersecurity technical standards author at a Big4 firm.

Golden Baseline Rules (non-negotiable):
1. TOC must have exactly these 6 sections:
   Objectives | Scope and Applicability | Standards Requirements |
   Roles and Responsibilities | Update and Review | Compliance with the Standard
2. Objectives MUST mention CIA and NCA ECC regulatory alignment.
3. Scope MUST state applicability to all employees, contractors, service providers,
   and all information/technology assets. Include the exceptions clause VERBATIM:
   "Any exception to this standard must be approved in writing by the Cybersecurity
   Department according to the approved exception and risk acceptance process."
4. Standards Requirements (Section 4): MINIMUM 3 domain blocks.
   Each domain block MUST follow this exact order:
   a) Objective:
   b) Potential Risks:
   c) Requirements: numbered N.1, N.2 … with "shall" statements
5. Every "shall" requirement MUST trace to a real NCA control from the provided list.
6. Roles: 3 numbered items (1- Document Sponsor, 2- Review Owner, 3- Implementation Owner).
7. Update and Review MUST include triggers: major technology changes / policy changes /
   regulatory changes.
8. Compliance: 3 numbered clauses including disciplinary action clause.
9. Closing note: "Only the latest standards published by the organization are official."
"""

_STD_USER = """\
Draft a complete cybersecurity STANDARD document with these parameters:
- Document ID: {doc_id}
- Title: {title}
- Organisation: Ministry of Communications and Information Technology

## Parent Document Context (your standard must implement requirements from these)
{parent_context}

## Retrieved NCA Controls (cite REAL control IDs from this list)
{controls_block}

Produce the full StandardSpec JSON:
- notice: standard legal/ownership notice (2-3 sentences)
- definitions: 8-15 technical operational terms
- objectives: 3-4 paragraphs; cite NCA ECC control IDs explicitly
- scope: full applicability statement + exceptions clause verbatim
- domains: MINIMUM 3 domain blocks, each with 5-8 requirements
  Domain pattern: 1=Governance & Management, 2=Technical Controls,
                  3=Time-Based & Periodic Controls, 4=Assurance & Evidence
- requirements: each uses "shall", numbered 1.1 … 1.N within its domain
- Each requirement must have 1-2 real NCA trace entries
"""


def draft_standard_lc(doc_id: str, title: str,
                      depends_on: list[str] | None = None) -> StandardSpec:
    retriever      = get_retriever()
    controls       = retriever.search(title, top_k=20)
    controls_block = retriever.format_for_prompt(controls)
    parent_ctx     = _load_parent_context(depends_on or [])

    llm    = _llm()
    prompt = ChatPromptTemplate.from_messages([
        ("system", _STD_SYSTEM),
        ("human",  _STD_USER),
    ])
    chain = prompt | llm.with_structured_output(StandardSpec)

    return chain.invoke({
        "doc_id":         doc_id,
        "title":          title,
        "parent_context": parent_ctx or "None — derive from title only.",
        "controls_block": controls_block,
    })


# ── PROCEDURE ─────────────────────────────────────────────────────────────────

_PRC_SYSTEM = """\
You are a senior cybersecurity operations consultant at a Big4 firm drafting
ministry-grade cybersecurity procedure documents.

Golden Baseline Rules (non-negotiable):
1. Section 7 (Detailed Procedure Steps) MUST be the dominant section by content:
   - 3-5 phases (7.1 … 7.N)
   - Each phase MUST have 4-6 steps (7.1.1 … 7.1.N)
   - Each step MUST specify: actor, action, system/form used, output,
     evidence generated, timing/SLA, next step
2. Phases follow the pattern: Initiation → Validation → Review → Approval →
   Execution → Verification → Closure (use what is appropriate)
3. Roles in Section 4 must be specific and execution-linked (not generic governance)
4. Section 6 MUST include Triggers, Prerequisites, Inputs, Tools, Forms tables
5. Section 8 MUST explicitly name escalation authority and fallback paths
6. Section 9 MUST include Records & Evidence table with retention periods
7. Section 10 MUST include measurable SLA timings tied to steps
8. The procedure must operationalize the requirements of its parent policy and standard
9. Every action must be executable by a practitioner without guesswork
"""

_PRC_USER = """\
Draft a complete cybersecurity PROCEDURE document with these parameters:
- Document ID: {doc_id}
- Title: {title}
- Parent Policy: {parent_policy}
- Parent Standard: {parent_standard}
- Organisation: Ministry of Communications and Information Technology

## Parent Documents (your procedure MUST implement these requirements)
{parent_context}

## Retrieved NCA Controls (for context and compliance references)
{controls_block}

Produce the full ProcedureSpec JSON:
- definitions: 8-12 operational/technical terms
- roles: 5-7 execution roles (Requestor, Reviewer, Approver, Executor,
  System Owner, CISO/Escalation, Auditor)
- phases: 4-5 phases, each with 4-6 detailed steps
- Every step MUST have: actor, specific action verb, named system/tool,
  measurable output, specific evidence record, timing SLA
- decision_points: 3-5 explicit if/then branches
- time_controls: specific SLAs (e.g. "Initial response within 4 hours",
  "Approval within 2 business days")
- related_docs: list parent policy, parent standard, and 2-3 related documents
"""


def draft_procedure_lc(doc_id: str, title: str,
                       parent_policy: str, parent_standard: str,
                       depends_on: list[str] | None = None) -> ProcedureSpec:
    retriever      = get_retriever()
    controls       = retriever.search(title, top_k=15)
    controls_block = retriever.format_for_prompt(controls)
    parent_ctx     = _load_parent_context(depends_on or [])

    llm    = _llm()
    prompt = ChatPromptTemplate.from_messages([
        ("system", _PRC_SYSTEM),
        ("human",  _PRC_USER),
    ])
    chain = prompt | llm.with_structured_output(ProcedureSpec)

    return chain.invoke({
        "doc_id":          doc_id,
        "title":           title,
        "parent_policy":   parent_policy,
        "parent_standard": parent_standard,
        "parent_context":  parent_ctx or "Derive context from title and document type.",
        "controls_block":  controls_block,
    })
