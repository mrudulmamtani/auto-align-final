"""
Document Library API.

Routes:
  GET  /api/doc-library                      — all 110 documents with status, grouped by wave
  GET  /api/doc-library/jobs                 — all active/recent generation jobs
  GET  /api/doc-library/jobs/{job_id}        — single job status
  GET  /api/doc-library/{doc_id}             — single doc + deps + dependents + status
  POST /api/doc-library/{doc_id}/generate    — trigger generation (async background thread)
  GET  /api/doc-library/{doc_id}/pdf         — serve generated PDF (converts on-the-fly if needed)
  GET  /api/doc-library/{doc_id}/download    — download main DOCX
  POST /api/doc-library/chain                — generate multiple docs with dep resolution
"""
from __future__ import annotations

import os
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.policy_factory.doc_graph import (
    get_all_documents,
    get_all_waves,
    get_document,
    get_dependencies,
    get_all_dependencies,
    get_dependents,
    get_all_dependents,
    get_generation_order,
)
from app.policy_factory.doc_registry import (
    get_status,
    get_all_statuses,
    register_generated,
    register_failed,
    update_pdf_path,
)
from app.policy_factory.pdf_converter import convert_docx_to_pdf
from app.policy_factory.config import OUTPUT_DIR

router = APIRouter()

# ── In-memory job store ───────────────────────────────────────────────────────
_lib_jobs: dict[str, dict] = {}


# ── Request models ────────────────────────────────────────────────────────────

class ProfileIn(BaseModel):
    org_name: str = "Organisation"
    sector: str = "Government"
    hosting_model: str = "hybrid"
    soc_model: str = "internal"
    data_classification: list[str] = ["confidential", "restricted", "public"]
    ot_presence: bool = False
    critical_systems: list[str] = []
    jurisdiction: str = "UAE"


class GenerateDocRequest(BaseModel):
    profile: ProfileIn = ProfileIn()
    force: bool = False   # regenerate even if DOCX already exists


class ChainGenerateRequest(BaseModel):
    doc_ids: list[str]
    profile: ProfileIn = ProfileIn()
    include_dependencies: bool = True   # prepend missing transitive deps


# ── Background generation worker ──────────────────────────────────────────────

def _run_doc_generation(job_id: str, doc_id: str, profile: ProfileIn, force: bool) -> None:
    """Generate a single document in a background thread."""
    try:
        _lib_jobs[job_id]["status"] = "running"
        _lib_jobs[job_id]["started_at"] = datetime.now(timezone.utc).isoformat()

        # Skip if already on disk and not forced
        if not force:
            st = get_status(doc_id)
            if st["status"] == "generated":
                docx = st.get("docx_path") or os.path.join(OUTPUT_DIR, f"{doc_id}.docx")
                if os.path.exists(docx):
                    # Try to convert to PDF if missing
                    if not st.get("pdf_path") or not os.path.exists(st["pdf_path"] or ""):
                        pdf = convert_docx_to_pdf(docx, OUTPUT_DIR)
                        if pdf:
                            update_pdf_path(doc_id, pdf)
                    _lib_jobs[job_id]["status"] = "skipped"
                    _lib_jobs[job_id]["message"] = f"{doc_id} already generated — skipped"
                    _lib_jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
                    return

        doc = get_document(doc_id)
        if not doc:
            raise ValueError(f"Unknown doc_id: {doc_id}")

        from app.policy_factory.pipeline import PolicyFactory
        from app.policy_factory.models import EntityProfile, DocumentSpec

        entity = EntityProfile(
            org_name=profile.org_name,
            sector=profile.sector,
            hosting_model=profile.hosting_model,
            soc_model=profile.soc_model,
            data_classification=profile.data_classification,
            ot_presence=profile.ot_presence,
            critical_systems=profile.critical_systems,
            jurisdiction=profile.jurisdiction,
        )

        spec = DocumentSpec(
            doc_type=doc["type"],
            doc_id=doc_id,
            topic=doc["name_en"],
            scope="All information assets and cybersecurity functions within the organisation",
            target_audience="All staff, IT departments, and cybersecurity teams",
            version="1.0",
        )

        t0 = time.time()
        factory = PolicyFactory()
        result = factory.run(profile=entity, spec=spec, output_dir=OUTPUT_DIR)
        elapsed = time.time() - t0

        docx_path = result.get("main_docx") or os.path.join(OUTPUT_DIR, f"{doc_id}.docx")
        pdf_path = convert_docx_to_pdf(docx_path, OUTPUT_DIR) if docx_path else None

        register_generated(
            doc_id,
            docx_path=docx_path,
            pdf_path=pdf_path,
            qa_passed=result.get("qa_passed"),
            elapsed=elapsed,
        )

        _lib_jobs[job_id]["status"] = "completed"
        _lib_jobs[job_id]["result"] = {k: v for k, v in result.items() if isinstance(v, (str, int, float, bool, type(None)))}
        _lib_jobs[job_id]["pdf_path"] = pdf_path
        _lib_jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()

    except Exception as exc:
        register_failed(doc_id, str(exc))
        _lib_jobs[job_id]["status"] = "failed"
        _lib_jobs[job_id]["error"] = str(exc)
        _lib_jobs[job_id]["traceback"] = traceback.format_exc()
        _lib_jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/doc-library")
async def list_documents():
    """All 110 documents with generation status, grouped by wave."""
    statuses = get_all_statuses()
    waves = get_all_waves()

    result_waves = []
    for wave_key, doc_ids in waves:
        wave_docs = []
        for doc_id in doc_ids:
            doc = get_document(doc_id)
            if doc:
                st = statuses.get(doc_id, {"status": "not_generated"})
                wave_docs.append({**doc, "gen_status": st})
        result_waves.append({
            "wave_key": wave_key,
            "wave_label": _wave_label(wave_key),
            "documents": wave_docs,
        })

    total = sum(len(w["documents"]) for w in result_waves)
    generated = sum(
        1 for w in result_waves
        for d in w["documents"]
        if d.get("gen_status", {}).get("status") == "generated"
    )
    return {"waves": result_waves, "total": total, "generated": generated}


@router.get("/doc-library/jobs")
async def list_lib_jobs():
    jobs = sorted(_lib_jobs.values(), key=lambda j: j.get("queued_at", ""), reverse=True)
    return {"jobs": jobs, "total": len(jobs)}


@router.get("/doc-library/jobs/{job_id}")
async def get_lib_job(job_id: str):
    job = _lib_jobs.get(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    return job


@router.get("/doc-library/{doc_id}")
async def get_doc_detail(doc_id: str):
    """Single document details including all dependency/dependent info and generation status."""
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(404, f"Document {doc_id} not found in catalog")

    st = get_status(doc_id)
    direct_deps = get_dependencies(doc_id)
    all_deps    = get_all_dependencies(doc_id)
    direct_down = get_dependents(doc_id)
    all_down    = get_all_dependents(doc_id)

    def with_status(docs: list) -> list:
        return [{**d, "gen_status": get_status(d["id"])} for d in docs]

    missing_deps = [
        d["id"] for d in all_deps
        if get_status(d["id"])["status"] != "generated"
    ]

    return {
        **doc,
        "gen_status": st,
        "direct_dependencies": with_status(direct_deps),
        "all_dependencies": with_status(all_deps),
        "direct_dependents": with_status(direct_down),
        "all_dependents": with_status(all_down),
        "missing_deps": missing_deps,
        "can_generate": len(missing_deps) == 0,
    }


@router.post("/doc-library/{doc_id}/generate")
async def generate_doc(doc_id: str, req: GenerateDocRequest = GenerateDocRequest()):
    """Trigger generation of a single document (runs in background thread)."""
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(404, f"Unknown doc_id: {doc_id}")

    job_id = str(uuid.uuid4())[:8]
    _lib_jobs[job_id] = {
        "job_id": job_id,
        "doc_id": doc_id,
        "doc_name": doc["name_en"],
        "doc_type": doc["type"],
        "status": "queued",
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }

    thread = threading.Thread(
        target=_run_doc_generation,
        args=(job_id, doc_id, req.profile, req.force),
        daemon=True,
    )
    thread.start()

    return {
        "job_id": job_id,
        "doc_id": doc_id,
        "doc_name": doc["name_en"],
        "status": "queued",
        "message": f"Generation queued for {doc_id}: {doc['name_en']}",
    }


@router.post("/doc-library/chain")
async def generate_chain(req: ChainGenerateRequest):
    """
    Generate a chain of documents in topological order.
    If include_dependencies=True, missing transitive dependencies are prepended.
    The chain runs sequentially (each doc waits for previous to complete).
    """
    if req.include_dependencies:
        ordered = get_generation_order(req.doc_ids)
    else:
        ordered = list(req.doc_ids)

    jobs = []
    for doc_id in ordered:
        doc = get_document(doc_id)
        if not doc:
            continue
        job_id = str(uuid.uuid4())[:8]
        _lib_jobs[job_id] = {
            "job_id": job_id,
            "doc_id": doc_id,
            "doc_name": doc["name_en"],
            "doc_type": doc["type"],
            "status": "queued",
            "queued_at": datetime.now(timezone.utc).isoformat(),
        }
        jobs.append({"job_id": job_id, "doc_id": doc_id, "doc_name": doc["name_en"]})

    # Run all docs sequentially in a single background thread
    profile = req.profile

    def run_chain() -> None:
        for job in jobs:
            _run_doc_generation(job["job_id"], job["doc_id"], profile, False)

    thread = threading.Thread(target=run_chain, daemon=True)
    thread.start()

    return {"jobs": jobs, "total": len(jobs), "message": f"Chain of {len(jobs)} documents queued"}


@router.get("/doc-library/{doc_id}/pdf")
async def serve_pdf(doc_id: str):
    """Serve the generated PDF.  Converts on-the-fly if PDF does not exist yet."""
    st = get_status(doc_id)

    pdf_path = st.get("pdf_path")
    if not pdf_path or not os.path.exists(pdf_path):
        # Try on-the-fly conversion
        docx_path = st.get("docx_path") or os.path.join(OUTPUT_DIR, f"{doc_id}.docx")
        if os.path.exists(docx_path):
            pdf_path = convert_docx_to_pdf(docx_path, OUTPUT_DIR)
            if pdf_path:
                update_pdf_path(doc_id, pdf_path)

    if not pdf_path or not os.path.exists(pdf_path):
        raise HTTPException(
            404,
            detail=f"PDF not available for {doc_id}. "
                   "Generate the document first, then ensure Word or LibreOffice is installed for conversion.",
        )

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{doc_id}.pdf"'},
    )


@router.get("/doc-library/{doc_id}/download")
async def download_docx(doc_id: str):
    """Download the main DOCX for a document."""
    st = get_status(doc_id)
    docx_path = st.get("docx_path") or os.path.join(OUTPUT_DIR, f"{doc_id}.docx")
    if not os.path.exists(docx_path):
        raise HTTPException(404, f"DOCX not found for {doc_id}. Has it been generated?")

    return FileResponse(
        docx_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{doc_id}.docx"'},
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _wave_label(wave_key: str) -> str:
    labels = {
        "wave_1_policies_foundation": "Wave 1 — Foundation Policies",
        "wave_2_core_standards": "Wave 2 — Core Standards",
        "wave_3_high_impact_procedures": "Wave 3 — High-Impact Procedures",
        "wave_4_remaining_policies": "Wave 4 — Remaining Policies",
        "wave_5_remaining_standards": "Wave 5 — Remaining Standards",
        "wave_6_remaining_procedures": "Wave 6 — Remaining Procedures",
    }
    return labels.get(wave_key, wave_key.replace("_", " ").title())
