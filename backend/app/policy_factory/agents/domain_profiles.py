"""
Domain Profiles — maps procedure/policy/standard topics to domain-specific
prompt extensions, tool references, and retrieval queries.

Used by all three specialized drafters to inject domain-specific context.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DomainProfile:
    name: str
    keywords: list[str]                # detection keywords (lowercase)
    system_prompt_extension: str       # injected into drafter system prompt
    extra_retrieval_queries: list[str] # additional NIST retrieval queries
    phase_guidance: str                # hints about phase structure


# ─────────────────────────────────────────────────────────────────────────────
# PROCEDURE DOMAINS
# ─────────────────────────────────────────────────────────────────────────────

PROCEDURE_DOMAINS: list[DomainProfile] = [

    DomainProfile(
        name="IAM / Privileged Access Management",
        keywords=["identity", "access", "iam", "privilege", "account", "entitlement",
                  "provisioning", "deprovisioning", "rbac", "pam", "mfa", "sso",
                  "password", "credential", "directory", "active directory", "ldap"],
        system_prompt_extension="""
DOMAIN: IDENTITY & ACCESS MANAGEMENT / PRIVILEGED ACCESS MANAGEMENT

MANDATORY TECHNICAL DEPTH:
• Active Directory: PowerShell examples for Get-ADUser, Set-ADUser, New-ADGroup, Add-ADGroupMember,
  Get-ADGroupMember, Search-ADAccount, Disable-ADAccount, Move-ADObject
• CyberArk PAM: REST API — POST /PasswordVault/API/auth/Cyberark/Logon,
  GET /PasswordVault/API/Accounts, POST /PasswordVault/API/Accounts/{id}/Password/Retrieve
• SailPoint IdentityNow: REST API — GET /v3/accounts, POST /v3/provisioning-policies,
  PATCH /v3/access-profiles/{id}
• Azure AD / Entra ID: az ad user list, az ad group member add, az role assignment create,
  Get-AzureADUser, Get-AzureADGroupMember
• Okta: API — GET /api/v1/users, POST /api/v1/users/{id}/lifecycle/activate,
  GET /api/v1/users/{id}/appLinks

SPECIFIC REQUIREMENTS FOR IAM PROCEDURES:
1. Access request and approval workflow (joiner/mover/leaver)
2. Privileged account creation, vaulting, and rotation
3. Quarterly access recertification campaign steps
4. MFA enforcement verification and exceptions process
5. Service account management and monitoring
6. Emergency access (break-glass) procedure with dual-control
7. SOD (segregation of duties) conflict detection and resolution
8. Session recording for privileged sessions (CyberArk PSM or equivalent)

NCA CONTROLS FOCUS: NCA_ECC-2-2, NCA_ECC-2-3, access control family
NIST CONTROLS FOCUS: AC-2, AC-3, AC-5, AC-6, AC-17, IA-2, IA-5, IA-8, PS-4, PS-5
""",
        extra_retrieval_queries=[
            "identity access management user provisioning deprovisioning lifecycle",
            "privileged access management PAM vault session recording",
            "multi-factor authentication MFA enforcement access recertification",
            "role based access control RBAC segregation of duties SOD",
        ],
        phase_guidance="Phases: 1-Request & Approval, 2-Provisioning & Configuration, 3-Vaulting & MFA, 4-Recertification & Review, 5-Deprovisioning & Audit",
    ),

    DomainProfile(
        name="Vulnerability Management & Patching",
        keywords=["vulnerability", "patch", "patching", "scanning", "remediation",
                  "cve", "cvss", "nessus", "qualys", "openvas", "tenable", "svm",
                  "hardening", "baseline", "cis benchmark"],
        system_prompt_extension="""
DOMAIN: VULNERABILITY MANAGEMENT & PATCH MANAGEMENT

MANDATORY TECHNICAL DEPTH:
• Tenable Nessus / Tenable.sc: nessuscli scan --create, REST API GET /scans/{id}/hosts,
  export format JSON/CSV, CVSS v3.1 scoring, asset criticality rating
• Qualys VMDR: API — GET /api/2.0/fo/scan/?action=list, POST /api/2.0/fo/scan/?action=launch,
  GET /api/2.0/fo/asset/host/vm/detection/?action=list
• Microsoft WSUS / SCCM: PowerShell — Get-WsusUpdate, Approve-WsusUpdate,
  Get-CMSoftwareUpdate, Start-CMSoftwareUpdateDeployment
• CrowdStrike Spotlight: REST API /spotlight/combined/vulnerabilities/v1
• Azure Defender for Cloud / AWS Inspector v2 / GCP Security Command Center

SPECIFIC REQUIREMENTS FOR VULNERABILITY PROCEDURES:
1. Asset inventory and criticality classification (Crown Jewels, Tier 1/2/3)
2. Authenticated vs unauthenticated scan configuration
3. CVSS v3.1 scoring + organisational risk context (exploitability, asset value)
4. Patch testing in staging environment before production rollout
5. Emergency patching (P0/P1) vs standard patching windows
6. Compensating controls for unpatchable systems (OT/legacy)
7. False positive validation and exception tracking
8. Metrics: MTTD, MTTR, patch compliance % by tier, SLA adherence

NCA CONTROLS FOCUS: NCA_ECC-3-3, NCA_ECC-3-4, vulnerability management family
NIST CONTROLS FOCUS: RA-5, SI-2, SI-3, CM-6, CM-7, SA-11
""",
        extra_retrieval_queries=[
            "vulnerability scanning assessment CVSS remediation patching SLA",
            "patch management testing staging production rollout emergency",
            "asset inventory criticality classification crown jewels",
            "vulnerability exception compensating control false positive",
        ],
        phase_guidance="Phases: 1-Asset Discovery & Scoping, 2-Authenticated Scanning, 3-Risk Prioritisation & Triage, 4-Remediation & Patching, 5-Verification & Closure, 6-Metrics & Reporting",
    ),

    DomainProfile(
        name="Incident Response & Digital Forensics",
        keywords=["incident", "response", "forensic", "breach", "siem", "soar",
                  "containment", "eradication", "recovery", "ioc", "ioa",
                  "threat hunting", "malware", "ransomware", "dfir", "triage"],
        system_prompt_extension="""
DOMAIN: INCIDENT RESPONSE & DIGITAL FORENSICS

MANDATORY TECHNICAL DEPTH:
• Splunk SIEM: SPL queries — index=security sourcetype=WinEventLog EventCode=4625
  | stats count by src_ip, User | where count > 50
• Microsoft Sentinel: KQL — SecurityEvent | where EventID == 4625 | summarize
  count() by Account, IpAddress | where count_ > 20
• CrowdStrike Falcon: RTR commands — runscript, put, ls, netstat, ps, reg query
• Volatility3: vol.py -f memory.dmp windows.pslist, windows.netscan, windows.malfind
• FTK Imager / dd: dd if=/dev/sda of=/mnt/evidence/disk.img bs=4M status=progress

SPECIFIC REQUIREMENTS FOR IR PROCEDURES:
1. Incident classification matrix (P0-P4) with response SLAs
2. Evidence preservation order (RAM → disk → logs → network) with chain of custody
3. Containment options: network isolation, account lockout, endpoint quarantine
4. IOC/IOA extraction and TI platform submission (MISP, OpenCTI)
5. Communication plan: internal escalation + regulatory notification (NCA within 72h)
6. Lessons learned and post-incident review process
7. SOAR playbook integration (Palo Alto XSOAR, Splunk SOAR, IBM QRadar SOAR)
8. MITRE ATT&CK mapping for TTPs observed

NCA CONTROLS FOCUS: NCA_ECC-5-1, NCA_ECC-5-2, incident management family
NIST CONTROLS FOCUS: IR-4, IR-5, IR-6, IR-7, IR-8, SI-4, AU-6
""",
        extra_retrieval_queries=[
            "incident response containment eradication recovery forensic investigation",
            "SIEM alert triage threat detection IOC indicator of compromise",
            "digital forensics evidence preservation chain of custody memory acquisition",
            "incident classification severity P0 P1 notification regulatory NCA",
        ],
        phase_guidance="Phases: 1-Detection & Triage, 2-Containment & Preservation, 3-Investigation & Analysis, 4-Eradication & Recovery, 5-Post-Incident Review & Reporting",
    ),

    DomainProfile(
        name="Security Monitoring & SIEM Operations",
        keywords=["monitoring", "siem", "soc", "log", "logging", "alert", "detection",
                  "splunk", "sentinel", "qradar", "elastic", "threat detection",
                  "use case", "playbook", "sla", "correlation"],
        system_prompt_extension="""
DOMAIN: SECURITY MONITORING & SIEM OPERATIONS

MANDATORY TECHNICAL DEPTH:
• Splunk Enterprise Security: ES searches, notable events, risk-based alerting,
  adaptive response actions, dashboard creation (| eval risk_score=...)
• Microsoft Sentinel: Analytics rules, workbooks, UEBA, Fusion detection,
  Logic App playbooks, watchlists
• IBM QRadar: AQL queries, custom rules, offense management, reference sets
• Log source onboarding: Syslog (RFC 5424), Windows Event Forwarding (WEF),
  CEF/LEEF format parsing, custom field extractions

SPECIFIC REQUIREMENTS FOR MONITORING PROCEDURES:
1. Log source inventory and criticality classification
2. Use case development lifecycle (hypothesis → detection rule → tuning → retire)
3. Alert tuning: false positive reduction methodology with baselines
4. MTTD (Mean Time to Detect) and MTTR metrics collection
5. Threat intelligence feed integration (STIX/TAXII, MISP)
6. SOC tier model: L1 triage → L2 investigation → L3 threat hunting
7. Retention policy: hot (90d) → warm (365d) → cold (7yr) tiering
8. Compliance-mandated log sources (NCA ECC §3.3, ISO 27001 A.12.4)

NCA CONTROLS FOCUS: NCA_ECC-3-3, monitoring and detection family
NIST CONTROLS FOCUS: AU-2, AU-3, AU-6, AU-9, AU-12, SI-4, SI-5, IR-4
""",
        extra_retrieval_queries=[
            "security monitoring SIEM log management detection alert correlation",
            "SOC operations threat detection use case development tuning",
            "log retention audit trail compliance evidence monitoring",
            "threat intelligence feed IOC integration SIEM playbook",
        ],
        phase_guidance="Phases: 1-Log Source Onboarding, 2-Detection Rule Configuration, 3-Alert Triage & Validation, 4-Investigation & Escalation, 5-Tuning & Continuous Improvement",
    ),

    DomainProfile(
        name="Change & Configuration Management",
        keywords=["change", "configuration", "cmdb", "cab", "change board", "baseline",
                  "hardening", "cis", "stig", "drift", "configuration management",
                  "change request", "approval", "rollback"],
        system_prompt_extension="""
DOMAIN: CHANGE & CONFIGURATION MANAGEMENT

MANDATORY TECHNICAL DEPTH:
• ServiceNow ITSM: REST API — POST /api/now/table/change_request, PATCH update,
  change_request fields: category, risk, impact, justification, test_plan, rollback_plan
• Ansible/Ansible Tower: ansible-playbook site.yml --check --diff, awx job_templates launch,
  inventory management, role-based access to Tower
• Chef InSpec: inspec exec baseline_profile --reporter json:report.json
• CIS-CAT Pro: ./CISCAT.sh -a -rd /var/www/html/reports -b benchmarks/CIS_RHEL8_v2.0.0-xccdf.xml

SPECIFIC REQUIREMENTS FOR CHANGE PROCEDURES:
1. RFC (Request for Change) submission and completeness check
2. Risk and impact assessment matrix (Low/Medium/High/Critical)
3. CAB review process: standard vs normal vs emergency change
4. Pre-implementation environment (dev → staging → UAT → prod)
5. Configuration baseline snapshot before and after change
6. Automated compliance scan post-change (CIS benchmark verification)
7. Rollback triggers and rollback execution procedure
8. Post-implementation review (PIR) within 5 business days

NCA CONTROLS FOCUS: NCA_ECC-3-1, change management family
NIST CONTROLS FOCUS: CM-2, CM-3, CM-4, CM-5, CM-6, CM-7, CM-8, SA-10
""",
        extra_retrieval_queries=[
            "change management CAB change advisory board risk impact assessment",
            "configuration management baseline CMDB drift detection hardening",
            "CIS benchmark STIG compliance configuration baseline verification",
            "emergency change rollback post-implementation review",
        ],
        phase_guidance="Phases: 1-RFC Submission & Review, 2-Risk & Impact Assessment, 3-CAB Approval, 4-Pre-Implementation Staging, 5-Production Implementation, 6-Post-Change Verification",
    ),

    DomainProfile(
        name="Backup, Recovery & Business Continuity",
        keywords=["backup", "recovery", "rto", "rpo", "disaster", "bcp", "bcm",
                  "continuity", "restore", "replication", "failover", "resilience",
                  "dr test", "ransomware recovery"],
        system_prompt_extension="""
DOMAIN: BACKUP, RECOVERY & BUSINESS CONTINUITY

MANDATORY TECHNICAL DEPTH:
• Veeam Backup & Replication: PowerShell — Get-VBRBackup, Start-VBRFullBackup,
  Start-VBRRestoreVM, Get-VBRRestorePoint, Export-VBRBackupDisk
• Veritas NetBackup: nbbackup -p policy_name -s schedule_name,
  bprestore -s start_date -e end_date -C client_name -L restore.log
• AWS Backup: aws backup start-backup-job --backup-vault-name, start-restore-job,
  list-backup-jobs, describe-backup-vault
• Azure Site Recovery: az site-recovery replication-recovery-plan create,
  start-unplanned-failover-job

SPECIFIC REQUIREMENTS FOR BACKUP/RECOVERY PROCEDURES:
1. RTO and RPO targets per system tier (Tier 1: RTO 4h / RPO 1h)
2. 3-2-1-1-0 backup rule (3 copies, 2 media types, 1 offsite, 1 immutable, 0 errors)
3. Immutable backup configuration (WORM storage, object lock)
4. Backup integrity verification (hash comparison, test restores monthly)
5. DR test exercise: quarterly tabletop + annual full failover test
6. Ransomware recovery playbook: isolation → clean restore → integrity check
7. Recovery runbook per critical system with exact restore commands
8. Backup monitoring: job success/failure alerting, capacity management

NCA CONTROLS FOCUS: NCA_ECC-4-1, availability and continuity family
NIST CONTROLS FOCUS: CP-4, CP-6, CP-7, CP-9, CP-10, SI-12
""",
        extra_retrieval_queries=[
            "backup recovery RTO RPO disaster recovery testing restore validation",
            "business continuity BCP DR test failover resilience",
            "immutable backup WORM ransomware recovery isolation",
            "3-2-1 backup rule offsite replication integrity verification",
        ],
        phase_guidance="Phases: 1-Backup Configuration & Scheduling, 2-Backup Execution & Monitoring, 3-Integrity Verification, 4-Recovery Testing, 5-Incident Recovery, 6-DR Exercise & Reporting",
    ),

    DomainProfile(
        name="Data Protection & DLP",
        keywords=["data", "dlp", "classification", "privacy", "gdpr", "pdpl",
                  "sensitive", "pii", "encryption", "data loss", "exfiltration",
                  "data governance", "retention", "disposal", "purge"],
        system_prompt_extension="""
DOMAIN: DATA PROTECTION & DATA LOSS PREVENTION

MANDATORY TECHNICAL DEPTH:
• Microsoft Purview DLP: Set-DlpCompliancePolicy, New-DlpComplianceRule,
  sensitivity labels, auto-labelling policies, endpoint DLP
• Symantec DLP: enforce server policies, network monitor, endpoint prevent,
  policy violation incident management via REST API
• Varonis Data Security Platform: permission analysis, data access governance,
  alert on unusual file activity via API GET /api/v1/alerts
• Azure Information Protection: Set-AIPFileLabel, Get-AIPFileStatus,
  Protection.ProtectWithTemplate()

SPECIFIC REQUIREMENTS FOR DATA PROTECTION PROCEDURES:
1. Data classification taxonomy (Public / Internal / Confidential / Restricted / Secret)
2. Automated data discovery and classification scanning (structured + unstructured)
3. DLP policy creation: detection rules for PII, financial data, IP, health records
4. Incident workflow: block → quarantine → notify → review → remediate
5. Encryption at rest (AES-256) and in transit (TLS 1.2/1.3) verification
6. Data retention schedule and secure disposal (NIST SP 800-88 media sanitisation)
7. Cross-border data transfer assessment (Saudi PDPL Article 29 requirements)
8. Data lineage mapping for critical datasets

NCA CONTROLS FOCUS: NCA_ECC-2-6, data protection and privacy family
NIST CONTROLS FOCUS: MP-6, SC-8, SC-28, SI-12, AC-23, RA-3
""",
        extra_retrieval_queries=[
            "data classification sensitivity label DLP policy enforcement",
            "data loss prevention exfiltration detection quarantine incident",
            "encryption at rest in transit key management data protection",
            "data retention disposal media sanitisation NIST 800-88",
        ],
        phase_guidance="Phases: 1-Data Discovery & Classification, 2-DLP Policy Configuration, 3-Monitoring & Detection, 4-Incident Response & Remediation, 5-Retention & Disposal, 6-Compliance Verification",
    ),

    DomainProfile(
        name="Network Security & Segmentation",
        keywords=["network", "firewall", "segmentation", "dmz", "vlan", "vpn",
                  "zero trust", "microsegmentation", "ids", "ips", "nac",
                  "proxy", "dns", "routing", "acl", "nsg"],
        system_prompt_extension="""
DOMAIN: NETWORK SECURITY & SEGMENTATION

MANDATORY TECHNICAL DEPTH:
• Palo Alto Networks NGFW: set deviceconfig system, show running security-policy,
  test security-policy-match, commit, operational commands for traffic analysis
• Cisco ASA/Firepower: show access-list, access-group, object-group,
  packet-tracer input INSIDE tcp 10.0.0.1 1234 192.168.1.1 443 detail
• Check Point: fw stat, cpinfo, fwaccel stat, SmartConsole API calls
• Illumio / Guardicore microsegmentation: policy creation, traffic visualisation
• Azure NSG / AWS Security Groups: az network nsg rule create, aws ec2 authorize-security-group-ingress

SPECIFIC REQUIREMENTS FOR NETWORK SECURITY PROCEDURES:
1. Network zone definition and traffic matrix (approved flows between zones)
2. Firewall rule review process: quarterly review + change-driven review
3. Default-deny philosophy: document approved exceptions with business justification
4. IDS/IPS signature update and tuning procedure
5. Network access control (NAC): 802.1X supplicant, RADIUS configuration
6. VPN: site-to-site and remote access configuration, certificate management
7. DNS security: RPZ (response policy zones), DNSSEC validation, DNS filtering
8. Network traffic baseline and anomaly detection thresholds

NCA CONTROLS FOCUS: NCA_ECC-3-2, network security family
NIST CONTROLS FOCUS: SC-5, SC-7, SC-8, SC-20, SC-22, SC-32, SI-4
""",
        extra_retrieval_queries=[
            "network segmentation firewall rule DMZ VLAN access control",
            "zero trust microsegmentation network access control NAC",
            "IDS IPS intrusion detection prevention network monitoring",
            "VPN remote access certificate management network security",
        ],
        phase_guidance="Phases: 1-Network Discovery & Zone Mapping, 2-Segmentation Design & Approval, 3-Firewall Rule Implementation, 4-IDS/IPS Configuration, 5-Testing & Validation, 6-Ongoing Monitoring",
    ),

    DomainProfile(
        name="Cloud Security",
        keywords=["cloud", "aws", "azure", "gcp", "saas", "iaas", "paas",
                  "s3", "ec2", "container", "kubernetes", "k8s", "serverless",
                  "cspm", "cwpp", "cnapp", "devops", "ci/cd", "pipeline"],
        system_prompt_extension="""
DOMAIN: CLOUD SECURITY (IaaS / PaaS / SaaS)

MANDATORY TECHNICAL DEPTH:
• AWS Security Hub + Config Rules: aws securityhub get-findings, aws configservice
  get-compliance-details-by-config-rule, aws iam get-credential-report
• Azure Security Center / Defender for Cloud: az security assessment list,
  az security alert list, Get-AzSecurityAlert
• GCP Security Command Center: gcloud scc findings list, gcloud asset list
• Prisma Cloud (CSPM): API — GET /v2/alert, POST /v2/policy, compliance reports
• Kubernetes security: kubectl get pods --all-namespaces -o json | jq '.items[].spec.containers[].securityContext',
  OPA Gatekeeper policy enforcement, kube-bench CIS benchmark

SPECIFIC REQUIREMENTS FOR CLOUD SECURITY PROCEDURES:
1. Cloud account/subscription onboarding with baseline security controls
2. CSPM integration: continuous posture monitoring, misconfiguration alerting
3. IAM least privilege: AWS SCPs, Azure Policy, GCP Org Policies
4. Data encryption: KMS key management, customer-managed keys (CMK) rotation
5. Cloud network security: VPC/VNet design, security groups, WAF configuration
6. Container security: image scanning, runtime protection, secret management
7. Cloud logging: CloudTrail, Azure Activity Log, GCP Cloud Audit Logs → SIEM
8. Shared responsibility model documentation per cloud service type

NCA CONTROLS FOCUS: NCA_ECC cloud controls, NCA_CSCC
NIST CONTROLS FOCUS: AC-4, AU-2, CM-7, RA-5, SC-7, SI-4, SA-4
""",
        extra_retrieval_queries=[
            "cloud security posture management CSPM misconfiguration AWS Azure GCP",
            "cloud IAM least privilege service account role assignment",
            "cloud logging audit trail CloudTrail Azure Activity Log SIEM",
            "container security Kubernetes image scanning runtime protection",
        ],
        phase_guidance="Phases: 1-Cloud Account Onboarding & Baseline, 2-CSPM Configuration, 3-IAM & Encryption Hardening, 4-Logging & Monitoring Setup, 5-Continuous Compliance Validation",
    ),

    DomainProfile(
        name="Cryptography & Key Management",
        keywords=["cryptography", "encryption", "key", "certificate", "pki", "hsm",
                  "tls", "ssl", "kms", "rotation", "ca", "crl", "ocsp"],
        system_prompt_extension="""
DOMAIN: CRYPTOGRAPHY & KEY MANAGEMENT

MANDATORY TECHNICAL DEPTH:
• HashiCorp Vault: vault kv put secret/db password=..., vault secrets enable pki,
  vault write pki/root/generate/internal common_name=example.com,
  vault lease renew, vault token renew
• AWS KMS: aws kms create-key, aws kms create-alias, aws kms enable-key-rotation,
  aws kms generate-data-key --key-id arn:... --key-spec AES_256
• OpenSSL: openssl genrsa -out private.key 4096, openssl req -new -x509,
  openssl verify -CAfile ca.crt cert.crt, openssl s_client -connect host:443
• Microsoft CA: certreq, certutil -viewstore, Get-Certificate, New-SelfSignedCertificate

SPECIFIC REQUIREMENTS FOR CRYPTOGRAPHY PROCEDURES:
1. Algorithm standards: AES-256-GCM, RSA-4096, ECDSA P-384, SHA-256 minimum
2. Key lifecycle: generation → distribution → storage → rotation → revocation → destruction
3. HSM integration for root CAs and master keys
4. Certificate inventory management: expiry monitoring (30/14/7 day alerts)
5. TLS configuration: disable TLS 1.0/1.1, require TLS 1.2+, cipher suite hardening
6. Key rotation schedule per key type (data encryption: annual, session keys: per-session)
7. Key escrow and emergency recovery procedure
8. Cryptographic algorithm migration planning (quantum-readiness)

NCA CONTROLS FOCUS: NCA_ECC-2-6, cryptographic controls
NIST CONTROLS FOCUS: SC-8, SC-12, SC-13, SC-17, SC-28, IA-5, SI-7
""",
        extra_retrieval_queries=[
            "cryptography key management lifecycle rotation revocation HSM PKI",
            "TLS certificate management CA PKI expiry monitoring",
            "encryption algorithm AES RSA key generation storage distribution",
            "quantum cryptography algorithm migration NIST post-quantum",
        ],
        phase_guidance="Phases: 1-Key Generation & HSM Integration, 2-Certificate Issuance & Distribution, 3-Inventory & Monitoring, 4-Rotation & Renewal, 5-Revocation & Destruction",
    ),

    DomainProfile(
        name="Endpoint Security & EDR",
        keywords=["endpoint", "edr", "antivirus", "antimalware", "crowdstrike",
                  "defender", "carbon black", "sentinelone", "cylance",
                  "hardening", "patch", "device", "workstation", "laptop", "mobile"],
        system_prompt_extension="""
DOMAIN: ENDPOINT SECURITY & EDR

MANDATORY TECHNICAL DEPTH:
• CrowdStrike Falcon: falconctl s --cid=..., RTR session management,
  Prevent policies: HIGH_SEVERITY_DETECTIONS, prevent=true, API GET /devices/queries/devices/v1
• Microsoft Defender for Endpoint: Get-MpComputerStatus, Set-MpPreference,
  Update-MpSignature, Invoke-MpScan -ScanType QuickScan,
  MDE API: GET /api/machines, POST /api/machines/{id}/isolate
• SentinelOne: API GET /web/api/v2.1/agents, POST .../threats/{id}/mitigate/remediate
• Windows: sfc /scannow, DISM /Online /Cleanup-Image /RestoreHealth,
  secedit /analyze /cfg CIS_Win10_v1.12.0.inf /db analysis.sdb /log analysis.log

SPECIFIC REQUIREMENTS FOR ENDPOINT SECURITY PROCEDURES:
1. EDR agent deployment and configuration baseline
2. Prevention policy configuration: prevention vs detection mode by asset tier
3. Threat response: alert → investigation → containment → remediation workflow
4. Endpoint hardening: CIS benchmark application, AppLocker/WDAC policies
5. USB and removable media control policy enforcement
6. Endpoint isolation procedure for compromised devices
7. EDR telemetry forwarding to SIEM (schema mapping)
8. Coverage metrics: agent health, protection coverage %, offline devices

NCA CONTROLS FOCUS: NCA_ECC-3-4, endpoint protection family
NIST CONTROLS FOCUS: SI-2, SI-3, SI-7, CM-6, CM-7, AU-2, IR-4
""",
        extra_retrieval_queries=[
            "endpoint detection response EDR agent deployment prevention policy",
            "endpoint hardening CIS benchmark AppLocker device control",
            "malware threat response containment remediation endpoint isolation",
            "antivirus antimalware signature update scan schedule telemetry",
        ],
        phase_guidance="Phases: 1-EDR Deployment & Configuration, 2-Prevention Policy Tuning, 3-Threat Detection & Triage, 4-Containment & Remediation, 5-Coverage Monitoring & Reporting",
    ),

    DomainProfile(
        name="Third-Party & Vendor Risk Management",
        keywords=["third party", "vendor", "supplier", "procurement", "outsourcing",
                  "due diligence", "assessment", "contract", "sla", "msa",
                  "supply chain", "tprm", "vra"],
        system_prompt_extension="""
DOMAIN: THIRD-PARTY & VENDOR RISK MANAGEMENT

MANDATORY TECHNICAL DEPTH:
• OneTrust Vendorpedia / ProcessUnity: vendor questionnaire workflows, API integrations
• BitSight / SecurityScorecard: GET /ratings/v1/companies/{id}/factors, continuous monitoring
• ServiceNow GRC: vendor risk assessment workflows, third-party portal, risk scoring

SPECIFIC REQUIREMENTS FOR VENDOR RISK PROCEDURES:
1. Vendor classification (Critical/High/Medium/Low) based on data access and criticality
2. Pre-contract due diligence: security questionnaire (CSA CAIQ, SIG Lite), background check
3. Contract security requirements: MSSP SLA, right-to-audit clause, breach notification
4. Ongoing monitoring: quarterly BitSight/SecurityScorecard, annual reassessment
5. Fourth-party (sub-processor) risk identification and management
6. Vendor offboarding: access revocation, data return/destruction, certificate termination
7. Incident notification: vendor breach → impact assessment → regulatory notification (if data involved)
8. Supply chain software integrity: SBOM, code signing verification, dependency scanning

NCA CONTROLS FOCUS: NCA_ECC-1-3, supply chain and third-party controls
NIST CONTROLS FOCUS: SR-2, SR-3, SR-5, SR-6, SR-8, CA-2, SA-9
""",
        extra_retrieval_queries=[
            "third party vendor risk assessment due diligence supply chain",
            "vendor security questionnaire SLA right to audit contract",
            "ongoing vendor monitoring scoring continuous assessment",
            "fourth party sub-processor data handling breach notification",
        ],
        phase_guidance="Phases: 1-Vendor Classification & Scoping, 2-Due Diligence Assessment, 3-Contract & Onboarding, 4-Ongoing Monitoring, 5-Periodic Reassessment, 6-Offboarding",
    ),

    # Generic fallback
    DomainProfile(
        name="Generic Cybersecurity Procedure",
        keywords=[],
        system_prompt_extension="""
DOMAIN: CYBERSECURITY OPERATIONAL PROCEDURE

Apply deep technical detail appropriate to the specific topic. Reference enterprise tools
from the ENTERPRISE_TOOLS library. Include real CLI commands, API calls, and configuration
examples. Each step must be independently executable by a skilled practitioner.

TECHNICAL REQUIREMENTS:
• Reference at least 3 enterprise tools with real CLI/API syntax
• Include configuration examples with actual parameter values
• Provide measurable success criteria with specific thresholds or values
• Each phase must identify the threat or risk it mitigates

QUALITY STANDARD: Fortune500 Big4 advisory quality — auditor-ready documentation.
""",
        extra_retrieval_queries=[],
        phase_guidance="Phases: 1-Planning & Preparation, 2-Implementation, 3-Verification & Testing, 4-Documentation & Closure, 5-Ongoing Monitoring",
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# POLICY DOMAINS
# ─────────────────────────────────────────────────────────────────────────────

POLICY_DOMAINS: list[DomainProfile] = [

    DomainProfile(
        name="Information Security Governance",
        keywords=["governance", "program", "risk", "grc", "ciso", "framework",
                  "committee", "board", "strategy", "maturity"],
        system_prompt_extension="""
DOMAIN: INFORMATION SECURITY GOVERNANCE & PROGRAM MANAGEMENT

POLICY DEPTH REQUIREMENTS:
• Board-level accountability: define CISO reporting line, board security committee charter
• Risk appetite statement: quantitative thresholds (risk tolerance ≤ SAR X for Tier-1 systems)
• Governance structure: ISSC (Information Security Steering Committee) terms of reference
• KPIs and KRIs: minimum 10 measurable indicators in the policy
• NCA ECC alignment: explicitly cite applicable ECC sub-controls in each policy element
• ISO 27001:2022 Annex A controls mapping table
• NIST CSF 2.0 function alignment (Govern, Identify, Protect, Detect, Respond, Recover)
""",
        extra_retrieval_queries=[
            "information security governance program CISO board committee risk appetite",
            "GRC framework policy program management security strategy",
        ],
        phase_guidance="N/A for policies",
    ),

    DomainProfile(
        name="Generic Security Policy",
        keywords=[],
        system_prompt_extension="""
POLICY DEPTH REQUIREMENTS:
• Each policy element must be a mandatory 'shall' statement grounded in NCA controls
• Include measurable compliance metrics for each policy area
• Define clear roles and delegated authorities
• State enforcement mechanisms and disciplinary consequences
• Cross-reference related standards and procedures
""",
        extra_retrieval_queries=[],
        phase_guidance="N/A for policies",
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# STANDARD DOMAINS
# ─────────────────────────────────────────────────────────────────────────────

STANDARD_DOMAINS: list[DomainProfile] = [

    DomainProfile(
        name="Technical Hardening Standard",
        keywords=["hardening", "baseline", "configuration", "cis", "stig", "benchmark",
                  "secure configuration", "patch", "update"],
        system_prompt_extension="""
DOMAIN: TECHNICAL HARDENING & SECURE CONFIGURATION STANDARD

STANDARD DEPTH REQUIREMENTS:
• Minimum requirements MUST include specific configuration values (not vague "strong password")
• E.g.: "Minimum password length: 14 characters; complexity: upper + lower + digit + special;
  history: 24 passwords; max age: 90 days; lockout: 5 attempts → 30 min lockout"
• CIS Benchmark level reference: state Level 1 vs Level 2 applicability
• STIG ID references where applicable
• Exceptions process: compensating control must be equivalent strength
• Automated compliance verification: state the tool and benchmark ID
""",
        extra_retrieval_queries=[
            "secure configuration baseline hardening CIS benchmark STIG specific values",
            "password policy lockout account configuration requirements",
        ],
        phase_guidance="N/A for standards",
    ),

    DomainProfile(
        name="Generic Security Standard",
        keywords=[],
        system_prompt_extension="""
STANDARD DEPTH REQUIREMENTS:
• Requirements must be specific, measurable, and verifiable
• Include minimum thresholds, numerical targets, and configuration values
• Each domain must have 5+ requirements with N.M req_ids
• Define verification method for each requirement
• State deviation and exception approval process
""",
        extra_retrieval_queries=[],
        phase_guidance="N/A for standards",
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# DETECTION FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def detect_procedure_domain(topic: str) -> DomainProfile:
    """Return the best-matching procedure domain profile for the given topic."""
    topic_lower = topic.lower()
    best: DomainProfile | None = None
    best_score = 0
    for profile in PROCEDURE_DOMAINS[:-1]:  # skip generic fallback
        score = sum(1 for kw in profile.keywords if kw in topic_lower)
        if score > best_score:
            best_score = score
            best = profile
    return best if best_score > 0 else PROCEDURE_DOMAINS[-1]  # fallback to generic


def detect_policy_domain(topic: str) -> DomainProfile:
    """Return the best-matching policy domain profile for the given topic."""
    topic_lower = topic.lower()
    best: DomainProfile | None = None
    best_score = 0
    for profile in POLICY_DOMAINS[:-1]:
        score = sum(1 for kw in profile.keywords if kw in topic_lower)
        if score > best_score:
            best_score = score
            best = profile
    return best if best_score > 0 else POLICY_DOMAINS[-1]


def detect_standard_domain(topic: str) -> DomainProfile:
    """Return the best-matching standard domain profile for the given topic."""
    topic_lower = topic.lower()
    best: DomainProfile | None = None
    best_score = 0
    for profile in STANDARD_DOMAINS[:-1]:
        score = sum(1 for kw in profile.keywords if kw in topic_lower)
        if score > best_score:
            best_score = score
            best = profile
    return best if best_score > 0 else STANDARD_DOMAINS[-1]
