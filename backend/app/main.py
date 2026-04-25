"""Controls Intelligence Hub — PwC Backend API."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

# Load .env from backend root before anything else
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv as _load_dotenv
        _load_dotenv(_env_file, override=True)
    except ImportError:
        for _line in _env_file.read_text().splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ[_k.strip()] = _v.strip()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import uccf, arr
from app.api import converter, generate, orchestrate, documents, officejs
from app.services.database import close_redis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Controls Intelligence Hub backend starting up")
    # Pre-warm PolicyFactory singleton in background — loads embedding pickle
    # files once so the first generate request doesn't pay the startup cost.
    import threading
    threading.Thread(
        target=generate.prewarm_factory, daemon=True, name="factory-prewarm"
    ).start()
    yield
    await close_redis()
    logger.info("Controls Intelligence Hub backend shut down")


app = FastAPI(
    title="Controls Intelligence Hub",
    description="PwC Controls Intelligence Hub — UCCF Semantic Mapping Engine + AutoAlign Policy Factory",
    version="2.0.0",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3100",
        "http://localhost:3000",
        "http://127.0.0.1:3100",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(uccf.router,       prefix="/api/uccf",  tags=["UCCF"])
app.include_router(arr.router,        prefix="/api/arr",   tags=["ARR"])
app.include_router(converter.router,  prefix="/api",       tags=["AutoAlign Converter"])
app.include_router(generate.router,   prefix="/api",       tags=["AutoAlign Generate"])
app.include_router(orchestrate.router, prefix="/api",      tags=["Ministry Orchestrator"])
app.include_router(documents.router,  prefix="/api",       tags=["Document Library"])
app.include_router(officejs.router,   prefix="/api",       tags=["Office.js Add-in"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "Controls Intelligence Hub v2.0"}
