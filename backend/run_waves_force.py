"""
Force-regenerate Wave 1+2+3 (54 docs) using the new Arabic ministry factory.
Uses skip_existing=False — overwrites old English-format files.
Runs independently of the orchestrator singleton.
"""
import sys, os, json, time, traceback
sys.path.insert(0, os.path.dirname(__file__))

from app.policy_factory.ministry_drafter import (
    draft_policy, draft_standard, draft_procedure, extract_dependency_summary
)
from app.policy_factory.ministry_renderer import (
    render_ministry_policy, render_ministry_standard, render_ministry_procedure
)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "policy_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

CATALOG_PATH = os.path.join(os.path.dirname(__file__), "docGenConstruct.json")
with open(CATALOG_PATH, encoding="utf-8") as f:
    CATALOG = json.load(f)

DOC_INDEX = {d["id"]: d for d in CATALOG["documents"]}

# Wave 1+2+3 in exact wave order
WAVE_1 = ["POL-01","POL-12","POL-08","POL-34","POL-17","POL-09",
           "POL-06","POL-07","POL-14","POL-19","POL-16","POL-33"]
WAVE_2 = ["STD-15","STD-26","STD-02","STD-03","STD-11","STD-09",
           "STD-13","STD-04","STD-08","STD-22","STD-14","STD-16",
           "STD-29","STD-05","STD-07","STD-06","STD-12","STD-23",
           "STD-31","STD-32"]
WAVE_3 = ["PRC-01","PRC-02","PRC-03","PRC-04","PRC-05","PRC-30",
           "PRC-25","PRC-26","PRC-27","PRC-22","PRC-09","PRC-33",
           "PRC-31","PRC-43","PRC-44","PRC-32","PRC-10","PRC-40",
           "PRC-15","PRC-21","PRC-23","PRC-24"]

ALL_DOCS = WAVE_1 + WAVE_2 + WAVE_3

# Artifact cache for dependency context injection
artifact_cache: dict[str, str] = {}

completed, failed = [], []
total = len(ALL_DOCS)

print(f"Starting generation: {total} documents (Wave 1+2+3)")
print(f"Output: {OUTPUT_DIR}")
print("=" * 70)

for i, doc_id in enumerate(ALL_DOCS, 1):
    entry    = DOC_INDEX.get(doc_id)
    if not entry:
        print(f"[{i}/{total}] SKIP  {doc_id} — not in catalog")
        continue

    doc_type = entry["type"]
    name_en  = entry["name_en"]
    name_ar  = entry["name_ar"]
    deps     = entry.get("depends_on", [])

    # Build dependency context from already-generated summaries
    dep_parts = [artifact_cache[d] for d in deps if d in artifact_cache]
    dep_ctx   = "\n\n---\n\n".join(dep_parts)

    wave_num = entry.get("wave", "?")
    print(f"[{i}/{total}] W{wave_num}  {doc_id}  {doc_type.upper()}  {name_en}", flush=True)

    t0 = time.time()
    try:
        if doc_type == "policy":
            draft = draft_policy(doc_id, name_en, name_ar, dep_ctx)
            path  = render_ministry_policy(draft, OUTPUT_DIR)

        elif doc_type == "standard":
            draft = draft_standard(doc_id, name_en, name_ar, dep_ctx)
            path  = render_ministry_standard(draft, OUTPUT_DIR)

        elif doc_type == "procedure":
            parent_pol = next((d for d in deps if d.startswith("POL-")), "")
            parent_std = next((d for d in deps if d.startswith("STD-")), "")
            draft = draft_procedure(
                doc_id, name_en, name_ar, dep_ctx,
                parent_policy_id=parent_pol, parent_standard_id=parent_std,
            )
            path  = render_ministry_procedure(draft, OUTPUT_DIR)

        else:
            print(f"  UNKNOWN type: {doc_type}")
            failed.append(doc_id)
            continue

        # Cache summary for downstream docs
        artifact_cache[doc_id] = extract_dependency_summary(draft)

        # Save JSON draft for inspection
        json_path = os.path.join(OUTPUT_DIR, f"{doc_id}.json")
        with open(json_path, "w", encoding="utf-8") as jf:
            json.dump(draft.model_dump(), jf, ensure_ascii=False, indent=2)

        elapsed = time.time() - t0
        print(f"  OK  {os.path.basename(path)}  ({elapsed:.1f}s)", flush=True)
        completed.append(doc_id)

    except Exception as exc:
        elapsed = time.time() - t0
        print(f"  FAIL ({elapsed:.1f}s): {exc}", flush=True)
        traceback.print_exc()
        failed.append(doc_id)

# ── Summary ────────────────────────────────────────────────────────────────────
print()
print("=" * 70)
print(f"COMPLETE  {len(completed)}/{total} generated  |  {len(failed)} failed")

docx_files = sorted(f for f in os.listdir(OUTPUT_DIR) if f.endswith(".docx") and not f.startswith("~"))
policy_files   = [f for f in docx_files if f.startswith("POL-")]
standard_files = [f for f in docx_files if f.startswith("STD-")]
proc_files     = [f for f in docx_files if f.startswith("PRC-")]
print(f"\nMinistry DOCX in policy_output/:")
print(f"  POL files: {len(policy_files)}")
print(f"  STD files: {len(standard_files)}")
print(f"  PRC files: {len(proc_files)}")

if failed:
    print(f"\nFailed: {failed}")
