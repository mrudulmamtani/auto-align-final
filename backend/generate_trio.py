"""
Generate one Policy, one Standard, and one Procedure using the
LangChain-based BIG4 pipeline.

Documents:
  POL-01  Cybersecurity Governance Policy
  STD-15  Cybersecurity Risk Management Standard  (deps: POL-08, POL-12)
  PRC-01  Cybersecurity Incident Management Procedure  (deps: POL-06, STD-02, STD-03)

Output: policy_output_big4/{doc_id}_big4.docx  +  {doc_id}_big4.json
"""
import sys, os, json, time, traceback

sys.path.insert(0, os.path.dirname(__file__))

from app.policy_factory.langchain_drafter import (
    draft_policy_lc,
    draft_standard_lc,
    draft_procedure_lc,
)
from app.policy_factory.big4_renderer import (
    render_policy,
    render_standard,
    render_procedure,
)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "policy_output_big4")
os.makedirs(OUTPUT_DIR, exist_ok=True)

TRIO = [
    {
        "doc_id":   "POL-01",
        "type":     "policy",
        "title":    "Cybersecurity Governance Policy",
        "depends_on": [],
    },
    {
        "doc_id":   "STD-15",
        "type":     "standard",
        "title":    "Cybersecurity Risk Management Standard",
        "depends_on": ["POL-08", "POL-12"],
    },
    {
        "doc_id":          "PRC-01",
        "type":            "procedure",
        "title":           "Cybersecurity Incident Management Procedure",
        "parent_policy":   "POL-06",
        "parent_standard": "STD-02",
        "depends_on":      ["POL-06", "STD-02", "STD-03"],
    },
]

completed, failed = [], []

for entry in TRIO:
    doc_id = entry["doc_id"]
    title  = entry["title"]
    dtype  = entry["type"]

    out_docx = os.path.join(OUTPUT_DIR, f"{doc_id}_big4.docx")
    out_json = os.path.join(OUTPUT_DIR, f"{doc_id}_big4.json")

    print(f"\n{'='*70}")
    print(f"  {doc_id}  {dtype.upper()}  —  {title}")
    print(f"{'='*70}", flush=True)

    t0 = time.time()
    try:
        # ── Draft (or reload from cached JSON) ────────────────────────────────
        if os.path.exists(out_json):
            print(f"  Loading draft from cached JSON: {out_json}", flush=True)
            from app.policy_factory.langchain_drafter import (
                PolicySpec, StandardSpec, ProcedureSpec,
            )
            with open(out_json, encoding="utf-8") as jf:
                data = json.load(jf)
            if dtype == "policy":
                draft = PolicySpec.model_validate(data)
            elif dtype == "standard":
                draft = StandardSpec.model_validate(data)
            else:
                draft = ProcedureSpec.model_validate(data)
        else:
            print(f"  Drafting via LangChain (GPT-4o)…", flush=True)
            if dtype == "policy":
                draft = draft_policy_lc(
                    doc_id,
                    title,
                    depends_on=entry["depends_on"],
                )
            elif dtype == "standard":
                draft = draft_standard_lc(
                    doc_id,
                    title,
                    depends_on=entry["depends_on"],
                )
            else:
                draft = draft_procedure_lc(
                    doc_id,
                    title,
                    parent_policy=entry["parent_policy"],
                    parent_standard=entry["parent_standard"],
                    depends_on=entry["depends_on"],
                )

            # Save JSON immediately so a re-run skips the API call
            with open(out_json, "w", encoding="utf-8") as jf:
                json.dump(draft.model_dump(), jf, ensure_ascii=False, indent=2)
            print(f"  Draft saved -> {out_json}", flush=True)

        draft_elapsed = time.time() - t0

        # ── Render ────────────────────────────────────────────────────────────
        print(f"  Rendering DOCX…", flush=True)
        if dtype == "policy":
            path = render_policy(draft, OUTPUT_DIR)
        elif dtype == "standard":
            path = render_standard(draft, OUTPUT_DIR)
        else:
            path = render_procedure(draft, OUTPUT_DIR)

        elapsed  = time.time() - t0
        size_kb  = os.path.getsize(path) // 1024
        print(f"  OK  {os.path.basename(path)}  "
              f"({elapsed:.1f}s total, {size_kb} KB)", flush=True)
        completed.append(doc_id)

    except Exception as exc:
        elapsed = time.time() - t0
        print(f"  FAIL ({elapsed:.1f}s): {exc}", flush=True)
        traceback.print_exc()
        failed.append(doc_id)

# ── Summary ────────────────────────────────────────────────────────────────────
print(f"\n{'='*70}")
print(f"COMPLETE  {len(completed)}/3 generated  |  {len(failed)} failed")
if failed:
    print(f"Failed:   {failed}")

print(f"\nOutput files in  {OUTPUT_DIR}/")
for f in sorted(os.listdir(OUTPUT_DIR)):
    if not f.startswith("~"):
        path = os.path.join(OUTPUT_DIR, f)
        kb   = os.path.getsize(path) // 1024
        print(f"  {f}  ({kb} KB)")
