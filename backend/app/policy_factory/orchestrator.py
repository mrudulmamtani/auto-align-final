"""
Ministry Document Orchestrator — wave-based generation engine.

Reads docGenConstruct.json and generates all 110 documents in wave order.
Each document receives the summaries of its dependency documents as context,
ensuring consistency across the document hierarchy.

Wave order:
  Wave 1 → Foundation policies (POL-01 first, no dependencies)
  Wave 2 → Core standards (depend on Wave 1 policies)
  Wave 3 → High-impact procedures (depend on Wave 1+2)
  Wave 4 → Remaining policies
  Wave 5 → Remaining standards
  Wave 6 → Remaining procedures
"""
from __future__ import annotations
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .ministry_drafter import draft_policy, draft_standard, draft_procedure, extract_dependency_summary
from .ministry_renderer import render_ministry_policy, render_ministry_standard, render_ministry_procedure
from .ministry_models import MinistryPolicyDraft, MinistryStandardDraft, MinistryProcedureDraft
from .config import OUTPUT_DIR

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_CATALOG_PATH = _BACKEND_DIR / "docGenConstruct.json"


def _load_catalog() -> dict:
    with open(_CATALOG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _get_wave_order(catalog: dict) -> list[list[str]]:
    """Return list of waves, each wave is a list of doc_ids in order."""
    gen_order = catalog.get("generation_order", {})
    waves = []
    for wave_key in sorted(gen_order.keys()):
        waves.append(gen_order[wave_key])
    return waves


def _build_doc_index(catalog: dict) -> dict[str, dict]:
    """Return {doc_id: doc_entry} index."""
    return {d["id"]: d for d in catalog.get("documents", [])}


# ── Orchestrator state ─────────────────────────────────────────────────────────

class OrchestratorState:
    """Thread-safe state for a running orchestration job."""

    def __init__(self):
        self._lock = threading.Lock()
        self.status: str = "idle"          # idle | running | completed | failed | paused
        self.current_doc: Optional[str] = None
        self.current_wave: int = 0
        self.total_docs: int = 0
        self.completed_docs: list[str] = []
        self.failed_docs: list[str] = []
        self.skipped_docs: list[str] = []
        self.log: list[dict] = []
        self.started_at: Optional[str] = None
        self.completed_at: Optional[str] = None
        self.error: Optional[str] = None
        # artifact cache: doc_id -> summary string (used as dependency context)
        self._artifact_cache: dict[str, str] = {}
        # thread reference
        self._thread: Optional[threading.Thread] = None
        # stop signal
        self._stop_requested: bool = False

    def log_event(self, level: str, doc_id: str, msg: str):
        with self._lock:
            self.log.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "level": level,
                "doc_id": doc_id,
                "msg": msg,
            })

    def set_status(self, status: str):
        with self._lock:
            self.status = status

    def mark_started(self, total: int):
        with self._lock:
            self.status = "running"
            self.total_docs = total
            self.started_at = datetime.now(timezone.utc).isoformat()

    def mark_doc_complete(self, doc_id: str):
        with self._lock:
            self.completed_docs.append(doc_id)
            self.current_doc = None

    def mark_doc_failed(self, doc_id: str, error: str):
        with self._lock:
            self.failed_docs.append(doc_id)
            self.current_doc = None
            self.log.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "level": "ERROR",
                "doc_id": doc_id,
                "msg": error,
            })

    def set_current(self, doc_id: str, wave: int):
        with self._lock:
            self.current_doc = doc_id
            self.current_wave = wave

    def cache_artifact(self, doc_id: str, summary: str):
        with self._lock:
            self._artifact_cache[doc_id] = summary

    def get_dependency_context(self, dep_ids: list[str]) -> str:
        """Assemble dependency context from cached summaries."""
        parts = []
        with self._lock:
            for dep_id in dep_ids:
                summary = self._artifact_cache.get(dep_id, "")
                if summary:
                    parts.append(summary)
        return "\n\n---\n\n".join(parts)

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "status": self.status,
                "current_doc": self.current_doc,
                "current_wave": self.current_wave,
                "total_docs": self.total_docs,
                "completed_count": len(self.completed_docs),
                "failed_count": len(self.failed_docs),
                "completed_docs": list(self.completed_docs),
                "failed_docs": list(self.failed_docs),
                "skipped_docs": list(self.skipped_docs),
                "started_at": self.started_at,
                "completed_at": self.completed_at,
                "error": self.error,
                "recent_log": self.log[-30:],  # last 30 events
            }


# ── Singleton state ────────────────────────────────────────────────────────────
_state = OrchestratorState()


def get_state() -> OrchestratorState:
    return _state


# ── Core generation function ───────────────────────────────────────────────────

def _generate_single(
    doc_entry: dict,
    state: OrchestratorState,
    output_dir: str,
    org_name: str,
    skip_existing: bool,
) -> bool:
    """Generate one document. Returns True on success."""
    doc_id   = doc_entry["id"]
    doc_type = doc_entry["type"]
    name_en  = doc_entry["name_en"]
    name_ar  = doc_entry["name_ar"]
    deps     = doc_entry.get("depends_on", [])
    wave     = doc_entry.get("wave", 0)

    # Skip if already exists
    out_path = os.path.join(output_dir, f"{doc_id}.docx")
    if skip_existing and os.path.exists(out_path):
        state.log_event("SKIP", doc_id, f"Already exists: {out_path}")
        with state._lock:
            state.skipped_docs.append(doc_id)
        return True

    state.log_event("START", doc_id, f"Generating {doc_type}: {name_en}")
    dep_ctx = state.get_dependency_context(deps)

    try:
        if doc_type == "policy":
            draft = draft_policy(
                doc_id=doc_id,
                name_en=name_en,
                name_ar=name_ar,
                dependency_context=dep_ctx,
                org_name=org_name,
            )
            path = render_ministry_policy(draft, output_dir)

        elif doc_type == "standard":
            draft = draft_standard(
                doc_id=doc_id,
                name_en=name_en,
                name_ar=name_ar,
                dependency_context=dep_ctx,
                org_name=org_name,
            )
            path = render_ministry_standard(draft, output_dir)

        elif doc_type == "procedure":
            # Find parent policy and standard from depends_on
            parent_pol = next((d for d in deps if d.startswith("POL-")), "")
            parent_std = next((d for d in deps if d.startswith("STD-")), "")
            draft = draft_procedure(
                doc_id=doc_id,
                name_en=name_en,
                name_ar=name_ar,
                dependency_context=dep_ctx,
                org_name=org_name,
                parent_policy_id=parent_pol,
                parent_standard_id=parent_std,
            )
            path = render_ministry_procedure(draft, output_dir)

        else:
            state.log_event("WARN", doc_id, f"Unknown doc_type: {doc_type}")
            return False

        # Cache the summary for downstream dependency injection
        summary = extract_dependency_summary(draft)
        state.cache_artifact(doc_id, summary)

        # Also save the draft as JSON for inspection/re-rendering
        json_path = os.path.join(output_dir, f"{doc_id}.json")
        with open(json_path, "w", encoding="utf-8") as jf:
            json.dump(draft.model_dump(), jf, ensure_ascii=False, indent=2)

        state.log_event("OK", doc_id, f"Saved: {path}")
        state.mark_doc_complete(doc_id)
        return True

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        state.mark_doc_failed(doc_id, f"{exc}\n{tb[:500]}")
        return False


# ── Wave runner ────────────────────────────────────────────────────────────────

def _run_waves(
    doc_ids: Optional[list[str]],
    output_dir: str,
    org_name: str,
    skip_existing: bool,
):
    """Background thread: run generation for specified doc_ids or all."""
    global _state

    catalog   = _load_catalog()
    doc_index = _build_doc_index(catalog)
    waves     = _get_wave_order(catalog)

    # Determine what to generate
    if doc_ids:
        target_ids = set(doc_ids)
    else:
        target_ids = set(doc_index.keys())

    # Build ordered list respecting wave order
    ordered = []
    for wave_docs in waves:
        for doc_id in wave_docs:
            if doc_id in target_ids and doc_id in doc_index:
                ordered.append(doc_index[doc_id])

    # Add any target_ids not found in waves (shouldn't happen with correct catalog)
    found = {d["id"] for d in ordered}
    for doc_id in target_ids:
        if doc_id not in found and doc_id in doc_index:
            ordered.append(doc_index[doc_id])

    _state.mark_started(len(ordered))
    os.makedirs(output_dir, exist_ok=True)

    wave_num = 0
    for wave_docs in waves:
        wave_num += 1
        for doc_id in wave_docs:
            if _state._stop_requested:
                _state.log_event("INFO", "", "Stop requested — halting.")
                _state.set_status("paused")
                return
            if doc_id not in target_ids or doc_id not in doc_index:
                continue
            _state.set_current(doc_id, wave_num)
            _generate_single(doc_index[doc_id], _state, output_dir, org_name, skip_existing)

    _state.set_status("completed")
    with _state._lock:
        _state.completed_at = datetime.now(timezone.utc).isoformat()


# ── Public API ─────────────────────────────────────────────────────────────────

def start_orchestration(
    doc_ids: Optional[list[str]] = None,
    output_dir: str = OUTPUT_DIR,
    org_name: str = "الوزارة",
    skip_existing: bool = True,
) -> bool:
    """Start orchestration in a background thread. Returns False if already running."""
    global _state
    if _state.status == "running":
        return False

    _state = OrchestratorState()
    _state._stop_requested = False

    thread = threading.Thread(
        target=_run_waves,
        args=(doc_ids, output_dir, org_name, skip_existing),
        daemon=True,
    )
    _state._thread = thread
    thread.start()
    return True


def stop_orchestration() -> bool:
    """Request the running orchestration to stop."""
    if _state.status != "running":
        return False
    with _state._lock:
        _state._stop_requested = True
    return True


def generate_single_document(
    doc_id: str,
    output_dir: str = OUTPUT_DIR,
    org_name: str = "الوزارة",
    dependency_context: str = "",
) -> dict:
    """Generate a single document synchronously. Returns result dict."""
    catalog   = _load_catalog()
    doc_index = _build_doc_index(catalog)

    if doc_id not in doc_index:
        return {"success": False, "error": f"Document {doc_id} not found in catalog"}

    entry = doc_index[doc_id]
    doc_type = entry["type"]
    name_en  = entry["name_en"]
    name_ar  = entry["name_ar"]
    deps     = entry.get("depends_on", [])

    os.makedirs(output_dir, exist_ok=True)

    try:
        if doc_type == "policy":
            draft = draft_policy(doc_id, name_en, name_ar, dependency_context)
            path  = render_ministry_policy(draft, output_dir)
        elif doc_type == "standard":
            draft = draft_standard(doc_id, name_en, name_ar, dependency_context)
            path  = render_ministry_standard(draft, output_dir)
        else:
            parent_pol = next((d for d in deps if d.startswith("POL-")), "")
            parent_std = next((d for d in deps if d.startswith("STD-")), "")
            draft = draft_procedure(
                doc_id, name_en, name_ar, dependency_context,
                parent_policy_id=parent_pol, parent_standard_id=parent_std,
            )
            path = render_ministry_procedure(draft, output_dir)

        # Save JSON
        json_path = os.path.join(output_dir, f"{doc_id}.json")
        with open(json_path, "w", encoding="utf-8") as jf:
            json.dump(draft.model_dump(), jf, ensure_ascii=False, indent=2)

        summary = extract_dependency_summary(draft)
        return {"success": True, "doc_id": doc_id, "path": path, "summary": summary}

    except Exception as exc:
        import traceback
        return {"success": False, "error": str(exc), "traceback": traceback.format_exc()}


def get_catalog() -> dict:
    """Return the full document catalog with generation order."""
    return _load_catalog()


def get_generated_docs(output_dir: str = OUTPUT_DIR) -> list[dict]:
    """Return list of generated documents with metadata."""
    if not os.path.exists(output_dir):
        return []
    result = []
    for fname in sorted(os.listdir(output_dir)):
        if fname.endswith(".docx"):
            doc_id = fname[:-5]
            json_path = os.path.join(output_dir, f"{doc_id}.json")
            entry = {"doc_id": doc_id, "docx_path": os.path.join(output_dir, fname)}
            if os.path.exists(json_path):
                try:
                    with open(json_path, encoding="utf-8") as jf:
                        meta = json.load(jf).get("meta", {})
                        entry["title_ar"] = meta.get("title_ar", "")
                        entry["title_en"] = meta.get("title_en", "")
                        entry["doc_type"] = meta.get("doc_type", "")
                        entry["version"]  = meta.get("version", "")
                except Exception:
                    pass
            result.append(entry)
    return result
