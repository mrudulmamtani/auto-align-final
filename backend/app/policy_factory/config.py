import os
from pathlib import Path

# Base directory resolves to backend/ root (parent.parent.parent of this file)
# File is at: backend/app/policy_factory/config.py
# So: parent = policy_factory/, parent.parent = app/, parent.parent.parent = backend/
_THIS_FILE = Path(__file__).resolve()
BASE_DIR = str(_THIS_FILE.parent.parent.parent)   # backend/  (or /app/ in Docker)

# NOTE: Secrets must not be checked into version control.
#       Provide values via environment variables or a secrets manager.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
HF_TOKEN = os.environ.get("HF_TOKEN")

NIST_JSON        = os.path.join(BASE_DIR, "NIST3.json")    # NIST with uae_ia_id + nca_id
UAE_JSON         = os.path.join(BASE_DIR, "uae.json")
NCA_JSON         = os.path.join(BASE_DIR, "nca_oscal_catalog.json")
NIST_VECS_CACHE  = os.path.join(BASE_DIR, "oai_nist_vecs.pkl")
UAE_VECS_CACHE   = os.path.join(BASE_DIR, "oai_uae_vecs.pkl")
NCA_VECS_CACHE   = os.path.join(BASE_DIR, "oai_nca_vecs.pkl")
OUTPUT_DIR       = os.path.join(BASE_DIR, "policy_output")

EMBED_MODEL           = "text-embedding-3-large"
PLAN_MODEL            = "o3"              # planner — best reasoning model (no temperature)
DRAFT_MODEL           = "gpt-5.4"         # drafter + editor (generic doc types)
DRAFT_MODEL_POLICY    = "gpt-5.4"         # policy / standard / procedure compiler
ENRICH_MODEL          = "gpt-5.4"         # enricher + gap analyst + diagram agent

RETRIEVAL_TOP_K_PER_QUERY = 35   # dense retrieval per query before reranking
RERANK_TOP_K              = 20   # chunks kept per section after cross-encoder reranking
MAX_DRAFT_RETRIES         = 1    # outer pipeline retries (supervisor handles internal repair)

# Cross-encoder model (sentence-transformers, downloaded on first use, ~80 MB)
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
