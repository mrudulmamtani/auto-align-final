"""
Document generation registry.

Tracks which documents (POL-*, STD-*, PRC-*) have been generated,
when they were generated, and whether they are stale (a dependency was
regenerated after this document was last built).

Storage: JSON file at backend/doc_registry.json (thread-safe via a lock).
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.policy_factory.config import OUTPUT_DIR, BASE_DIR

_REGISTRY_FILE = os.path.join(BASE_DIR, "doc_registry.json")
_lock = threading.Lock()


# ── Persistence ───────────────────────────────────────────────────────────────

def _load() -> dict:
    if os.path.exists(_REGISTRY_FILE):
        try:
            with open(_REGISTRY_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save(reg: dict) -> None:
    with open(_REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=2)


# ── Public API ────────────────────────────────────────────────────────────────

def register_generated(
    doc_id: str,
    *,
    docx_path: str | None = None,
    pdf_path: str | None = None,
    qa_passed: bool | None = None,
    elapsed: float | None = None,
) -> None:
    """Record a successful generation.  Marks direct dependents as stale."""
    with _lock:
        reg = _load()
        reg[doc_id] = {
            "doc_id": doc_id,
            "status": "generated",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "docx_path": docx_path,
            "pdf_path": pdf_path,
            "qa_passed": qa_passed,
            "elapsed": elapsed,
            "stale": False,
        }
        _save(reg)

    _mark_dependents_stale(doc_id)


def register_failed(doc_id: str, error: str) -> None:
    with _lock:
        reg = _load()
        reg[doc_id] = {
            "doc_id": doc_id,
            "status": "failed",
            "generated_at": None,
            "docx_path": None,
            "pdf_path": None,
            "qa_passed": None,
            "elapsed": None,
            "stale": False,
            "error": error,
        }
        _save(reg)


def get_status(doc_id: str) -> dict:
    """Return status record for a document.  Falls back to disk-existence check."""
    with _lock:
        reg = _load()

    if doc_id in reg:
        return reg[doc_id]

    # Fall back: check if DOCX exists on disk
    docx_path = os.path.join(OUTPUT_DIR, f"{doc_id}.docx")
    pdf_path  = os.path.join(OUTPUT_DIR, f"{doc_id}.pdf")
    if os.path.exists(docx_path):
        return {
            "doc_id": doc_id,
            "status": "generated",
            "generated_at": None,
            "docx_path": docx_path,
            "pdf_path": pdf_path if os.path.exists(pdf_path) else None,
            "qa_passed": None,
            "elapsed": None,
            "stale": False,
        }

    return {
        "doc_id": doc_id,
        "status": "not_generated",
        "generated_at": None,
        "docx_path": None,
        "pdf_path": None,
        "qa_passed": None,
        "elapsed": None,
        "stale": False,
    }


def get_all_statuses() -> dict[str, dict]:
    from app.policy_factory.doc_graph import get_all_documents
    return {doc["id"]: get_status(doc["id"]) for doc in get_all_documents()}


def update_pdf_path(doc_id: str, pdf_path: str) -> None:
    with _lock:
        reg = _load()
        if doc_id in reg:
            reg[doc_id]["pdf_path"] = pdf_path
            _save(reg)


def _mark_dependents_stale(doc_id: str) -> None:
    """Mark all direct dependents as stale after a regeneration."""
    from app.policy_factory.doc_graph import get_dependents
    with _lock:
        reg = _load()
        for dep in get_dependents(doc_id):
            if dep["id"] in reg and reg[dep["id"]]["status"] == "generated":
                reg[dep["id"]]["stale"] = True
        _save(reg)
