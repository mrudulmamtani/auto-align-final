"""
Generate the full dependency chain for PRC-03 (Detection Rule Management Procedure):

  POL-07  Security Logging and Monitoring Policy          [Wave 1]
  STD-03  Security Logging and Monitoring Standard        [Wave 2, needs POL-07]
  STD-11  Network Detection and Response Standard         [Wave 2, needs POL-07]
  PRC-03  Detection Rule Management Procedure             [Wave 3, needs POL-07, STD-03, STD-11]

Source: docGenConstruct.json
  PRC-03 depends_on: ["POL-07", "STD-03", "STD-11"]
  STD-03 depends_on: ["POL-07", "POL-12"]
  STD-11 depends_on: ["POL-06", "POL-07"]
  POL-07 depends_on: ["POL-01", "POL-12"]

Pipeline: NCA OSCAL + NIST SP 800-53 retrieval → cross-encoder reranking
          → gap analysis (Agent 2) → multi-agent drafting (o3 + gpt-4o)
          → deterministic QA → DOCX + traceability annex

Output: policy_output/{doc_id}.docx
        policy_output/{doc_id}_traceability.docx
        policy_output/{prefix}_*_{stage}.json  (intermediate artifacts)

Usage:
    cd backend
    python run_trio_nca.py

Required env vars:
    OPENAI_API_KEY
    HF_TOKEN   (HuggingFace — for cross-encoder; cached after first download)
"""
import sys
import os
import time
import traceback

sys.path.insert(0, os.path.dirname(__file__))

from app.policy_factory.pipeline import PolicyFactory
from app.policy_factory.models import EntityProfile, DocumentSpec

# ── Organisation profile ──────────────────────────────────────────────────────

ORG_PROFILE = EntityProfile(
    org_name            = "Ministry of Digital Economy",
    sector              = "Government",
    hosting_model       = "hybrid",
    soc_model           = "internal",
    data_classification = ["confidential", "restricted", "public"],
    ot_presence         = False,
    critical_systems    = ["SIEM Platform", "Network Detection System",
                           "Log Management System", "SOC Dashboard"],
    jurisdiction        = "UAE",
)

# ── Document chain ─────────────────────────────────────────────────────────────
#
#   docGenConstruct.json dependency graph:
#
#   POL-07 (Security Logging and Monitoring Policy)
#     ├── STD-03 (Security Logging and Monitoring Standard)
#     ├── STD-11 (Network Detection and Response Standard)
#     │       └── PRC-03 (Detection Rule Management Procedure)
#     └───────────────────────────────────────────────────┘

CHAIN = [
    # ── [1/4] Foundation policy ───────────────────────────────────────────────
    {
        "doc_id":   "POL-07",
        "doc_type": "policy",
        "topic":    "Security Logging and Monitoring",
        "scope": (
            "All information systems, servers, network devices, applications, "
            "cloud platforms, and security controls that generate audit logs or "
            "security events. Applies to all personnel and third parties operating "
            "systems on behalf of the organisation."
        ),
        "target_audience": (
            "Senior management, cybersecurity governance committee, SOC management, "
            "IT operations leadership, all staff with administrative system access"
        ),
    },

    # ── [2/4] Logging and monitoring standard (depends on POL-07) ─────────────
    {
        "doc_id":   "STD-03",
        "doc_type": "standard",
        "topic":    "Security Logging and Monitoring",
        "scope": (
            "All security log collection, storage, retention, and monitoring activities "
            "across on-premise infrastructure, cloud environments, and hybrid deployments. "
            "Applies to all employees, contractors, and managed service providers with "
            "access to logging and monitoring infrastructure."
        ),
        "target_audience": (
            "SOC analysts, SIEM administrators, IT operations, cybersecurity team, "
            "internal audit, cloud security team"
        ),
    },

    # ── [3/4] NDR standard (depends on POL-07) ────────────────────────────────
    {
        "doc_id":   "STD-11",
        "doc_type": "standard",
        "topic":    "Network Detection and Response",
        "scope": (
            "All network detection and response (NDR) and endpoint detection and response "
            "(EDR) capabilities, threat detection rules, alert tuning, and automated response "
            "playbooks. Applies to all network segments, endpoints, and security monitoring "
            "infrastructure owned or managed by the organisation."
        ),
        "target_audience": (
            "SOC threat detection engineers, SIEM/NDR/EDR administrators, "
            "cybersecurity operations team, incident response team, internal audit"
        ),
    },

    # ── [4/4] Procedure (depends on POL-07, STD-03, STD-11) ──────────────────
    {
        "doc_id":        "PRC-03",
        "doc_type":      "procedure",
        "topic":         "Detection Rule Management",
        "scope": (
            "All activities related to the creation, testing, deployment, tuning, "
            "and retirement of threat detection rules within the SIEM, NDR, and EDR "
            "platforms. Applies to SOC engineers, threat detection analysts, and "
            "administrators responsible for maintaining detection content."
        ),
        "target_audience": (
            "SOC detection engineers, SIEM administrators, threat intelligence analysts, "
            "cybersecurity operations team, SOC management"
        ),
        # Explicit parent references for the procedure renderer
        "parent_policy_id":   "POL-07",
        "parent_standard_id": "STD-03",   # primary standard (STD-11 is secondary)
    },
]

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "policy_output")


# ── Runner ────────────────────────────────────────────────────────────────────

def main() -> bool:
    print("=" * 70)
    print("  PolicyFactory — PRC-03 Dependency Chain Generator")
    print("  POL-07 → STD-03 → STD-11 → PRC-03")
    print(f"  Organisation: {ORG_PROFILE.org_name}")
    print(f"  Jurisdiction:  {ORG_PROFILE.jurisdiction}")
    print("=" * 70)
    print()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("[Init] Loading PolicyFactory (embedding index + cross-encoder)...")
    t_init = time.time()
    factory = PolicyFactory()
    print(f"[Init] Ready in {time.time() - t_init:.1f}s\n")

    results = []

    for i, entry in enumerate(CHAIN, start=1):
        doc_id   = entry["doc_id"]
        doc_type = entry["doc_type"]
        topic    = entry["topic"]

        print(f"\n{'='*70}")
        print(f"  [{i}/{len(CHAIN)}]  {doc_id}  {doc_type.upper()}  —  {topic}")
        print(f"{'='*70}")

        # Skip if DOCX already exists
        out_docx = os.path.join(OUTPUT_DIR, f"{doc_id}.docx")
        if os.path.exists(out_docx):
            size_kb = os.path.getsize(out_docx) // 1024
            print(f"  SKIP — already exists: {out_docx}  ({size_kb} KB)")
            results.append({
                "doc_id": doc_id, "doc_type": doc_type,
                "status": "skipped", "path": out_docx,
            })
            continue

        spec = DocumentSpec(
            doc_id          = doc_id,
            doc_type        = doc_type,
            topic           = topic,
            scope           = entry["scope"],
            target_audience = entry["target_audience"],
            version         = "1.0",
        )

        t0 = time.time()
        try:
            result = factory.run(
                profile    = ORG_PROFILE,
                spec       = spec,
                output_dir = OUTPUT_DIR,
            )
            elapsed = time.time() - t0

            print(f"\n  OK  {doc_id} complete  ({elapsed:.0f}s)")
            _print_summary(result)
            results.append({**result, "status": "ok", "elapsed": elapsed})

        except Exception as exc:
            elapsed = time.time() - t0
            print(f"\n  FAIL  {doc_id}  ({elapsed:.0f}s): {exc}")
            traceback.print_exc()
            results.append({
                "doc_id": doc_id, "doc_type": doc_type,
                "status": "failed", "error": str(exc), "elapsed": elapsed,
            })

    # ── Final report ──────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("  GENERATION COMPLETE")
    print(f"{'='*70}")

    ok      = [r for r in results if r["status"] == "ok"]
    skipped = [r for r in results if r["status"] == "skipped"]
    failed  = [r for r in results if r["status"] == "failed"]

    print(f"  Generated: {len(ok)}   Skipped: {len(skipped)}   Failed: {len(failed)}")
    print()

    for r in results:
        icon = {"ok": "✓", "skipped": "–", "failed": "✗"}.get(r["status"], "?")
        if r["status"] == "ok":
            qa  = "PASS" if r.get("qa_passed") else "WARN"
            sec = f"{r.get('elapsed', 0):.0f}s"
            print(f"  {icon}  {r['doc_id']:<8}  {r.get('document_type', r.get('doc_type', '')):<10}  "
                  f"QA:{qa}  {sec}")
            for key in ("main_docx", "traceability_docx"):
                path = r.get(key)
                if path and os.path.exists(path):
                    kb = os.path.getsize(path) // 1024
                    print(f"           {path}  ({kb} KB)")
        elif r["status"] == "skipped":
            print(f"  {icon}  {r['doc_id']:<8}  already exists")
        else:
            print(f"  {icon}  {r['doc_id']:<8}  FAILED: {r.get('error', '')[:80]}")

    # List all chain output files
    print()
    chain_ids = {e["doc_id"] for e in CHAIN}
    docx_files = sorted(
        f for f in os.listdir(OUTPUT_DIR)
        if f.endswith(".docx") and any(f.startswith(did) for did in chain_ids)
    )
    if docx_files:
        print(f"  Output files in {OUTPUT_DIR}/")
        for fname in docx_files:
            path = os.path.join(OUTPUT_DIR, fname)
            kb   = os.path.getsize(path) // 1024
            print(f"    {fname}  ({kb} KB)")

    return len(failed) == 0


def _print_summary(r: dict):
    doc_type = r.get("document_type", r.get("doc_type", ""))

    if doc_type == "policy":
        print(f"     Elements:     {r.get('policy_elements', '?')}")
        print(f"     Subprograms:  {r.get('subprograms', '?')}/34")
        print(f"     QA:           {'PASS' if r.get('qa_passed') else 'FAIL'}")
        print(f"     SHALL traced: {r.get('traced_count', '?')}/{r.get('shall_count', '?')}")

    elif doc_type == "standard":
        print(f"     Definitions:  {r.get('definitions', '?')}")
        print(f"     Domains:      {r.get('domains', '?')}")
        print(f"     Requirements: {r.get('total_reqs', '?')}  ({r.get('shall_count', '?')} shall)")
        print(f"     QA:           {'PASS' if r.get('qa_passed') else 'FAIL'}")
        print(f"     SHALL traced: {r.get('traced_count', '?')}/{r.get('shall_count', '?')}")

    elif doc_type == "procedure":
        print(f"     Parent POL:   {r.get('parent_policy_id', '?')}")
        print(f"     Parent STD:   {r.get('parent_standard_id', '?')}")
        print(f"     Phases:       {r.get('phases', '?')}")
        print(f"     Steps:        {r.get('total_steps', '?')}  ({r.get('cited_steps', '?')} cited)")
        print(f"     Verifications:{r.get('verification_checks', '?')}")
        print(f"     Diagrams:     {r.get('diagram_count', '?')}/2")
        print(f"     QA:           {'PASS' if r.get('qa_passed') else 'FAIL'}")

    if r.get("main_docx"):
        print(f"     Main DOCX:    {r['main_docx']}")
    if r.get("traceability_docx"):
        print(f"     Traceability: {r['traceability_docx']}")


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
