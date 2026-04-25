"""
Re-render all existing Arabic JSON files with the professional renderer.
Reads {doc_id}.json from policy_output/ and writes {doc_id}_ar.docx.

Skips docs that already have a {doc_id}_ar.docx (use --force to overwrite).
"""
import sys, os, json, time, argparse
sys.path.insert(0, os.path.dirname(__file__))

from app.policy_factory.ministry_models import (
    MinistryPolicyDraft, MinistryStandardDraft, MinistryProcedureDraft,
)
from app.policy_factory.ministry_renderer_pro import (
    render_pro_policy, render_pro_standard, render_pro_procedure,
)

parser = argparse.ArgumentParser()
parser.add_argument("--force", action="store_true", help="Overwrite existing _ar.docx files")
args = parser.parse_args()

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "policy_output")

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

completed, skipped, failed = [], [], []
total = len(ALL_DOCS)
print(f"Re-rendering {total} Arabic docs with professional layout")
print("=" * 70)

for i, doc_id in enumerate(ALL_DOCS, 1):
    json_path = os.path.join(OUTPUT_DIR, f"{doc_id}.json")
    out_path  = os.path.join(OUTPUT_DIR, f"{doc_id}_ar.docx")

    if not os.path.exists(json_path):
        print(f"[{i}/{total}] MISSING  {doc_id}.json — skipping")
        skipped.append(doc_id)
        continue

    if os.path.exists(out_path) and not args.force:
        print(f"[{i}/{total}] SKIP  {doc_id} — {doc_id}_ar.docx already exists")
        skipped.append(doc_id)
        continue

    t0 = time.time()
    try:
        with open(json_path, encoding="utf-8") as jf:
            data = json.load(jf)
        doc_type = data.get("meta", {}).get("doc_type", "")

        if doc_type == "policy":
            draft = MinistryPolicyDraft.model_validate(data)
            path  = render_pro_policy(draft, OUTPUT_DIR, lang="ar")
        elif doc_type == "standard":
            draft = MinistryStandardDraft.model_validate(data)
            path  = render_pro_standard(draft, OUTPUT_DIR, lang="ar")
        elif doc_type == "procedure":
            draft = MinistryProcedureDraft.model_validate(data)
            path  = render_pro_procedure(draft, OUTPUT_DIR, lang="ar")
        else:
            print(f"[{i}/{total}] UNKNOWN type '{doc_type}' for {doc_id}")
            failed.append(doc_id)
            continue

        elapsed = time.time() - t0
        size_kb = os.path.getsize(path) // 1024
        print(f"[{i}/{total}] OK  {os.path.basename(path)}  ({elapsed:.1f}s, {size_kb}KB)", flush=True)
        completed.append(doc_id)

    except Exception as exc:
        elapsed = time.time() - t0
        print(f"[{i}/{total}] FAIL  {doc_id}  ({elapsed:.1f}s): {exc}", flush=True)
        failed.append(doc_id)

print()
print("=" * 70)
print(f"DONE  {len(completed)} re-rendered  |  {len(skipped)} skipped  |  {len(failed)} failed")

ar_files = sorted(f for f in os.listdir(OUTPUT_DIR) if f.endswith("_ar.docx") and not f.startswith("~"))
print(f"\nArabic pro DOCX in policy_output/: {len(ar_files)}")
if failed:
    print(f"Failed: {failed}")
