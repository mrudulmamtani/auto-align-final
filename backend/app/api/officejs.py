"""
Office.js Integration API — serves document data to the Word task pane add-in.

Routes:
  GET /api/officejs/documents          — list all generated documents
  GET /api/officejs/document/{job_id}  — document metadata + download URL
  GET /api/officejs/health             — add-in connectivity check
  GET /api/officejs/diagram/{job_id}/{index} — serve diagram PNG as base64
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.policy_factory.config import OUTPUT_DIR

router = APIRouter()


# ── Health check ──────────────────────────────────────────────────────────────

@router.get("/officejs/health")
async def officejs_health():
    """Ping endpoint the task pane uses to verify backend connectivity."""
    return {"status": "ok", "service": "AutoAlign Office.js API", "output_dir": OUTPUT_DIR}


# ── Document listing ──────────────────────────────────────────────────────────

@router.get("/officejs/documents")
async def list_documents():
    """
    Return a list of all generated documents in OUTPUT_DIR.
    Used by the task pane to correlate the open document with backend data.
    """
    out = Path(OUTPUT_DIR)
    if not out.exists():
        return {"documents": []}

    docs = []
    for f in sorted(out.glob("*.docx")):
        if "_traceability" in f.stem:
            continue
        stat = f.stat()
        docs.append({
            "doc_id":    f.stem,
            "filename":  f.name,
            "size_kb":   round(stat.st_size / 1024, 1),
            "modified":  stat.st_mtime,
            "type":      _infer_type(f.stem),
        })

    return {"documents": docs, "count": len(docs)}


def _infer_type(stem: str) -> str:
    s = stem.upper()
    if s.startswith("POL"): return "policy"
    if s.startswith("STD"): return "standard"
    if s.startswith("PRC"): return "procedure"
    return "document"


# ── Document detail ───────────────────────────────────────────────────────────

@router.get("/officejs/document/{doc_id}")
async def get_document_info(doc_id: str):
    """
    Return metadata and download URL for a specific generated document.
    The task pane calls this when it detects a doc_id in the open Word document.
    """
    out    = Path(OUTPUT_DIR)
    safe   = doc_id.replace("/", "-").replace("\\", "-")
    docx   = out / f"{safe}.docx"
    annex  = out / f"{safe}_traceability.docx"
    pngdir = out / safe    # swimlane PNGs stored in per-doc subdir (if any)

    if not docx.exists():
        raise HTTPException(404, f"Document {doc_id} not found in output directory.")

    stat = docx.stat()

    # Collect diagram files (PNG swimlanes)
    diagram_files = []
    if pngdir.is_dir():
        for png in sorted(pngdir.glob("*.png")):
            diagram_files.append({
                "index":    len(diagram_files),
                "filename": png.name,
                "url":      f"/api/officejs/diagram/{safe}/{len(diagram_files)}",
            })
    # Also check flat PNGs in OUTPUT_DIR named {doc_id}_*.png
    for png in sorted(out.glob(f"{safe}_*.png")):
        diagram_files.append({
            "index":    len(diagram_files),
            "filename": png.name,
            "url":      f"/api/officejs/diagram-flat/{safe}/{png.name}",
        })

    return {
        "doc_id":    doc_id,
        "type":      _infer_type(safe),
        "docx_path": str(docx),
        "size_kb":   round(stat.st_size / 1024, 1),
        "modified":  stat.st_mtime,
        "has_annex": annex.exists(),
        "diagrams":  diagram_files,
    }


# ── Diagram serving ───────────────────────────────────────────────────────────

@router.get("/officejs/diagram/{doc_id}/{index}")
async def get_diagram(doc_id: str, index: int):
    """
    Return a diagram PNG as a base64 data URL, for the task pane to
    re-insert or compare against the current document's images.
    """
    safe   = doc_id.replace("/", "-").replace("\\", "-")
    pngdir = Path(OUTPUT_DIR) / safe

    pngs = sorted(pngdir.glob("*.png")) if pngdir.is_dir() else []
    if index >= len(pngs):
        raise HTTPException(404, f"Diagram index {index} not found for {doc_id}.")

    data = pngs[index].read_bytes()
    b64  = base64.b64encode(data).decode()
    return JSONResponse({
        "doc_id":   doc_id,
        "index":    index,
        "filename": pngs[index].name,
        "data_url": f"data:image/png;base64,{b64}",
    })


@router.get("/officejs/diagram-flat/{doc_id}/{filename}")
async def get_diagram_flat(doc_id: str, filename: str):
    """Serve a flat PNG file stored directly in OUTPUT_DIR."""
    safe = doc_id.replace("/", "-").replace("\\", "-")
    # Prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename.")

    png = Path(OUTPUT_DIR) / filename
    if not png.exists() or not filename.startswith(safe):
        raise HTTPException(404, f"Diagram {filename} not found.")

    data = png.read_bytes()
    b64  = base64.b64encode(data).decode()
    return JSONResponse({
        "doc_id":   doc_id,
        "filename": filename,
        "data_url": f"data:image/png;base64,{b64}",
    })
