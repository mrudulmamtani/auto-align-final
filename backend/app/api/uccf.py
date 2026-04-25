"""UCCF — Unified Common Controls Framework API.

Provides endpoints to:
- List standards in the KG
- Get common controls mapped across standards (SEMANTIC_MATCH)
- Get cross-standard overlap matrix
- Ingest a new standard from JSON (auto-detect format)
- Re-run semantic matching across all standards

Storage: Redis (no Neo4j dependency).
Semantic matching: transformer sentence embeddings (all-MiniLM-L6-v2) via
  sentence-transformers + spaCy NER for entity/keyword extraction.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from functools import lru_cache, partial
from typing import Any

import numpy as np
from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.services.database import get_redis

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Cosine similarity threshold for transformer embeddings ──────────────────
SIMILARITY_THRESHOLD = 0.50   # cosine similarity (0-1)
MIN_SHARED_KEYWORDS  = 1      # at least 1 shared NER entity or domain keyword

# Redis key prefix for UCCF data
UCCF_STANDARDS_KEY   = "pwc:uccf:standards"
UCCF_CONTROLS_KEY    = "pwc:uccf:controls"
UCCF_LINKS_KEY       = "pwc:uccf:semantic_links"

# ── Domain keyword clusters (used for metadata assignment & display) ─────────
DOMAIN_CLUSTERS: dict[str, set[str]] = {
    "access_control":      {"access", "control", "identity", "authentication", "authorization",
                            "privilege", "iam", "mfa", "password", "credential", "account",
                            "user", "session", "login", "permission", "role", "segregation"},
    "risk_management":     {"risk", "assessment", "treatment", "residual", "evaluation",
                            "appetite", "tolerance", "register", "likelihood", "impact", "threat"},
    "incident_management": {"incident", "response", "detection", "monitoring", "siem",
                            "alert", "breach", "forensic", "investigation", "escalation"},
    "governance":          {"governance", "policy", "procedure", "framework", "strategy",
                            "leadership", "board", "management", "oversight", "accountability",
                            "roles", "responsibilities", "commitment"},
    "data_protection":     {"data", "classification", "encryption", "privacy", "protection",
                            "retention", "disposal", "information", "masking", "tokenization"},
    "network_security":    {"network", "firewall", "segmentation", "perimeter", "dmz",
                            "vpn", "proxy", "traffic", "packet", "communications"},
    "operations_security": {"operations", "change", "configuration", "patch", "vulnerability",
                            "hardening", "baseline", "asset", "inventory", "logging"},
    "third_party":         {"third", "party", "vendor", "supplier", "outsourcing",
                            "cloud", "saas", "contract", "due_diligence", "external"},
    "physical_security":   {"physical", "environmental", "facility", "premises",
                            "cctv", "badge", "entry", "secure"},
    "business_continuity": {"continuity", "disaster", "recovery", "backup",
                            "resilience", "bcp", "drp", "availability"},
    "audit_compliance":    {"audit", "compliance", "regulatory", "review",
                            "log", "trail", "evidence", "assurance", "testing"},
    "secure_development":  {"development", "sdlc", "application", "code",
                            "testing", "devsecops", "scanning", "secure"},
    "cryptography":        {"cryptography", "encryption", "algorithm", "cipher",
                            "key", "hash", "certificate", "pki", "tls"},
    "awareness_training":  {"training", "awareness", "education", "personnel",
                            "competence", "culture", "phishing", "human"},
}


# ── Transformer model singletons (lazy-loaded) ───────────────────────────────

@lru_cache(maxsize=1)
def _get_nlp():
    """Load spaCy en_core_web_sm model (cached singleton)."""
    import spacy  # noqa: PLC0415
    return spacy.load("en_core_web_sm")


@lru_cache(maxsize=1)
def _get_embedder():
    """Load sentence-transformers all-MiniLM-L6-v2 model (cached singleton)."""
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415
    return SentenceTransformer("all-MiniLM-L6-v2")


# ── NER-based keyword extraction ─────────────────────────────────────────────

def _extract_keywords(text: str) -> list[str]:
    """Extract entities and key terms using spaCy transformer NER pipeline.

    Returns a deterministic sorted list of relevant tokens: named entities
    (ORG, LAW, PRODUCT, WORK_OF_ART), noun chunk roots, and any domain
    cluster keywords matched in the text.
    """
    nlp = _get_nlp()
    doc = nlp(text[:512])   # cap for speed

    found: set[str] = set()

    # Named entities from transformer NER
    KEEP_LABELS = {"ORG", "LAW", "PRODUCT", "WORK_OF_ART", "MISC"}
    for ent in doc.ents:
        if ent.label_ in KEEP_LABELS:
            token = ent.text.lower().strip()
            if len(token) > 2:
                found.add(token)

    # Noun chunk roots (key concepts, single lemmatized tokens)
    for chunk in doc.noun_chunks:
        root_lemma = chunk.root.lemma_.lower()
        if len(root_lemma) > 3 and not chunk.root.is_stop:
            found.add(root_lemma)

    # Domain cluster vocabulary (exact word boundary match)
    text_lower = text.lower()
    for words in DOMAIN_CLUSTERS.values():
        for w in words:
            if re.search(r"\b" + re.escape(w) + r"\b", text_lower):
                found.add(w)

    return sorted(found)[:30]   # cap at 30 to keep Redis storage reasonable


def _assign_domain_cluster(keywords: list[str]) -> str:
    """Assign the best-matching domain cluster based on keyword overlap."""
    kw_set = set(keywords)
    best, best_score = "general", 0
    for domain, words in DOMAIN_CLUSTERS.items():
        score = len(kw_set & words)
        if score > best_score:
            best, best_score = domain, score
    return best


# ── Transformer similarity helpers ───────────────────────────────────────────

def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two embedding vectors."""
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom < 1e-9:
        return 0.0
    return float(np.dot(va, vb) / denom)


def _encode_texts_sync(texts: list[str]) -> list[list[float]]:
    """Encode a list of texts with the sentence-transformer model (synchronous)."""
    embedder = _get_embedder()
    embeddings = embedder.encode(
        texts,
        batch_size=64,
        convert_to_numpy=True,
        show_progress_bar=False,
        normalize_embeddings=True,   # enables dot-product == cosine sim
    )
    return embeddings.tolist()


async def _encode_texts(texts: list[str]) -> list[list[float]]:
    """Non-blocking wrapper: run encoding in a thread executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_encode_texts_sync, texts))


# ── Misc helpers ─────────────────────────────────────────────────────────────

def _sha_urn(kind: str, val: str) -> str:
    h = hashlib.sha256(val.encode()).hexdigest()[:12]
    return f"urn:pwc:{kind}:{h}"


# ── JSON Parsers (auto-detect format) ────────────────────────────────────────

def _parse_normalized(raw: dict) -> list[dict]:
    std_name    = raw.get("standard_name", "Unknown")
    std_short   = raw.get("short_name", std_name[:12])
    std_version = str(raw.get("version", "1.0"))
    std_urn     = raw.get("urn") or _sha_urn("std", std_name + std_version)
    out = []
    for domain in raw.get("domains", []):
        dom_id   = domain.get("id", "GEN")
        dom_name = domain.get("name", "General")
        objective = domain.get("objective", "")
        for ctrl in domain.get("controls", []):
            text = ctrl.get("text", ctrl.get("control_statement", ""))
            kw   = ctrl.get("keywords") or _extract_keywords(text)
            out.append({
                "standard_urn": std_urn, "standard_name": std_name,
                "standard_short": std_short, "standard_version": std_version,
                "domain_id": dom_id, "domain_name": dom_name, "domain_objective": objective,
                "control_id":   ctrl.get("id",   ctrl.get("control_id", "")),
                "control_name": ctrl.get("name", ctrl.get("control_name", "")),
                "control_text": text,
                "obligation":   ctrl.get("obligation", "shall"),
                "keywords":     list(kw),
                "domain_cluster": _assign_domain_cluster(list(kw)),
                "sub_controls": ctrl.get("subControls", ctrl.get("subcontrols", [])),
            })
    return out


def _parse_uae_ias_like(records: list[dict]) -> list[dict]:
    std_name = records[0].get("framework_name", "UAE IAS")
    std_urn  = _sha_urn("std", std_name)
    out = []
    for r in records:
        text = r.get("control_statement", "")
        kw   = _extract_keywords(text)
        out.append({
            "standard_urn": std_urn, "standard_name": std_name, "standard_short": std_name[:12],
            "standard_version": str(r.get("version", "1.0")),
            "domain_id":   r.get("control_family_id", "GEN"),
            "domain_name": r.get("control_family_name", "General"),
            "domain_objective": r.get("objective_family_level", ""),
            "control_id":   r.get("control_id", ""),
            "control_name": r.get("control_name", ""),
            "control_text": text,
            "obligation":  "shall",
            "keywords": kw, "domain_cluster": _assign_domain_cluster(kw),
            "sub_controls": r.get("sub_controls", []),
        })
    return out


def _parse_nca_like(records: list[dict]) -> list[dict]:
    std_name = records[0].get("framework_name", records[0].get("Main_Domain_Name", "NCA"))
    std_urn  = _sha_urn("std", std_name)
    out = []
    for r in records:
        did   = r.get("main_domain_id") or r.get("Main_Domain_ID", "GEN")
        dname = r.get("main_domain_name") or r.get("Main_Domain_Name", "General")
        text  = r.get("control_statement") or r.get("Main_Control_Description", "")
        kw    = _extract_keywords(text)
        out.append({
            "standard_urn": std_urn, "standard_name": std_name, "standard_short": std_name[:12],
            "standard_version": str(r.get("version", "1.0")),
            "domain_id": did, "domain_name": dname,
            "domain_objective": r.get("objective", ""),
            "control_id":   r.get("control_id", r.get("Main_Control_ID", "")),
            "control_name": r.get("subdomain_name", r.get("Subdomain_Name", "")),
            "control_text": text,
            "obligation": "shall",
            "keywords": kw, "domain_cluster": _assign_domain_cluster(kw),
            "sub_controls": r.get("subcontrols", []),
        })
    return out


def _parse_flat_list(records: list[dict]) -> list[dict]:
    first    = records[0]
    std_name = first.get("standard_name", first.get("framework_name", "Unknown"))
    std_urn  = _sha_urn("std", std_name)
    out = []
    for r in records:
        text = r.get("control_statement", r.get("text", r.get("requirement_text", "")))
        kw   = r.get("keywords") or _extract_keywords(text)
        out.append({
            "standard_urn": std_urn, "standard_name": std_name, "standard_short": std_name[:12],
            "standard_version": str(r.get("version", "1.0")),
            "domain_id":   r.get("domain_id", r.get("category", "GEN")),
            "domain_name": r.get("domain_name", r.get("category", "General")),
            "domain_objective": r.get("objective", ""),
            "control_id":   r.get("control_id", r.get("id", "")),
            "control_name": r.get("control_name", r.get("name", "")),
            "control_text": text,
            "obligation":   r.get("obligation", "shall"),
            "keywords":     list(kw), "domain_cluster": _assign_domain_cluster(list(kw)),
            "sub_controls": r.get("sub_controls", r.get("subcontrols", [])),
        })
    return out


def _auto_parse(raw: Any) -> list[dict]:
    if isinstance(raw, dict) and "domains" in raw:
        return _parse_normalized(raw)
    if isinstance(raw, dict):
        for key in ("controls", "requirements", "items", "data", "records"):
            if key in raw and isinstance(raw[key], list):
                return _auto_parse(raw[key])
    if isinstance(raw, list) and raw:
        first = raw[0]
        if "control_family_id" in first:
            return _parse_uae_ias_like(raw)
        if "main_domain_id" in first or "Main_Domain_ID" in first:
            return _parse_nca_like(raw)
        return _parse_flat_list(raw)
    return []


# ── Redis storage helpers ─────────────────────────────────────────────────────

async def _store_controls(controls: list[dict]) -> tuple[int, int]:
    """Store parsed controls in Redis. Returns (domains_created, controls_count)."""
    r = await get_redis()
    std = controls[0]
    std_urn = std["standard_urn"]

    raw_stds = await r.get(UCCF_STANDARDS_KEY)
    standards: dict[str, dict] = json.loads(raw_stds) if raw_stds else {}

    domains: dict[str, dict] = {}
    for ctrl in controls:
        did = ctrl["domain_id"]
        if did not in domains:
            domains[did] = {"id": did, "name": ctrl["domain_name"], "objective": ctrl["domain_objective"]}

    if std_urn not in standards:
        standards[std_urn] = {
            "urn": std_urn,
            "name": std["standard_name"],
            "short_name": std["standard_short"],
            "version": std["standard_version"],
            "domain_count": len(domains),
            "total_controls": len(controls),
            "domain_names": [d["name"] for d in list(domains.values())[:8]],
        }
    else:
        standards[std_urn]["domain_count"]   = len(domains)
        standards[std_urn]["total_controls"] = len(controls)

    await r.set(UCCF_STANDARDS_KEY, json.dumps(standards))

    raw_ctrls = await r.get(UCCF_CONTROLS_KEY)
    all_controls: list[dict] = json.loads(raw_ctrls) if raw_ctrls else []
    all_controls = [c for c in all_controls if c.get("standard_urn") != std_urn]

    for ctrl in controls:
        ctrl["urn"] = _sha_urn(
            "control",
            ctrl["standard_urn"] + ctrl["control_id"] + ctrl["control_text"][:50],
        )
        all_controls.append(ctrl)

    await r.set(UCCF_CONTROLS_KEY, json.dumps(all_controls))
    return len(domains), len(controls)


async def _semantic_match_new(controls: list[dict]) -> int:
    """Match newly ingested controls against all existing controls using
    transformer cosine similarity. Deterministic: same input → same output."""
    r = await get_redis()
    std_urn = controls[0]["standard_urn"]

    raw_ctrls = await r.get(UCCF_CONTROLS_KEY)
    if not raw_ctrls:
        return 0
    all_controls: list[dict] = json.loads(raw_ctrls)
    existing = [c for c in all_controls if c.get("standard_urn") != std_urn]
    if not existing:
        return 0

    raw_links = await r.get(UCCF_LINKS_KEY)
    links: list[dict] = json.loads(raw_links) if raw_links else []

    # Encode new controls
    new_texts = [c["control_text"] for c in controls]
    ex_texts  = [c["control_text"] for c in existing]

    new_embs = await _encode_texts(new_texts)
    ex_embs  = await _encode_texts(ex_texts)

    link_count = 0
    for nc, nc_emb in zip(controls, new_embs):
        nc_kw      = set(nc.get("keywords") or [])
        nc_cluster = nc.get("domain_cluster", "general")
        nc_urn     = nc.get("urn") or _sha_urn(
            "control", nc["standard_urn"] + nc["control_id"] + nc["control_text"][:50]
        )

        for ex, ex_emb in zip(existing, ex_embs):
            ex_cluster = ex.get("domain_cluster", "general")
            # Skip cross-cluster matches unless one is 'general'
            if nc_cluster != ex_cluster and nc_cluster != "general" and ex_cluster != "general":
                continue

            sim    = _cosine_sim(nc_emb, ex_emb)
            shared = sorted(nc_kw & set(ex.get("keywords") or []))

            if sim >= SIMILARITY_THRESHOLD and len(shared) >= MIN_SHARED_KEYWORDS:
                match_type = "domain_match" if nc_cluster == ex_cluster else "keyword_overlap"
                links.append({
                    "source_urn":      nc_urn,
                    "target_urn":      ex["urn"],
                    "source_standard": nc["standard_name"],
                    "target_standard": ex["standard_name"],
                    "similarity":      round(sim, 3),
                    "shared_keywords": shared,
                    "match_type":      match_type,
                })
                link_count += 1

    await r.set(UCCF_LINKS_KEY, json.dumps(links))
    return link_count


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/standards")
async def list_uccf_standards():
    r = await get_redis()
    raw = await r.get(UCCF_STANDARDS_KEY)
    standards_map: dict[str, dict] = json.loads(raw) if raw else {}
    return {"standards": list(standards_map.values()), "total": len(standards_map)}


@router.get("/common-controls")
async def get_common_controls(
    min_standards: int = Query(2, ge=2, le=15),
    domain_cluster: str = Query(None),
):
    r = await get_redis()
    raw_ctrls = await r.get(UCCF_CONTROLS_KEY)
    raw_links = await r.get(UCCF_LINKS_KEY)
    if not raw_ctrls or not raw_links:
        return {"common_controls": [], "total": 0}

    all_controls: list[dict] = json.loads(raw_ctrls)
    links: list[dict]        = json.loads(raw_links)
    ctrl_by_urn              = {c["urn"]: c for c in all_controls}

    matched_stds: dict[str, set[str]]   = {}
    match_details: dict[str, list[dict]] = {}

    for lk in links:
        for src, tgt in [(lk["source_urn"], lk["target_urn"]), (lk["target_urn"], lk["source_urn"])]:
            if src not in matched_stds:
                matched_stds[src]  = set()
                match_details[src] = []
            tgt_ctrl = ctrl_by_urn.get(tgt)
            if tgt_ctrl:
                matched_stds[src].add(tgt_ctrl.get("standard_name", ""))
                match_details[src].append({
                    "urn": tgt, "control_id": tgt_ctrl.get("control_id", ""),
                    "name": tgt_ctrl.get("control_name", ""),
                    "standard_urn": tgt_ctrl.get("standard_urn", ""),
                    "similarity": lk["similarity"],
                    "shared_kw":  lk["shared_keywords"],
                })

    result = []
    for urn, stds in matched_stds.items():
        if len(stds) + 1 < min_standards:
            continue
        ctrl = ctrl_by_urn.get(urn)
        if not ctrl:
            continue
        if domain_cluster and ctrl.get("domain_cluster") != domain_cluster:
            continue
        result.append({
            "urn":            urn,
            "control_id":     ctrl.get("control_id", ""),
            "name":           ctrl.get("control_name", ""),
            "text":           ctrl.get("control_text", ""),
            "domain_cluster": ctrl.get("domain_cluster", ""),
            "keywords":       ctrl.get("keywords", []),
            "standard_name":  ctrl.get("standard_name", ""),
            "standard_urn":   ctrl.get("standard_urn", ""),
            "domain_name":    ctrl.get("domain_name", ""),
            "standards_count": len(stds) + 1,
            "matches":        match_details.get(urn, []),
        })

    result.sort(key=lambda x: x["standards_count"], reverse=True)
    return {"common_controls": result[:300], "total": len(result)}


@router.get("/matrix")
async def get_overlap_matrix():
    r = await get_redis()
    raw_ctrls = await r.get(UCCF_CONTROLS_KEY)
    raw_links = await r.get(UCCF_LINKS_KEY)
    raw_stds  = await r.get(UCCF_STANDARDS_KEY)

    if not raw_links:
        return {"matrix": [], "standards": [], "total_pairs": 0}

    links: list[dict]        = json.loads(raw_links)
    all_controls: list[dict] = json.loads(raw_ctrls) if raw_ctrls else []
    stds_map: dict[str, dict] = json.loads(raw_stds) if raw_stds else {}

    totals = {s["name"]: s.get("total_controls", 1) for s in stds_map.values()}

    pair_counts: dict[str, int] = {}
    for lk in links:
        src_c = next((c for c in all_controls if c["urn"] == lk["source_urn"]), None)
        tgt_c = next((c for c in all_controls if c["urn"] == lk["target_urn"]), None)
        if not src_c or not tgt_c:
            continue
        a, b = sorted([src_c["standard_name"], tgt_c["standard_name"]])
        key = f"{a}||{b}"
        pair_counts[key] = pair_counts.get(key, 0) + 1

    matrix = []
    for key, count in pair_counts.items():
        a, b = key.split("||", 1)
        ta = totals.get(a, 1)
        tb = totals.get(b, 1)
        overlap_pct = round(count / min(ta, tb) * 100, 1) if min(ta, tb) > 0 else 0
        matrix.append({
            "standard_a": a, "standard_b": b,
            "shared_count": count, "overlap_pct": overlap_pct,
            "total_a": ta, "total_b": tb,
        })

    matrix.sort(key=lambda x: x["shared_count"], reverse=True)
    all_stds = [{"urn": v["urn"], "name": v["name"]} for v in stds_map.values()]
    return {"matrix": matrix, "standards": all_stds, "total_pairs": len(matrix)}


@router.post("/ingest")
async def ingest_standard_json(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Only .json files are accepted.")

    try:
        raw_bytes = await file.read()
        raw = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

    controls = _auto_parse(raw)
    if not controls:
        raise HTTPException(
            status_code=400,
            detail=(
                "Could not extract controls. Supported formats:\n"
                "1. Normalized: {standard_name, domains:[{id,name,controls:[{id,name,text}]}]}\n"
                "2. UAE IAS flat list: [{control_family_id, control_id, control_statement}]\n"
                "3. NCA flat list: [{framework_name, main_domain_id, control_id, control_statement}]\n"
                "4. Generic flat: [{standard_name, control_id, text/control_statement}]"
            ),
        )

    domains_created, ctrl_created = await _store_controls(controls)
    semantic_links = await _semantic_match_new(controls)

    return {
        "status":                  "ingested",
        "filename":                file.filename,
        "standard_name":           controls[0]["standard_name"],
        "standard_urn":            controls[0]["standard_urn"],
        "controls_parsed":         len(controls),
        "domains_created":         domains_created,
        "controls_created":        ctrl_created,
        "semantic_links_created":  semantic_links,
    }


@router.post("/remap")
async def remap_all():
    """Delete all semantic links and rebuild from scratch using transformer embeddings."""
    r = await get_redis()
    await r.delete(UCCF_LINKS_KEY)

    raw_ctrls = await r.get(UCCF_CONTROLS_KEY)
    if not raw_ctrls:
        return {"status": "remapped", "controls_processed": 0, "semantic_links_created": 0}

    all_controls: list[dict] = json.loads(raw_ctrls)

    # Batch-encode all control texts with the transformer
    texts = [c["control_text"] for c in all_controls]
    embeddings = await _encode_texts(texts)

    links: list[dict]       = []
    seen: set[tuple[str, str]] = set()
    total_links = 0

    for i, (ctrl_a, emb_a) in enumerate(zip(all_controls, embeddings)):
        for j in range(i + 1, len(all_controls)):
            ctrl_b = all_controls[j]
            if ctrl_a.get("standard_urn") == ctrl_b.get("standard_urn"):
                continue

            cluster_a = ctrl_a.get("domain_cluster", "general")
            cluster_b = ctrl_b.get("domain_cluster", "general")
            if cluster_a != cluster_b and cluster_a != "general" and cluster_b != "general":
                continue

            pair_key = tuple(sorted([ctrl_a["urn"], ctrl_b["urn"]]))
            if pair_key in seen:
                continue

            sim    = _cosine_sim(emb_a, embeddings[j])
            shared = sorted(set(ctrl_a.get("keywords") or []) & set(ctrl_b.get("keywords") or []))

            if sim >= SIMILARITY_THRESHOLD and len(shared) >= MIN_SHARED_KEYWORDS:
                match_type = "domain_match" if cluster_a == cluster_b else "keyword_overlap"
                links.append({
                    "source_urn":      ctrl_a["urn"],
                    "target_urn":      ctrl_b["urn"],
                    "source_standard": ctrl_a.get("standard_name", ""),
                    "target_standard": ctrl_b.get("standard_name", ""),
                    "similarity":      round(sim, 3),
                    "shared_keywords": shared,
                    "match_type":      match_type,
                })
                seen.add(pair_key)
                total_links += 1

    await r.set(UCCF_LINKS_KEY, json.dumps(links))
    return {
        "status":                 "remapped",
        "controls_processed":     len(all_controls),
        "semantic_links_created": total_links,
    }
