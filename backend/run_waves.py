"""Run Wave 1+2+3 generation (54 documents)."""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))

from app.policy_factory.orchestrator import start_orchestration, get_state

doc_ids = [
    # Wave 1 — Foundation Policies (12)
    "POL-01","POL-12","POL-08","POL-34","POL-17","POL-09",
    "POL-06","POL-07","POL-14","POL-19","POL-16","POL-33",
    # Wave 2 — Core Standards (20)
    "STD-15","STD-26","STD-02","STD-03","STD-11","STD-09",
    "STD-13","STD-04","STD-08","STD-22","STD-14","STD-16",
    "STD-29","STD-05","STD-07","STD-06","STD-12","STD-23",
    "STD-31","STD-32",
    # Wave 3 — High-Impact Procedures (22)
    "PRC-01","PRC-02","PRC-03","PRC-04","PRC-05","PRC-30",
    "PRC-25","PRC-26","PRC-27","PRC-22","PRC-09","PRC-33",
    "PRC-31","PRC-43","PRC-44","PRC-32","PRC-10","PRC-40",
    "PRC-15","PRC-21","PRC-23","PRC-24",
]

started = start_orchestration(
    doc_ids=doc_ids,
    org_name="الوزارة",
    skip_existing=True,
)
print(f"Orchestration started: {started}")
print(f"Total docs queued: {len(doc_ids)}")
print()

prev_completed = -1
prev_doc = ""

while True:
    state = get_state()
    s = state.to_dict()

    changed = (s["completed_count"] != prev_completed or s["current_doc"] != prev_doc)
    if changed:
        prev_completed = s["completed_count"]
        prev_doc = s["current_doc"] or ""
        line = f"[{s['completed_count']}/{s['total_docs']}] {s['status'].upper()}"
        if s["current_doc"]:
            line += f" | NOW: {s['current_doc']}"
        if s["failed_count"]:
            line += f" | FAILED: {s['failed_count']}"
        print(line, flush=True)

    if s["status"] in ("completed", "failed", "paused"):
        break
    time.sleep(5)

final = get_state().to_dict()
print()
print("=" * 60)
print(f"DONE  completed={final['completed_count']}  failed={final['failed_count']}  skipped={len(final['skipped_docs'])}")
if final["failed_docs"]:
    print(f"Failed IDs: {final['failed_docs']}")

# List generated DOCX files
out_dir = os.path.join(os.path.dirname(__file__), "policy_output")
if os.path.exists(out_dir):
    files = sorted(f for f in os.listdir(out_dir) if f.endswith(".docx"))
    print(f"\nGenerated {len(files)} DOCX files in policy_output/")
    for f in files:
        print(f"  {f}")
