"""
Procedure Section Sub-Agents — focused LLM agents for each section group.

Each agent is responsible for exactly one logical section of a ProcedureDraftOutput.
They receive only the control bundles relevant to their section and produce a partial
dict matching the ProcedureDraftOutput fields they own.

Section grouping:
  FrontMatterAgent      → §1-6: definitions, objective, scope, roles, overview, triggers/prereqs/tools
  PhaseAgent            → §7.N: one phase (name, intro, steps[]) — called once per phase
  EvidenceAgent         → §8-10: decisions/exceptions, outputs/records, verification, evidence, time_controls
  GovernanceAgent       → §11-15: related_docs, procedure_review, approval (mostly deterministic + thin LLM)
"""
from __future__ import annotations

import json
from .rate_limited_client import get_openai_client

from ..config import DRAFT_MODEL_POLICY, PLAN_MODEL
from ..models import (
    EntityProfile, DocumentSpec, ControlBundle, AugmentedControlContext,
    ProcedureStep, ProcedurePhase, ProcedureRoleItem,
    ProcedureVerificationCheck, ProcedureDefinition, ProcedureTrigger,
    ProcedureOutputRecord, ProcedureEvidenceRecord, ProcedureTimeControl,
    TraceEntry,
)
from .workflow_models import SectionOutput
from .domain_profiles import DomainProfile


def _bundle_summary(bundles: list[ControlBundle], max_n: int = 30) -> list[dict]:
    """Compact bundle representation for LLM context."""
    return [
        {
            "chunk_id":   b.chunk_id,
            "control_id": b.control_id,
            "framework":  b.framework,
            "title":      b.title,
            "statement":  b.statement[:350],
        }
        for b in bundles[:max_n]
    ]


def _aug_summary(augmented: list[AugmentedControlContext], max_n: int = 20) -> list[dict]:
    return [
        {
            "control_id":             a.control_id,
            "implementation_guidance": a.implementation_guidance,
            "validation_guidance":     a.validation_guidance,
            "nist_supplement":         a.nist_supplement,
        }
        for a in augmented
        if a.implementation_guidance
    ][:max_n]


# ─────────────────────────────────────────────────────────────────────────────
# Front Matter Agent — §1-6
# ─────────────────────────────────────────────────────────────────────────────

_FRONT_MATTER_SCHEMA = {
    "name": "ProcedureFrontMatter",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "definitions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "term": {"type": "string"},
                        "definition": {"type": "string"},
                    },
                    "required": ["term", "definition"],
                    "additionalProperties": False,
                },
            },
            "objective_en": {"type": "string"},
            "scope_en": {"type": "string"},
            "procedure_overview": {"type": "string"},
            "roles_responsibilities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "role_title": {"type": "string"},
                        "responsibilities": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["role_title", "responsibilities"],
                    "additionalProperties": False,
                },
            },
            "triggers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "trigger_id": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["trigger_id", "description"],
                    "additionalProperties": False,
                },
            },
            "prerequisites": {"type": "array", "items": {"type": "string"}},
            "tools_required": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tool_name": {"type": "string"},
                        "purpose": {"type": "string"},
                        "version_guidance": {"type": "string"},
                    },
                    "required": ["tool_name", "purpose", "version_guidance"],
                    "additionalProperties": False,
                },
            },
            "input_forms": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "form_name": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["form_name", "description"],
                    "additionalProperties": False,
                },
            },
        },
        "required": [
            "definitions", "objective_en", "scope_en", "procedure_overview",
            "roles_responsibilities", "triggers", "prerequisites",
            "tools_required", "input_forms",
        ],
        "additionalProperties": False,
    },
}


class FrontMatterAgent:
    """
    LLM sub-agent for §1–6 of a procedure:
      §1 Definitions & Abbreviations
      §2 Procedure Objective
      §3 Scope & Applicability
      §4 Roles & Responsibilities
      §5 Procedure Overview
      §6 Triggers, Prerequisites, Inputs & Tools

    Uses a minimal schema — only the fields it owns.
    """

    def __init__(self):
        self._client = get_openai_client()

    def draft(
        self,
        profile: EntityProfile,
        spec: DocumentSpec,
        bundles: list[ControlBundle],
        domain: DomainProfile,
        qa_findings: list[str] | None = None,
    ) -> SectionOutput:
        print(f"[FrontMatterAgent] Drafting §1-6 for {spec.topic}")

        system_msg = f"""\
You are a Principal Cybersecurity Procedure Architect (Big4, Fortune500 clients).
Draft sections 1-6 ONLY of a cybersecurity procedure for {profile.org_name}.
Topic: {spec.topic} | Sector: {profile.sector} | Jurisdiction: {profile.jurisdiction}
Domain: {domain.name}

SECTION REQUIREMENTS:
§1 DEFINITIONS (min 10 terms):
  - Operational definitions — what each term means in the context of EXECUTING this procedure
  - Include tool names, role names, artefact names specific to {spec.topic}
  - Each definition: 2-4 sentences, not dictionary-style

§2 OBJECTIVE (min 500 words):
  - 4-5 paragraphs: regulatory basis (NCA ECC), threat context, CIA triad relevance,
    operational purpose, intended measurable outcomes
  - Reference specific NCA controls from the provided bundles

§3 SCOPE (min 400 words):
  - In-scope: system categories, asset types, personnel roles, environments (prod/non-prod)
  - Out-of-scope: explicit exclusions with rationale
  - Reference {profile.hosting_model} hosting context

§4 ROLES & RESPONSIBILITIES (min 6 roles):
  - Each role: 8-10 specific, distinct responsibilities as full action sentences
  - Required roles: CISO/Security Director, Security Engineer, SOC Analyst,
    System/Asset Owner, IT Operations, Compliance/GRC Officer
  - Additional domain-specific roles as needed

§5 PROCEDURE OVERVIEW (min 300 words):
  - Narrative description of the end-to-end flow
  - How this procedure connects to parent policy and related procedures
  - Key handover points between phases

§6 TRIGGERS / PREREQUISITES / TOOLS:
  - Triggers: min 5 conditions that initiate this procedure
  - Prerequisites: min 5 items (access rights, system states, tool availability)
  - Tools: min 4 enterprise tools with vendor, version, CLI/API examples
  - Input forms: min 3 forms/tickets/requests that must exist before starting

{domain.system_prompt_extension}

OUTPUT: valid JSON matching the schema. All text fields substantive (no placeholders).
"""

        payload = {
            "topic":           spec.topic,
            "org_name":        profile.org_name,
            "sector":          profile.sector,
            "control_bundles": _bundle_summary(bundles, 25),
        }
        if qa_findings:
            payload["qa_findings_to_fix"] = qa_findings

        try:
            resp = self._client.chat.completions.create(
                model=DRAFT_MODEL_POLICY,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user",   "content": (
                        f"Draft sections 1-6 for the {spec.topic} procedure. "
                        "All fields must be substantive — Fortune500 audit quality. "
                        "Output valid JSON."
                    )},
                    {"role": "user",   "content": json.dumps(payload)},
                ],
                response_format={"type": "json_schema", "json_schema": _FRONT_MATTER_SCHEMA},
                temperature=0.3,
            )
            data = json.loads(resp.choices[0].message.content)
            return SectionOutput(section_id="front_matter", status="ok", data=data)
        except Exception as exc:
            print(f"[FrontMatterAgent] ERROR: {exc}")
            return SectionOutput(section_id="front_matter", status="fail",
                                 data={}, qa_issues=[str(exc)])


# ─────────────────────────────────────────────────────────────────────────────
# Phase Agent — §7.N (one call per phase)
# ─────────────────────────────────────────────────────────────────────────────

_PHASE_SCHEMA = {
    "name": "ProcedurePhaseOutput",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "phase_name": {"type": "string"},
            "phase_intro": {"type": "string"},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "step_no":         {"type": "string"},
                        "phase":           {"type": "string"},
                        "actor":           {"type": "string"},
                        "action":          {"type": "string"},
                        "expected_output": {"type": "string"},
                        "code_block":      {"type": "string"},
                        "citations":       {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["step_no", "phase", "actor", "action",
                                 "expected_output", "code_block", "citations"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["phase_name", "phase_intro", "steps"],
        "additionalProperties": False,
    },
}


class PhaseAgent:
    """
    LLM sub-agent for a single procedure phase (§7.N).

    Receives ONLY the bundles relevant to this phase — not the entire
    document bundle set. This keeps context tight and output focused.

    One call per phase → LLM can devote full attention to the steps.
    """

    def __init__(self):
        self._client = get_openai_client()

    def draft(
        self,
        profile: EntityProfile,
        spec: DocumentSpec,
        phase_index: int,
        phase_name: str,
        bundles: list[ControlBundle],
        augmented: list[AugmentedControlContext],
        domain: DomainProfile,
        all_phase_names: list[str],
        roles: list[str],
        qa_findings: list[str] | None = None,
    ) -> SectionOutput:
        phase_label = f"Phase {phase_index + 1}: {phase_name}"
        print(f"[PhaseAgent] Drafting {phase_label} ({len(bundles)} bundles)")

        prev_phase = all_phase_names[phase_index - 1] if phase_index > 0 else "N/A"
        next_phase = all_phase_names[phase_index + 1] if phase_index < len(all_phase_names) - 1 else "N/A"

        system_msg = f"""\
You are a Principal Cybersecurity Procedure Architect drafting ONE PHASE of a procedure.

Client: {profile.org_name} | Topic: {spec.topic} | Domain: {domain.name}
This phase: {phase_label}
Previous phase: {prev_phase}
Next phase: {next_phase}
Available roles: {', '.join(roles)}

PHASE REQUIREMENTS:

phase_name: exact name of this phase (e.g. "7.{phase_index+1} {phase_name}")

phase_intro (MIN 400 WORDS):
  - Purpose of this phase and what risk/threat it addresses
  - Entry condition: what state must exist before this phase begins
  - Inputs: what artefacts/data/access must be available
  - Key activities summary (before listing steps)
  - Exit condition / handoff to next phase: {next_phase}
  - Regulatory basis: cite the NCA ECC control IDs relevant to this phase

steps (MIN 5 steps, target 6-8):
  Each step:
  • step_no: "7.{phase_index+1}.N" format
  • phase: "{phase_name}"
  • actor: exact role name from the available roles list
  • action (MIN 250 WORDS):
    - Detailed imperative instruction
    - Exact CLI commands, API calls, PowerShell cmdlets, or configuration parameters
    - Specific parameter values, thresholds, flags
    - Security rationale (why this action is required from a risk perspective)
    - What to check if this step fails (failure detection)
    - Tool: {domain.name}-specific enterprise tool name + command
  • expected_output (MIN 180 WORDS):
    - Specific observable, measurable result
    - Exact log entries, system states, configuration values, or report fields to confirm
    - What the auditor will look for to verify this step was performed
    - Specific numeric thresholds or pass/fail criteria
  • code_block: REAL CLI/config snippet (not pseudocode). Empty string "" only if purely administrative.
  • citations: chunk_ids from control_bundles that ground this step (min 1 per step)

DOMAIN CONTEXT:
{domain.system_prompt_extension}
"""

        payload = {
            "phase_name":          phase_name,
            "phase_index":         phase_index,
            "topic":               spec.topic,
            "control_bundles":     _bundle_summary(bundles, 30),
            "augmented_guidance":  _aug_summary(augmented, 15),
        }
        if qa_findings:
            payload["qa_findings_to_fix"] = qa_findings

        try:
            resp = self._client.chat.completions.create(
                model=DRAFT_MODEL_POLICY,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user",   "content": (
                        f"Draft {phase_label} completely. "
                        "phase_intro must be 400+ words with entry/exit conditions, threat context, and regulatory basis. "
                        "Each step: 250+ word action, 180+ word expected_output, real CLI commands. "
                        "Ground every step in chunk_ids from control_bundles. "
                        "Output valid JSON."
                    )},
                    {"role": "user",   "content": json.dumps(payload)},
                ],
                response_format={"type": "json_schema", "json_schema": _PHASE_SCHEMA},
                temperature=0.25,
            )
            data = json.loads(resp.choices[0].message.content)
            return SectionOutput(section_id=f"phase_{phase_index}", status="ok", data=data)
        except Exception as exc:
            print(f"[PhaseAgent] Phase {phase_index} ERROR: {exc}")
            return SectionOutput(section_id=f"phase_{phase_index}", status="fail",
                                 data={}, qa_issues=[str(exc)])


# ─────────────────────────────────────────────────────────────────────────────
# Evidence Agent — §8-10
# ─────────────────────────────────────────────────────────────────────────────

_EVIDENCE_SCHEMA = {
    "name": "ProcedureEvidenceSection",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "decision_points_and_escalations": {"type": "string"},
            "exception_handling_en": {"type": "string"},
            "verification_checks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "check_id":         {"type": "string"},
                        "description":      {"type": "string"},
                        "evidence_artifact": {"type": "string"},
                    },
                    "required": ["check_id", "description", "evidence_artifact"],
                    "additionalProperties": False,
                },
            },
            "evidence_collection": {"type": "array", "items": {"type": "string"}},
            "output_records": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "record_id":    {"type": "string"},
                        "record_name":  {"type": "string"},
                        "description":  {"type": "string"},
                        "owner":        {"type": "string"},
                        "retention":    {"type": "string"},
                    },
                    "required": ["record_id", "record_name", "description", "owner", "retention"],
                    "additionalProperties": False,
                },
            },
            "time_controls": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "control_id":  {"type": "string"},
                        "activity":    {"type": "string"},
                        "sla":         {"type": "string"},
                        "escalation":  {"type": "string"},
                    },
                    "required": ["control_id", "activity", "sla", "escalation"],
                    "additionalProperties": False,
                },
            },
        },
        "required": [
            "decision_points_and_escalations", "exception_handling_en",
            "verification_checks", "evidence_collection", "output_records", "time_controls",
        ],
        "additionalProperties": False,
    },
}


class EvidenceAgent:
    """
    LLM sub-agent for §8–10:
      §8  Decision Points, Exceptions & Escalations
      §9  Outputs, Records, Evidence & Forms
      §10 Time Controls, Service Levels & Control Checkpoints
    """

    def __init__(self):
        self._client = get_openai_client()

    def draft(
        self,
        profile: EntityProfile,
        spec: DocumentSpec,
        phases_summary: list[dict],
        bundles: list[ControlBundle],
        domain: DomainProfile,
        qa_findings: list[str] | None = None,
    ) -> SectionOutput:
        print(f"[EvidenceAgent] Drafting §8-10 for {spec.topic}")

        system_msg = f"""\
You are a Principal Cybersecurity Procedure Architect drafting sections 8-10 of a procedure.

Client: {profile.org_name} | Topic: {spec.topic} | Domain: {domain.name}

§8 DECISION POINTS & EXCEPTION HANDLING (min 1200 words total):
  decision_points_and_escalations (min 700 words):
    - Decision matrix: for each major branching point in the procedure, state:
      * Condition being evaluated
      * Each possible outcome and the action taken
      * Role responsible for the decision
      * Maximum time allowed before escalation
    - Escalation matrix: L1 → L2 → CISO → Board (with names/roles and SLAs)
    - Rollback procedure: exact steps to reverse changes if procedure fails
    - Communication plan: who is notified at each decision point
  exception_handling_en (min 500 words):
    - Categories of exceptions (technical, operational, business)
    - Risk acceptance workflow: who approves, what documentation required
    - Compensating controls: what must be in place during exception period
    - Exception duration: maximum period, renewal process
    - Post-exception review: lessons-learned process

§9 OUTPUTS, RECORDS & EVIDENCE (min 12 verification checks):
  verification_checks: each check must have:
    - check_id: "VC-N" format
    - description (min 200 words): what is being verified, why it matters, exact method of verification,
      what a PASS looks like vs FAIL, who performs the check, frequency
    - evidence_artifact: EXACT file path, log location, system screen, report name, or ticket reference
  evidence_collection: min 8 specific artefact descriptions with file paths or system locations
  output_records: min 6 records with retention periods (align to NCA ECC data retention requirements)

§10 TIME CONTROLS & SLAs (min 8 entries):
  - One entry per major procedure activity or phase
  - SLA stated in precise units (hours, business days)
  - Escalation path if SLA breached

DOMAIN CONTEXT:
{domain.system_prompt_extension}
"""

        payload = {
            "topic":           spec.topic,
            "phases_summary":  phases_summary,
            "control_bundles": _bundle_summary(bundles, 25),
        }
        if qa_findings:
            payload["qa_findings_to_fix"] = qa_findings

        try:
            resp = self._client.chat.completions.create(
                model=DRAFT_MODEL_POLICY,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user",   "content": (
                        "Draft sections 8-10 completely. "
                        "decision_points_and_escalations: 700+ words with full escalation matrix. "
                        "exception_handling_en: 500+ words with risk acceptance workflow. "
                        "verification_checks: min 12 checks, each description 200+ words. "
                        "evidence_collection: min 8 artefacts with exact paths. "
                        "time_controls: min 8 entries with precise SLAs. "
                        "Output valid JSON."
                    )},
                    {"role": "user",   "content": json.dumps(payload)},
                ],
                response_format={"type": "json_schema", "json_schema": _EVIDENCE_SCHEMA},
                temperature=0.3,
            )
            data = json.loads(resp.choices[0].message.content)
            return SectionOutput(section_id="evidence", status="ok", data=data)
        except Exception as exc:
            print(f"[EvidenceAgent] ERROR: {exc}")
            return SectionOutput(section_id="evidence", status="fail",
                                 data={}, qa_issues=[str(exc)])


# ─────────────────────────────────────────────────────────────────────────────
# Section Repair Agent — targeted re-draft of a failing section
# ─────────────────────────────────────────────────────────────────────────────

class SectionRepairAgent:
    """
    Targeted repair agent — re-drafts a specific failing section without
    touching passing sections. Called when structural/QA validation fails
    on a specific section_id.
    """

    def __init__(self):
        self._client = get_openai_client()
        self._front_matter = FrontMatterAgent()
        self._phase        = PhaseAgent()
        self._evidence     = EvidenceAgent()

    def repair(
        self,
        section_id: str,
        original: SectionOutput,
        qa_issues: list[str],
        profile: EntityProfile,
        spec: DocumentSpec,
        bundles: list[ControlBundle],
        domain: DomainProfile,
        **kwargs,
    ) -> SectionOutput:
        """Re-draft the failing section with qa_issues as explicit fix instructions."""
        print(f"[SectionRepairAgent] Repairing {section_id}: {len(qa_issues)} issues")
        combined_issues = [f"{i+1}. {issue}" for i, issue in enumerate(qa_issues)]

        if section_id == "front_matter":
            return self._front_matter.draft(profile, spec, bundles, domain,
                                            qa_findings=combined_issues)
        elif section_id.startswith("phase_"):
            idx = int(section_id.split("_")[1])
            return self._phase.draft(
                profile, spec, idx,
                kwargs.get("phase_name", f"Phase {idx+1}"),
                bundles, kwargs.get("augmented", []), domain,
                kwargs.get("all_phase_names", []),
                kwargs.get("roles", []),
                qa_findings=combined_issues,
            )
        elif section_id == "evidence":
            return self._evidence.draft(profile, spec,
                                        kwargs.get("phases_summary", []),
                                        bundles, domain,
                                        qa_findings=combined_issues)
        else:
            print(f"[SectionRepairAgent] No repair handler for {section_id}")
            return original
