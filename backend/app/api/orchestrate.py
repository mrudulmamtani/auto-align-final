"""
Orchestration API — endpoints for the ministry document wave-based generator.

Routes:
  POST /api/orchestrate/start            — start full or partial orchestration
  POST /api/orchestrate/stop             — stop running orchestration
  GET  /api/orchestrate/status           — poll orchestration status
  GET  /api/orchestrate/catalog          — get full document catalog
  GET  /api/orchestrate/generated        — list generated documents
  POST /api/orchestrate/generate/{doc_id} — generate a single document
  GET  /api/orchestrate/download/{doc_id} — download a generated DOCX
"""
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.policy_factory.orchestrator import (
    start_orchestration, stop_orchestration,
    get_state, generate_single_document,
    get_catalog, get_generated_docs,
)
from app.policy_factory.config import OUTPUT_DIR

router = APIRouter()


# ── Request models ─────────────────────────────────────────────────────────────

class StartOrchestrateRequest(BaseModel):
    doc_ids: Optional[list[str]] = None   # None = generate all 110 docs
    org_name: str = "الوزارة"
    skip_existing: bool = True
    output_dir: str = OUTPUT_DIR


class SingleGenerateRequest(BaseModel):
    org_name: str = "الوزارة"
    dependency_context: str = ""
    output_dir: str = OUTPUT_DIR


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/orchestrate/start")
async def start_orchestration_route(req: StartOrchestrateRequest):
    started = start_orchestration(
        doc_ids=req.doc_ids,
        output_dir=req.output_dir,
        org_name=req.org_name,
        skip_existing=req.skip_existing,
    )
    if not started:
        raise HTTPException(409, "Orchestration is already running")
    return {"message": "Orchestration started", "status": "running"}


@router.post("/orchestrate/stop")
async def stop_orchestration_route():
    stopped = stop_orchestration()
    if not stopped:
        raise HTTPException(409, "No orchestration is currently running")
    return {"message": "Stop signal sent"}


@router.get("/orchestrate/status")
async def get_orchestration_status():
    return get_state().to_dict()


@router.get("/orchestrate/catalog")
async def get_orchestration_catalog():
    return get_catalog()


@router.get("/orchestrate/generated")
async def list_generated_documents(output_dir: str = OUTPUT_DIR):
    return {"documents": get_generated_docs(output_dir)}


@router.post("/orchestrate/generate/{doc_id}")
async def generate_single_doc(doc_id: str, req: SingleGenerateRequest):
    result = generate_single_document(
        doc_id=doc_id,
        output_dir=req.output_dir,
        org_name=req.org_name,
        dependency_context=req.dependency_context,
    )
    if not result.get("success"):
        raise HTTPException(500, result.get("error", "Generation failed"))
    return result


@router.get("/orchestrate/download/{doc_id}")
async def download_generated_doc(doc_id: str, output_dir: str = OUTPUT_DIR):
    path = os.path.join(output_dir, f"{doc_id}.docx")
    if not os.path.exists(path):
        raise HTTPException(404, f"Document {doc_id} not found")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"{doc_id}.docx",
    )


@router.get("/orchestrate/health")
async def orchestrate_health():
    return {"status": "ok", "output_dir": OUTPUT_DIR}
