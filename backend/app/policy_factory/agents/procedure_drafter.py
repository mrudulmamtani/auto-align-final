"""
Procedure Drafting Agent — Big4 consulting grade, Fortune500 audience.

Dedicated agent for PRC-* documents. Generates fully executable 15-section
cybersecurity operational procedures for enterprise environments. References
real enterprise tools (CrowdStrike, Splunk, SailPoint, CyberArk, Tenable, etc.)
with actual CLI/API syntax. Every step grounded in NCA control bundles.

15 sections per procedure.json schema:
  1. Definitions & Abbreviations
  2. Procedure Objective
  3. Scope & Applicability
  4. Roles & Responsibilities
  5. Procedure Overview
  6. Triggers, Prerequisites, Inputs & Tools
  7. Detailed Procedure Steps          ← DOMINANT (40–60%)
  8. Decision Points, Exceptions & Escalations
  9. Outputs, Records, Evidence & Forms
 10. Time Controls, Service Levels & Control Checkpoints
 11. Related Documents
 12. Effective Date                    (metadata)
 13. Procedure Review
 14. Review & Approval
 15. Version Control                   (metadata)
 Appendix: Swimlane diagram + Flowchart
"""
from __future__ import annotations

import json
from .rate_limited_client import get_openai_client

from ..config import DRAFT_MODEL_POLICY
from .domain_profiles import detect_procedure_domain
from ..schema_loader import schema_as_prompt_text
from ..models import (
    EntityProfile, DocumentSpec, ControlBundle, AugmentedControlContext,
    ProcedureDraftOutput, ProcedureRoleItem, ProcedureStep, ProcedurePhase,
    ProcedureVerificationCheck, ProcedureDefinition, ProcedureTrigger,
    ProcedureInputForm, ProcedureOutputRecord, ProcedureEvidenceRecord,
    ProcedureTimeControl, TraceEntry,
)

# ── Enterprise tool reference library (Big4 knowledge base) ───────────────────
# Compiled from Fortune500 engagements: real product names, vendors, CLI syntax.

ENTERPRISE_TOOLS = """
IDENTITY & ACCESS MANAGEMENT (IAM/IGA):
  • SailPoint IdentityNow / IdentityIQ — REST API: GET /v3/accounts, POST /v3/provisioning-policies
  • Microsoft Entra ID (Azure AD) + Entra ID Governance — CLI: az ad user list, az ad group member list
  • Saviynt Enterprise Identity Cloud — SCIM API, REST governance workflows
  • Okta Identity Cloud — Okta CLI: okta login; API: /api/v1/users, /api/v1/groups
  • ForgeRock / Ping Identity — REST: /openidm/managed/user, /openam/json/realms/root/authenticate

PRIVILEGED ACCESS MANAGEMENT (PAM):
  • CyberArk Privileged Access Manager (PAM) — PACLI: CreateUser, AddSafe, AddMember
    REST API: /PasswordVault/API/Accounts, /PasswordVault/API/Users
  • BeyondTrust Password Safe — REST API: /BeyondTrust/api/public/v3/Accounts
  • Delinea Secret Server (formerly Thycotic) — REST: /api/v1/secrets, /api/v1/reports
  • CyberArk Conjur — CLI: conjur variable set -i policy/db/password -v <value>

ENDPOINT DETECTION & RESPONSE (EDR/XDR):
  • CrowdStrike Falcon (Falcon Insight XDR, Falcon Prevent) — API: /devices/queries/devices/v1
    CLI (RTR): runscript --CloudFile='script.ps1'; falconctl get --cid
  • SentinelOne Singularity XDR — API: /web/api/v2.1/agents, /web/api/v2.1/threats
    CLI: sentinelctl status, sentinelctl config
  • Microsoft Defender XDR (Defender for Endpoint P2) — PS: Get-MpComputerStatus,
    Set-MpPreference; API: /api/machines, /api/alerts
  • Palo Alto Cortex XDR — REST API: /public_api/v1/endpoints/get_endpoint/
  • Tanium — CLI: tanium-cli ask "Get Running Services from all machines"

SIEM / SOAR:
  • Splunk Enterprise Security — SPL: index=security sourcetype=WinEventLog | stats count by EventCode
    CLI: splunk search '...' -auth admin:pass; REST: /services/search/jobs
  • Microsoft Sentinel — KQL: SecurityEvent | where EventID == 4625 | summarize count() by Account
    CLI: az sentinel alert-rule list --workspace-name <ws> --resource-group <rg>
  • IBM QRadar SIEM + SOAR — API: /api/siem/offenses, /api/analytics/rules
    AQL: SELECT sourceip, destinationip FROM events WHERE category=1002
  • Palo Alto XSIAM — REST API: /public_api/v1/incidents/get_incidents/
  • Exabeam Fusion — REST: /uba/api/users, /uba/api/sessions

VULNERABILITY MANAGEMENT:
  • Tenable.io / Tenable.sc / Nessus — API: GET /scans, POST /scans/{id}/launch
    CLI: nessuscli scan list; nessuscli fetch --report <scan_id> --format pdf
  • Qualys VMDR — API: /api/2.0/fo/scan/?action=launch; CLI: qualys-scan --target <ip>
  • Rapid7 InsightVM — REST: /api/3/scans, /api/3/assets/{id}/vulnerabilities
  • Wiz — CLI: wiz scan --target <image>; API: GraphQL queries via wiz.io

CLOUD SECURITY (CSPM / CWPP):
  • Palo Alto Prisma Cloud — API: /login, /v2/inventory; CLI: twistcli images scan
  • Wiz Cloud Security Platform — GraphQL API for cloud graph queries
  • Microsoft Defender for Cloud — CLI: az security assessment list; az security alert list
  • AWS Security Hub + GuardDuty + Inspector — CLI: aws securityhub get-findings,
    aws guardduty list-findings, aws inspector2 list-findings
  • Orca Security — REST API for cloud asset inventory and vulnerability queries

NETWORK SECURITY:
  • Palo Alto Networks NGFW + Panorama — CLI: show security policy, show system info
    API: /api/?type=op&cmd=<show><config><running/></config></show>
  • Cisco Secure Firewall (Firepower) + FMC — REST: /api/fmc_config/v1/domain/{id}/policy/accesspolicies
    CLI: show access-list, show conn count
  • Fortinet FortiGate + FortiManager — CLI: diagnose debug flow, get system status
    API: /api/v2/monitor/firewall/policy/select
  • Zscaler ZIA / ZPA — API: /api/v1/urlFilteringRules, /api/v1/appConnectors

DATA LOSS PREVENTION (DLP):
  • Microsoft Purview Information Protection + DLP — PS: Get-DlpCompliancePolicy,
    New-DlpCompliancePolicy; Purview portal compliance centre
  • Proofpoint Email Protection + TAP — API: /v2/siem/all; TRAP: /api/forensics
  • Forcepoint DLP — Management Console + REST API for policy deployment

GRC / TICKETING:
  • ServiceNow GRC + IRM — REST: /api/now/table/sn_risk_risk, /api/now/table/sn_compliance_task
    CLI: snow import --table sn_grc_issue
  • Archer GRC Platform — REST: /api/core/security/login; record management APIs
  • Jira Service Management — REST: /rest/api/3/issue; automation rules for risk tickets

PATCH MANAGEMENT:
  • Tanium Patch — Tanium API: GET /plugin/products/patch/patches
  • Microsoft Endpoint Configuration Manager (MECM) + Intune — PS: Get-CMSoftwareUpdate,
    Start-CMSoftwareUpdateDeployment; Intune Graph API: /deviceManagement/windowsAutopilotDeviceIdentities
  • Ivanti Neurons for Patch Management — REST: /api/patch/v1/scans
  • Automox — REST API: GET /orgs/{id}/packages; axclient.exe scan

CERTIFICATE / PKI:
  • Venafi Trust Protection Platform — REST: /vedsdk/Certificates/Retrieve
  • DigiCert CertCentral — API: /services/v2/certificate; CLI: dcnc issue
  • Microsoft AD CS — PS: Get-CertificationAuthority, certreq -submit; certutil -viewstore

SECRETS / VAULT:
  • HashiCorp Vault Enterprise — CLI: vault kv get secret/db/password,
    vault auth enable ldap; API: GET /v1/secret/data/{path}
  • AWS Secrets Manager — CLI: aws secretsmanager get-secret-value --secret-id <name>
  • Azure Key Vault — CLI: az keyvault secret show --name <name> --vault-name <vault>

BACKUP & RECOVERY:
  • Veeam Data Platform — PS: Get-VBRBackup, Start-VBRBackup, Start-VBRRestoreVM
    REST: /api/v1/backupInfrastructure/repositories
  • Rubrik Security Cloud — CLI: rubrik get-vmware-vm; API: /api/v1/vmware/vm
  • Cohesity DataProtect — REST: /irisservices/api/v1/public/protectionJobs

EMAIL SECURITY:
  • Proofpoint Email Protection — API: /v2/siem/all; TAP Dashboard API
  • Mimecast Email Security — API: /api/email/get-email-logs
  • Microsoft Defender for Office 365 — PS: Get-MailDetailATPReport; New-AntiPhishPolicy
"""


# ── OpenAI Structured Output schema (full 15-section) ─────────────────────────

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

_STEP_SCHEMA = {
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
    "required": ["step_no", "phase", "actor", "action", "expected_output",
                 "code_block", "citations"],
    "additionalProperties": False,
}

_PROCEDURE_SCHEMA = {
    "name": "ProcedureDraftOutput",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            # Metadata
            "doc_id":             {"type": "string"},
            "title_en":           {"type": "string"},
            "version":            {"type": "string"},
            "effective_date":     {"type": "string"},
            "owner":              {"type": "string"},
            "classification":     {"type": "string"},
            "parent_policy_id":   {"type": "string"},
            "parent_standard_id": {"type": "string"},
            # § 1 — Definitions
            "definitions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "term":       {"type": "string"},
                        "definition": {"type": "string"},
                    },
                    "required": ["term", "definition"],
                    "additionalProperties": False,
                }
            },
            # § 2 — Objective
            "objective_en": {"type": "string"},
            # § 3 — Scope
            "scope_en": {"type": "string"},
            # § 4 — Roles
            "roles_responsibilities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "role_title":       {"type": "string"},
                        "responsibilities": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["role_title", "responsibilities"],
                    "additionalProperties": False,
                }
            },
            # § 5 — Overview
            "procedure_overview": {"type": "string"},
            # § 6 — Triggers, Prerequisites, Inputs, Tools
            "triggers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "trigger":     {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["trigger", "description"],
                    "additionalProperties": False,
                }
            },
            "prerequisites":  {"type": "array", "items": {"type": "string"}},
            "tools_required": {"type": "array", "items": {"type": "string"}},
            "input_forms": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "form_name":  {"type": "string"},
                        "purpose":    {"type": "string"},
                        "reference":  {"type": "string"},
                    },
                    "required": ["form_name", "purpose", "reference"],
                    "additionalProperties": False,
                }
            },
            # § 7 — Detailed Procedure Steps
            "phases": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "phase_name":  {"type": "string"},
                        "phase_intro": {"type": "string"},
                        "steps":       {"type": "array", "items": _STEP_SCHEMA},
                    },
                    "required": ["phase_name", "phase_intro", "steps"],
                    "additionalProperties": False,
                }
            },
            # § 8 — Decision Points, Exceptions & Escalations
            "decision_points_and_escalations": {"type": "string"},
            "exception_handling_en":           {"type": "string"},
            # § 9 — Outputs, Records, Evidence
            "outputs_records": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "output":                    {"type": "string"},
                        "recipient_or_destination":  {"type": "string"},
                    },
                    "required": ["output", "recipient_or_destination"],
                    "additionalProperties": False,
                }
            },
            "evidence_records": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "record_or_evidence": {"type": "string"},
                        "owner":              {"type": "string"},
                        "retention":          {"type": "string"},
                        "storage_location":   {"type": "string"},
                    },
                    "required": ["record_or_evidence", "owner", "retention", "storage_location"],
                    "additionalProperties": False,
                }
            },
            "verification_checks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "check_id":          {"type": "string"},
                        "description":       {"type": "string"},
                        "method":            {"type": "string"},
                        "expected_result":   {"type": "string"},
                        "evidence_artifact": {"type": "string"},
                    },
                    "required": ["check_id", "description", "method",
                                 "expected_result", "evidence_artifact"],
                    "additionalProperties": False,
                }
            },
            "evidence_collection": {"type": "array", "items": {"type": "string"}},
            # § 10 — Time Controls & SLAs
            "time_controls": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "activity_or_step":        {"type": "string"},
                        "service_level":           {"type": "string"},
                        "responsible_role":        {"type": "string"},
                        "escalation_if_breached":  {"type": "string"},
                    },
                    "required": ["activity_or_step", "service_level",
                                 "responsible_role", "escalation_if_breached"],
                    "additionalProperties": False,
                }
            },
            # § 11 — Related Documents
            "related_documents": {"type": "array", "items": {"type": "string"}},
            # § 13 — Procedure Review
            "procedure_review": {"type": "string"},
            # § 14 — Review & Approval
            "review_and_approval": {"type": "string"},
            # Diagrams (Appendix)
            "swimlane_diagram": {"type": "string"},
            "flowchart_diagram": {"type": "string"},
        },
        "required": [
            "doc_id", "title_en", "version", "effective_date", "owner", "classification",
            "parent_policy_id", "parent_standard_id",
            # All 15 sections (12 = effective_date already in metadata, 15 = version)
            "definitions", "objective_en", "scope_en", "roles_responsibilities",
            "procedure_overview", "triggers", "prerequisites", "tools_required", "input_forms",
            "phases", "decision_points_and_escalations", "exception_handling_en",
            "outputs_records", "evidence_records", "verification_checks", "evidence_collection",
            "time_controls", "related_documents", "procedure_review", "review_and_approval",
            "swimlane_diagram", "flowchart_diagram",
        ],
        "additionalProperties": False,
    }
}


class ProcedureDraftingAgent:
    """
    Big4-grade Procedure Authoring Agent.

    Produces 15-section, audit-ready cybersecurity operational procedures for
    Fortune500 and government ministry clients. References real enterprise tools
    with actual CLI/API syntax. Steps are executable by practitioners without
    guesswork. Evidence collection aligned to SOC 2, ISO 27001, and NCA audit cycles.
    """

    def __init__(self):
        self._client = get_openai_client()

    def draft(
        self,
        profile: EntityProfile,
        spec: DocumentSpec,
        bundles: list[ControlBundle],
        augmented_contexts: list[AugmentedControlContext],
        doc_id: str,
        qa_findings: list[str] | None = None,
    ) -> ProcedureDraftOutput:
        print(f"[ProcedureDrafter] Compiling {doc_id} | {spec.topic} | "
              f"{len(bundles)} bundles | {len(augmented_contexts)} contexts | "
              f"model={DRAFT_MODEL_POLICY}")
        domain = detect_procedure_domain(spec.topic)
        print(f"[ProcedureDrafter] Domain profile: {domain.name}")

        schema_text = schema_as_prompt_text("procedure")
        bundle_list = _bundle_list(bundles)
        aug_list = [
            {
                "control_id":              a.control_id,
                "chunk_id":                a.chunk_id,
                "implementation_guidance": a.implementation_guidance,
                "validation_guidance":     a.validation_guidance,
                "gap_detected":            a.gap_detected,
                "gap_type":                a.gap_type,
                "nist_supplement":         a.nist_supplement,
            }
            for a in augmented_contexts
            if a.implementation_guidance
        ]

        system_msg = f"""\
You are a Principal Cybersecurity Procedure Architect at a Big4 advisory firm.
You author ENTERPRISE CYBERSECURITY OPERATIONAL PROCEDURES for Fortune500 corporations
and government ministries. Your procedures are implemented by security engineering teams,
reviewed by external auditors (NCA, ISO 27001, SOC 2, PCI-DSS), and executed by
Level-3 practitioners. Every step must be unambiguous, role-attributed, and evidence-producing.

CLIENT: {profile.org_name} | Sector: {profile.sector} | Jurisdiction: {profile.jurisdiction}
Hosting: {profile.hosting_model} | SOC: {profile.soc_model}
Critical systems: {', '.join(profile.critical_systems) or 'Not specified'}
OT presence: {profile.ot_presence}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AUTHORITATIVE DOCUMENT SCHEMA (overrides all templates)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{schema_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMPILER WORKFLOW — GENERATE ALL 15 SECTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. AST Construction (all nodes mandatory):
   DocumentAST {{
     Metadata: doc_id, title, version, effective_date, owner, classification,
               parent_policy_id, parent_standard_id
     § 1   definitions            (min 8 operational terms with execution-focused definitions)
     § 2   objective_en           (4–5 paragraphs: purpose, regulatory basis, threat context, CIA impact, intended outcome)
     § 3   scope_en               (1–2 paragraphs + categorised bullets)
     § 4   roles_responsibilities (table: role | responsibility — min 6 roles)
     § 5   procedure_overview     (narrative + high-level process summary)
     § 6   triggers + prerequisites + tools_required + input_forms
     § 7   phases                 ← DOMINANT: 40–60% of document
             Phase 7.1  Initiation & Planning
             Phase 7.2  Preparation & Staging
             Phase 7.3  Implementation & Execution
             Phase 7.4  Verification & Testing
             Phase 7.5  Documentation & Closure
             Phase 7.6  Ongoing Monitoring (if operationally relevant)
     § 8   decision_points_and_escalations + exception_handling_en
     § 9   outputs_records + evidence_records + verification_checks + evidence_collection
     § 10  time_controls          (SLA table per phase/step)
     § 11  related_documents      (parent policy + standard + related procedures + forms)
     § 12  effective_date         (in metadata)
     § 13  procedure_review       (annual cadence + 3 out-of-cycle triggers)
     § 14  review_and_approval    (prepared → reviewed → recommended → approved chain)
     § 15  version_control        (in metadata as version)
     Appendix A: swimlane_diagram (PlantUML @startuml activity diagram with swimlanes)
     Appendix B: flowchart_diagram (PlantUML @startuml activity diagram flowchart)
   }}
2. Section 7 MUST be the dominant section (40–60% of total words).
3. Each phase MUST have: phase_intro (350+ words) + 4–7 numbered steps.
4. Total steps across all phases: MINIMUM 28 steps.
5. Every step MUST have: actor, action (200+ words with exact commands), expected_output
   (150+ words with measurable outcomes), code_block (real CLI/config or "" if none), citations.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FRAMEWORK HIERARCHY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRIMARY  : NCA_ECC, NCA_CSCC, NCA_CCC, NCA_DCC, NCA_TCC, NCA_OSMACC, NCA_NCS
SECONDARY: NIST_80053 (SP 800-53 Rev 5)
NAME ONLY: ISO/IEC 27001:2022 | NIST CSF 2.0 | CIS Controls v8

Citations in steps: chunk_ids from control_bundles. No fabricated IDs.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ENTERPRISE TOOL REFERENCE LIBRARY
(Use real product names, vendor names, CLI/API syntax appropriate to {spec.topic})
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{ENTERPRISE_TOOLS}

TOOL SELECTION GUIDANCE for topic "{spec.topic}" in {profile.sector} sector:
  • Select tools relevant to this specific procedure topic.
  • Reference {profile.hosting_model} hosting tools where applicable.
  • For cloud environments: include AWS/Azure/GCP native services + CSPM tools.
  • For on-premise: include directory services (AD), SCCM, SIEM on-prem variants.
  • Include specific CLI commands, PowerShell cmdlets, or API calls in code_block fields.
  • Name vendor products in tools_required with version guidance (e.g., "CrowdStrike Falcon
    Sensor v7.x — Falcon Insight XDR module required").

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ABSOLUTE RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. ALL 15 SECTIONS MUST BE PRESENT AND POPULATED. Empty sections = document rejected.
2. tools_required: min 3 enterprise tools with vendor, product name, and version info.
3. roles_responsibilities: min 6 roles including CISO/Security Director, Security Engineer,
   SOC Analyst, System/Asset Owner, IT Operations, Compliance/GRC Officer.
4. phases: min 5 phases (7.1–7.5+); total steps ≥ 28.
5. Each step action: 200+ words with exact commands, parameters, expected system states.
6. verification_checks: min 12 checks; each description 180+ words.
7. evidence_records: min 8 records with specific file paths, log locations, retention periods.
8. time_controls: min 8 entries covering each phase with SLA and escalation path.
9. decision_points_and_escalations: 1000+ words covering all branching scenarios,
   escalation matrix (L1 → L2 → CISO), rollback procedures, and risk acceptance workflow.
10. swimlane_diagram: valid PlantUML @startuml...@enduml activity diagram with swimlanes.

    !! CRITICAL: If the generated diagram would produce overlapping elements in PlantUML,
       restructure the flow until the diagram is vertically linear and branch-safe. !!

    STRUCTURAL RULES:
    - Declare each role as: |Role Name|
    - Flow must be TOP-TO-BOTTOM only — never left-to-right
    - Every activity node: |Role|\n:Activity description;
    - Each activity has exactly ONE incoming arrow and ONE outgoing arrow
    - Never place two activities at the same vertical level

    DECISION RULES — strict pattern only:
      if (Condition?) then (Yes)
          :Action;
      else (No)
          :Alternate action;
      endif
    - Decision must immediately follow the activity that produces the condition
    - Both branches MUST reconnect with endif before continuing
    - NEVER stack two decisions without an activity between them
    - Never create uncontrolled branch joins (all branches must use endif)

    LIMITS (hard cap per swimlane diagram):
    - Max 20 activities, max 6 decisions, max 6 swimlane roles
    - If the procedure is longer, cover only the 3 most critical phases here

    REQUIRED skinparam block (must appear right after @startuml):
    skinparam shadowing false
    skinparam activityBorderColor #333333
    skinparam activityBackgroundColor #F7F7F7
    skinparam activityDiamondBackgroundColor #FFF2CC
    skinparam activityDiamondBorderColor #333333
    skinparam activityFontSize 12
    skinparam activityFontName Arial
    skinparam ArrowThickness 1
    skinparam ArrowColor #444444

11. flowchart_diagram: valid PlantUML @startuml...@enduml activity diagram flowchart.

    !! CRITICAL: If the generated diagram would produce overlapping elements in PlantUML,
       restructure the flow until the diagram is vertically linear and branch-safe. !!

    - Use partition "Phase Name" blocks to group steps by procedure phase
    - Include if/then/else for decisions, start/stop terminals
    - Each decision must have exactly two branches that rejoin with endif
    - NEVER stack two decisions without an intervening :activity;
    - Must be DISTINCT from swimlane — emphasise decision logic and exception paths
    - Include the same skinparam block (shadowing false, fonts, arrow styling)
    - Max 20 activities, max 6 decisions per flowchart diagram
12. procedure_review: annual cadence + 3 triggers (tech changes, policy changes, regulatory changes).
13. related_documents: include parent policy ID, parent standard ID, at least 3 related docs.
14. evidence_collection: min 5 artifacts with file paths or system locations.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DOMAIN-SPECIFIC REQUIREMENTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{domain.system_prompt_extension}

PHASE STRUCTURE GUIDANCE:
{domain.phase_guidance}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BIG4 PROCEDURE STANDARDS (Fortune500 quality)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Steps must be executable by a skilled practitioner without reference to other documents.
• Include specific parameter values, thresholds, and configuration settings.
• Code blocks: actual CLI syntax for the named enterprise tool (not pseudocode).
• Risk language: each phase_intro should identify what risk is being mitigated.
• Audit language: every evidence_record must state where an auditor will look to verify.
• SLA precision: hours/days, not vague "timely" language.
• Exception escalation must name roles and maximum wait times before escalation.
• Procedure must render as 30–40 Word pages. The dominant section (§7) alone should fill 18–22 pages.
• Definitions must be operational — what the term means in the context of executing this procedure.
"""

        user_payload: dict = {
            "doc_id":             doc_id,
            "org_name":           profile.org_name,
            "sector":             profile.sector,
            "jurisdiction":       profile.jurisdiction,
            "topic":              spec.topic,
            "version":            spec.version,
            "control_bundles":    bundle_list,
            "augmented_guidance": aug_list,
        }
        if qa_findings:
            user_payload["qa_findings_to_fix"] = qa_findings

        resp = self._client.chat.completions.create(
            model=DRAFT_MODEL_POLICY,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": (
                    f"Compile the complete 15-section Cybersecurity Procedure for {profile.org_name}. "
                    f"Topic: {spec.topic}. "
                    "ALL 15 sections must be populated. "
                    "Section 7 (detailed steps) must be 40–60% of content with min 20 steps across 5 phases. "
                    "Reference real enterprise tools with actual CLI/API commands. "
                    "Ground steps in chunk_ids from control_bundles. "
                    "Use augmented_guidance for implementation depth. "
                    "Both PlantUML diagrams (swimlane + flowchart) are MANDATORY — use @startuml...@enduml syntax. "
                    "Fortune500/Big4 quality — every field must be substantive. "
                    "Output valid JSON matching the schema."
                )},
                {"role": "user", "content": json.dumps(user_payload)},
            ],
            response_format={"type": "json_schema", "json_schema": _PROCEDURE_SCHEMA},
            temperature=0.2,
        )

        raw = json.loads(resp.choices[0].message.content)
        return _parse_procedure(raw, doc_id, spec)


def _parse_procedure(raw: dict, doc_id: str, spec) -> ProcedureDraftOutput:
    """Parse raw JSON into ProcedureDraftOutput, mapping all 15 sections."""
    roles = [
        ProcedureRoleItem(
            role_title       = r["role_title"],
            responsibilities = r["responsibilities"],
        )
        for r in raw["roles_responsibilities"]
    ]

    phases = []
    for ph in raw["phases"]:
        steps = [
            ProcedureStep(
                step_no         = s["step_no"],
                phase           = s["phase"],
                actor           = s["actor"],
                action          = s["action"],
                expected_output = s["expected_output"],
                code_block      = s.get("code_block", ""),
                citations       = s.get("citations", []),
            )
            for s in ph["steps"]
        ]
        phases.append(ProcedurePhase(
            phase_name  = ph["phase_name"],
            phase_intro = ph.get("phase_intro", ""),
            steps       = steps,
        ))

    verifications = [
        ProcedureVerificationCheck(
            check_id          = v["check_id"],
            description       = v["description"],
            method            = v["method"],
            expected_result   = v["expected_result"],
            evidence_artifact = v["evidence_artifact"],
        )
        for v in raw["verification_checks"]
    ]

    definitions = [
        ProcedureDefinition(term=d["term"], definition=d["definition"])
        for d in raw.get("definitions", [])
    ]
    triggers = [
        ProcedureTrigger(trigger=t["trigger"], description=t["description"])
        for t in raw.get("triggers", [])
    ]
    input_forms = [
        ProcedureInputForm(
            form_name = f["form_name"],
            purpose   = f["purpose"],
            reference = f["reference"],
        )
        for f in raw.get("input_forms", [])
    ]
    outputs_records = [
        ProcedureOutputRecord(
            output                   = o["output"],
            recipient_or_destination = o["recipient_or_destination"],
        )
        for o in raw.get("outputs_records", [])
    ]
    evidence_records = [
        ProcedureEvidenceRecord(
            record_or_evidence = e["record_or_evidence"],
            owner              = e["owner"],
            retention          = e["retention"],
            storage_location   = e["storage_location"],
        )
        for e in raw.get("evidence_records", [])
    ]
    time_controls = [
        ProcedureTimeControl(
            activity_or_step       = t["activity_or_step"],
            service_level          = t["service_level"],
            responsible_role       = t["responsible_role"],
            escalation_if_breached = t["escalation_if_breached"],
        )
        for t in raw.get("time_controls", [])
    ]

    draft = ProcedureDraftOutput(
        doc_id                         = raw.get("doc_id", doc_id),
        title_en                       = raw["title_en"],
        version                        = raw.get("version", spec.version),
        effective_date                 = raw.get("effective_date", "TBD"),
        owner                          = raw.get("owner", "Chief Information Security Officer"),
        classification                 = raw.get("classification", "Internal"),
        parent_policy_id               = raw.get("parent_policy_id", "POL-01"),
        parent_standard_id             = raw.get("parent_standard_id", "STD-01"),
        # § 1
        definitions                    = definitions,
        # § 2
        objective_en                   = raw["objective_en"],
        # § 3
        scope_en                       = raw["scope_en"],
        # § 4
        roles_responsibilities         = roles,
        # § 5
        procedure_overview             = raw.get("procedure_overview", ""),
        # § 6
        triggers                       = triggers,
        prerequisites                  = raw.get("prerequisites", []),
        tools_required                 = raw.get("tools_required", []),
        input_forms                    = input_forms,
        # § 7
        phases                         = phases,
        # § 8
        decision_points_and_escalations = raw.get("decision_points_and_escalations", ""),
        exception_handling_en          = raw.get("exception_handling_en", ""),
        # § 9
        outputs_records                = outputs_records,
        evidence_records               = evidence_records,
        verification_checks            = verifications,
        evidence_collection            = raw.get("evidence_collection", []),
        # § 10
        time_controls                  = time_controls,
        # § 11
        related_documents              = raw.get("related_documents", []),
        # § 13
        procedure_review               = raw.get("procedure_review", ""),
        # § 14
        review_and_approval            = raw.get("review_and_approval", ""),
        # Diagrams
        swimlane_diagram               = raw.get("swimlane_diagram", ""),
        flowchart_diagram              = raw.get("flowchart_diagram", ""),
    )

    total_steps = sum(len(ph.steps) for ph in phases)
    print(f"[ProcedureDrafter] Complete: {len(phases)} phases, {total_steps} steps, "
          f"{len(verifications)} verifications, {len(definitions)} definitions.")
    return draft


def _bundle_list(bundles: list[ControlBundle]) -> list[dict]:
    return [
        {
            "chunk_id":     b.chunk_id,
            "control_id":   b.control_id,
            "framework":    b.framework,
            "title":        b.title,
            "statement":    b.statement[:400],
            "rerank_score": round(b.rerank_score, 4) if b.rerank_score is not None else None,
        }
        for b in bundles
    ]
