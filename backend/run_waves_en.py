"""
Generate Wave 1+2+3 (54 documents) in English using:
  - ministry_drafter_en.py   (GPT-4o English drafter)
  - ministry_renderer_pro.py (professional DOCX with cover page, headers, footers)

Output: policy_output/{doc_id}_en.docx  +  policy_output/{doc_id}_en.json
"""
import sys, os, json, time, traceback
sys.path.insert(0, os.path.dirname(__file__))

from app.policy_factory.ministry_drafter_en import (
    draft_policy_en, draft_standard_en, draft_procedure_en,
    extract_dependency_summary_en,
)
from app.policy_factory.ministry_renderer_pro import (
    render_pro_policy, render_pro_standard, render_pro_procedure,
)

OUTPUT_DIR   = os.path.join(os.path.dirname(__file__), "policy_output")
CATALOG_PATH = os.path.join(os.path.dirname(__file__), "docGenConstruct.json")

os.makedirs(OUTPUT_DIR, exist_ok=True)

with open(CATALOG_PATH, encoding="utf-8") as f:
    CATALOG = json.load(f)

DOC_INDEX = {d["id"]: d for d in CATALOG["documents"]}

# Wave 1+2+3 in exact order
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

# ── Pre-seed artifact cache from any existing English JSON files ──────────────
artifact_cache: dict[str, str] = {}
for fname in os.listdir(OUTPUT_DIR):
    if fname.endswith("_en.json") and not fname.startswith("~"):
        doc_id = fname[:-8]   # strip _en.json
        json_path = os.path.join(OUTPUT_DIR, fname)
        try:
            with open(json_path, encoding="utf-8") as jf:
                data = json.load(jf)
            meta     = data.get("meta", {})
            doc_type = meta.get("doc_type", "")
            title    = meta.get("title_en", meta.get("title_ar", ""))
            obj      = data.get("objective_ar", "")[:300]
            if doc_type == "policy":
                clauses = data.get("policy_clauses", [])[:6]
                lines   = "\n".join(f"- {c.get('text_ar','')}" for c in clauses)
                artifact_cache[doc_id] = f"[{doc_id}] {title}\nObjective: {obj}\nKey clauses:\n{lines}"
            elif doc_type == "standard":
                clusters = data.get("domain_clusters", [])
                lines    = "\n".join(f"- {c.get('cluster_id','')} {c.get('title_ar','')} ({len(c.get('clauses',[]))} clauses)" for c in clusters)
                artifact_cache[doc_id] = f"[{doc_id}] {title}\nObjective: {obj}\nDomain clusters:\n{lines}"
            else:
                phases = data.get("phases", [])
                lines  = "\n".join(f"- {p.get('phase_id','')} {p.get('phase_title_ar','')} ({len(p.get('steps',[]))} steps)" for p in phases)
                artifact_cache[doc_id] = f"[{doc_id}] {title}\nObjective: {obj}\nPhases:\n{lines}"
        except Exception:
            pass

print(f"Pre-seeded {len(artifact_cache)} English summaries from existing JSON files")
print(f"Generating {len(ALL_DOCS)} English documents (Wave 1+2+3)")
print("=" * 70)

completed, failed, skipped = [], [], []
total = len(ALL_DOCS)

for i, doc_id in enumerate(ALL_DOCS, 1):
    entry = DOC_INDEX.get(doc_id)
    if not entry:
        print(f"[{i}/{total}] SKIP  {doc_id} — not in catalog")
        skipped.append(doc_id)
        continue

    out_docx = os.path.join(OUTPUT_DIR, f"{doc_id}_en.docx")
    out_json = os.path.join(OUTPUT_DIR, f"{doc_id}_en.json")

    # Skip if fully done
    if os.path.exists(out_docx) and os.path.exists(out_json):
        print(f"[{i}/{total}] SKIP  {doc_id} — already exists")
        skipped.append(doc_id)
        continue

    doc_type = entry["type"]
    name_en  = entry["name_en"]
    deps     = entry.get("depends_on", [])
    wave_num = entry.get("wave", "?")

    dep_parts = [artifact_cache[d] for d in deps if d in artifact_cache]
    dep_ctx   = "\n\n---\n\n".join(dep_parts)

    print(f"[{i}/{total}] W{wave_num}  {doc_id}  {doc_type.upper()}  {name_en}", flush=True)
    t0 = time.time()

    try:
        # ── Draft (or reload from cached JSON to avoid re-calling the API) ──
        if os.path.exists(out_json):
            print(f"  Loading draft from cached JSON...", flush=True)
            from app.policy_factory.ministry_models import (
                MinistryPolicyDraft, MinistryStandardDraft, MinistryProcedureDraft,
            )
            with open(out_json, encoding="utf-8") as jf:
                data = json.load(jf)
            if doc_type == "policy":
                draft = MinistryPolicyDraft.model_validate(data)
            elif doc_type == "standard":
                draft = MinistryStandardDraft.model_validate(data)
            else:
                draft = MinistryProcedureDraft.model_validate(data)
        elif doc_type == "policy":
            draft = draft_policy_en(doc_id, name_en, dependency_context=dep_ctx)
        elif doc_type == "standard":
            draft = draft_standard_en(doc_id, name_en, dependency_context=dep_ctx)
        elif doc_type == "procedure":
            parent_pol = next((d for d in deps if d.startswith("POL-")), "")
            parent_std = next((d for d in deps if d.startswith("STD-")), "")
            draft = draft_procedure_en(
                doc_id, name_en, dependency_context=dep_ctx,
                parent_policy_id=parent_pol, parent_standard_id=parent_std,
            )
        else:
            print(f"  UNKNOWN type: {doc_type}")
            failed.append(doc_id)
            continue

        # Save JSON immediately (before rendering) so re-runs can skip drafting
        with open(out_json, "w", encoding="utf-8") as jf:
            json.dump(draft.model_dump(), jf, ensure_ascii=False, indent=2)

        # Cache summary for downstream docs
        artifact_cache[doc_id] = extract_dependency_summary_en(draft)

        # ── Render ──
        if doc_type == "policy":
            path = render_pro_policy(draft, OUTPUT_DIR, lang="en")
        elif doc_type == "standard":
            path = render_pro_standard(draft, OUTPUT_DIR, lang="en")
        else:
            path = render_pro_procedure(draft, OUTPUT_DIR, lang="en")

        elapsed = time.time() - t0
        size_kb = os.path.getsize(path) // 1024
        print(f"  OK  {os.path.basename(path)}  ({elapsed:.1f}s, {size_kb}KB)", flush=True)
        completed.append(doc_id)

    except Exception as exc:
        elapsed = time.time() - t0
        print(f"  FAIL ({elapsed:.1f}s): {exc}", flush=True)
        traceback.print_exc()
        failed.append(doc_id)

# ── Summary ────────────────────────────────────────────────────────────────────
print()
print("=" * 70)
print(f"COMPLETE  {len(completed)}/{total} generated  |  {len(skipped)} skipped  |  {len(failed)} failed")

en_files  = sorted(f for f in os.listdir(OUTPUT_DIR) if f.endswith("_en.docx") and not f.startswith("~"))
pol_files = [f for f in en_files if f.startswith("POL-")]
std_files = [f for f in en_files if f.startswith("STD-")]
prc_files = [f for f in en_files if f.startswith("PRC-")]
print(f"\nEnglish DOCX in policy_output/:")
print(f"  POL: {len(pol_files)}")
print(f"  STD: {len(std_files)}")
print(f"  PRC: {len(prc_files)}")
print(f"  Total: {len(en_files)}")

if failed:
    print(f"\nFailed: {failed}")
