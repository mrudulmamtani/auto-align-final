"""
Policy & Standard Generator — integrated into Controls Intelligence Hub.

Routes:
  POST /api/generate          — generate a policy or standard document
  GET  /api/generate/status/{job_id} — poll generation job status
  GET  /api/generate/topics   — list available policy/standard topics
"""
import asyncio
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# ── In-memory job store ───────────────────────────────────────────────────────

_jobs: dict[str, dict] = {}

# ── Singleton PolicyFactory — initialized once at startup ─────────────────────
# Loading ControlStore embeddings takes 3–8 minutes; never recreate per-job.

_factory = None
_factory_lock = threading.Lock()


def _get_factory():
    """Return the singleton PolicyFactory, initializing it on first call."""
    global _factory
    if _factory is None:
        with _factory_lock:
            if _factory is None:
                from app.policy_factory.pipeline import PolicyFactory
                print("[Generate] Initialising PolicyFactory singleton...")
                _factory = PolicyFactory()
                print("[Generate] PolicyFactory ready.")
    return _factory


def prewarm_factory():
    """Call at app startup to load embeddings before the first request arrives."""
    _get_factory()

# ── Request / Response models ─────────────────────────────────────────────────

class EntityProfileIn(BaseModel):
    org_name: str
    sector: str = "Financial Services"
    hosting_model: str = "hybrid"
    soc_model: str = "internal"
    data_classification: list[str] = ["confidential", "restricted", "public"]
    ot_presence: bool = False
    critical_systems: list[str] = []
    jurisdiction: str = "UAE"


class GenerateRequest(BaseModel):
    doc_type: Literal["policy", "standard", "procedure"]
    topic: str
    doc_id: Optional[str] = None          # e.g. "POL-01", "STD-02" — enables Golden Baseline
    scope: str = "All information assets and cybersecurity functions"
    target_audience: str = "All staff, IT, cybersecurity teams"
    version: str = "1.0"
    profile: EntityProfileIn = EntityProfileIn(org_name="Organisation")
    customization: Optional[str] = None   # consultant free-text injected into all agent prompts


class GenerateResponse(BaseModel):
    job_id: str
    status: str
    message: str


# ── Topic catalogue — loaded from docGenConstruct.json ───────────────────────

def _load_topics_from_construct() -> dict:
    """Read topic lists directly from docGenConstruct.json so they stay in sync."""
    construct_path = Path(__file__).resolve().parent.parent.parent / "docGenConstruct.json"
    policies, standards, procedures = [], [], []
    try:
        data = json.loads(construct_path.read_text(encoding="utf-8"))
        for doc in data.get("documents", []):
            entry = {"doc_id": doc["id"], "topic": doc.get("name_en", doc["id"])}
            t = doc.get("type", "")
            if t == "policy":      policies.append(entry)
            elif t == "standard":  standards.append(entry)
            elif t == "procedure": procedures.append(entry)
    except Exception:
        pass
    return {"policies": policies, "standards": standards, "procedures": procedures}


@router.get("/generate/topics")
async def get_topics():
    return _load_topics_from_construct()


# ── Background generation worker ─────────────────────────────────────────────

def _run_generation(job_id: str, req: GenerateRequest):
    """Runs the PolicyFactory pipeline synchronously in a background thread."""
    try:
        _jobs[job_id]["status"] = "running"
        _jobs[job_id]["started_at"] = datetime.now(timezone.utc).isoformat()

        from app.policy_factory.models import EntityProfile, DocumentSpec
        from app.policy_factory.config import OUTPUT_DIR

        profile = EntityProfile(
            org_name=req.profile.org_name,
            sector=req.profile.sector,
            hosting_model=req.profile.hosting_model,
            soc_model=req.profile.soc_model,
            data_classification=req.profile.data_classification,
            ot_presence=req.profile.ot_presence,
            critical_systems=req.profile.critical_systems,
            jurisdiction=req.profile.jurisdiction,
        )

        # Append consultant customization to the topic so every agent sees it
        effective_topic = req.topic
        if req.customization and req.customization.strip():
            effective_topic = (
                f"{req.topic}\n\n"
                f"--- Consultant Customization (apply throughout entire document) ---\n"
                f"{req.customization.strip()}"
            )

        spec = DocumentSpec(
            doc_type=req.doc_type,
            topic=effective_topic,
            scope=req.scope,
            target_audience=req.target_audience,
            version=req.version,
        )

        # Inject doc_id onto spec so pipeline uses Golden Baseline route
        # (pipeline uses getattr(spec, "doc_id", None) — set via object __dict__)
        if req.doc_id:
            object.__setattr__(spec, "doc_id", req.doc_id)

        factory = _get_factory()
        result = factory.run(profile=profile, spec=spec, output_dir=OUTPUT_DIR)

        _jobs[job_id]["status"] = "completed"
        _jobs[job_id]["result"] = result
        _jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()

        # Register in doc library registry + convert to PDF
        if req.doc_id:
            try:
                from app.policy_factory.doc_registry import register_generated
                from app.policy_factory.pdf_converter import convert_docx_to_pdf
                docx_path = result.get("main_docx")
                pdf_path = convert_docx_to_pdf(docx_path, OUTPUT_DIR) if docx_path else None
                register_generated(
                    req.doc_id,
                    docx_path=docx_path,
                    pdf_path=pdf_path,
                    qa_passed=result.get("qa_passed"),
                )
            except Exception:
                pass

    except Exception as exc:
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(exc)
        _jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        import traceback
        _jobs[job_id]["traceback"] = traceback.format_exc()


@router.post("/generate", response_model=GenerateResponse)
async def generate_document(req: GenerateRequest):
    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {
        "job_id":      job_id,
        "status":      "queued",
        "doc_type":    req.doc_type,
        "topic":       req.topic,
        "doc_id":      req.doc_id,
        "org_name":    req.profile.org_name,
        "queued_at":   datetime.now(timezone.utc).isoformat(),
        "result":      None,
        "error":       None,
    }

    # Run in a background thread (CPU-bound generation)
    thread = threading.Thread(target=_run_generation, args=(job_id, req), daemon=True)
    thread.start()

    return GenerateResponse(
        job_id=job_id,
        status="queued",
        message=f"Generation started for {req.doc_type}: {req.topic}",
    )


@router.get("/generate/status/{job_id}")
async def get_job_status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    return job


@router.get("/generate/jobs")
async def list_jobs():
    """List all generation jobs (most recent first)."""
    jobs = sorted(_jobs.values(), key=lambda j: j.get("queued_at", ""), reverse=True)
    return {"jobs": jobs, "total": len(jobs)}
