"""Retry the 3 documents that failed due to API connection errors."""
import sys, os, json, time, traceback
sys.path.insert(0, os.path.dirname(__file__))

from app.policy_factory.ministry_drafter import (
    draft_policy, draft_standard, draft_procedure, extract_dependency_summary
)
from app.policy_factory.ministry_renderer import (
    render_ministry_policy, render_ministry_standard, render_ministry_procedure
)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "policy_output")
CATALOG_PATH = os.path.join(os.path.dirname(__file__), "docGenConstruct.json")
with open(CATALOG_PATH, encoding="utf-8") as f:
    CATALOG = json.load(f)
DOC_INDEX = {d["id"]: d for d in CATALOG["documents"]}

FAILED = ["PRC-44", "PRC-32", "PRC-10"]

# Load existing dependency summaries from already-generated JSON files
artifact_cache: dict[str, str] = {}
for fname in os.listdir(OUTPUT_DIR):
    if fname.endswith(".json") and not fname.startswith("~"):
        doc_id = fname[:-5]
        json_path = os.path.join(OUTPUT_DIR, fname)
        try:
            with open(json_path, encoding="utf-8") as jf:
                data = json.load(jf)
            meta = data.get("meta", {})
            doc_type = meta.get("doc_type", "")
            if doc_type == "policy":
                clauses = data.get("policy_clauses", [])[:8]
                summary = (
                    f"[{doc_id}] {meta.get('title_ar', '')}\n"
                    f"الهدف: {data.get('objective_ar', '')[:300]}\n"
                    f"أبرز بنود السياسة:\n" +
                    "\n".join(f"- {c.get('text_ar','')}" for c in clauses)
                )
            elif doc_type == "standard":
                clusters = data.get("domain_clusters", [])
                summary = (
                    f"[{doc_id}] {meta.get('title_ar', '')}\n"
                    f"الهدف: {data.get('objective_ar', '')[:300]}\n"
                    f"المجموعات:\n" +
                    "\n".join(f"- {c.get('cluster_id','')} {c.get('title_ar','')}" for c in clusters)
                )
            else:
                phases = data.get("phases", [])
                summary = (
                    f"[{doc_id}] {meta.get('title_ar', '')}\n"
                    f"الهدف: {data.get('objective_ar', '')[:300]}\n"
                    f"المراحل:\n" +
                    "\n".join(f"- {p.get('phase_id','')} {p.get('phase_title_ar','')}" for p in phases)
                )
            artifact_cache[doc_id] = summary
        except Exception:
            pass

print(f"Loaded {len(artifact_cache)} cached summaries")
print(f"Retrying: {FAILED}\n")

completed, failed = [], []
for doc_id in FAILED:
    entry = DOC_INDEX.get(doc_id)
    if not entry:
        print(f"SKIP {doc_id} — not in catalog")
        continue

    doc_type = entry["type"]
    name_en  = entry["name_en"]
    name_ar  = entry["name_ar"]
    deps     = entry.get("depends_on", [])

    dep_parts = [artifact_cache[d] for d in deps if d in artifact_cache]
    dep_ctx   = "\n\n---\n\n".join(dep_parts)

    print(f"  {doc_id}  {doc_type.upper()}  {name_en}", flush=True)
    t0 = time.time()
    try:
        parent_pol = next((d for d in deps if d.startswith("POL-")), "")
        parent_std = next((d for d in deps if d.startswith("STD-")), "")
        draft = draft_procedure(
            doc_id, name_en, name_ar, dep_ctx,
            parent_policy_id=parent_pol, parent_standard_id=parent_std,
        )
        path = render_ministry_procedure(draft, OUTPUT_DIR)
        json_path = os.path.join(OUTPUT_DIR, f"{doc_id}.json")
        with open(json_path, "w", encoding="utf-8") as jf:
            json.dump(draft.model_dump(), jf, ensure_ascii=False, indent=2)
        elapsed = time.time() - t0
        print(f"    OK  {os.path.basename(path)}  ({elapsed:.1f}s)", flush=True)
        completed.append(doc_id)
    except Exception as exc:
        elapsed = time.time() - t0
        print(f"    FAIL ({elapsed:.1f}s): {exc}", flush=True)
        failed.append(doc_id)

print(f"\nRETRY DONE: {len(completed)} OK, {len(failed)} still failed")
if failed:
    print(f"Still failing: {failed}")

# Final count
docx_files = sorted(f for f in os.listdir(OUTPUT_DIR) if f.endswith(".docx") and not f.startswith("~"))
pol = len([f for f in docx_files if f.startswith("POL-")])
std = len([f for f in docx_files if f.startswith("STD-")])
prc = len([f for f in docx_files if f.startswith("PRC-")])
print(f"\nFinal Ministry DOCX count: POL={pol}  STD={std}  PRC={prc}  Total={pol+std+prc}")
