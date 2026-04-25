"""
NCA Control Retriever
---------------------
Loads nca_oscal_catalog.json (432 controls) and the pre-computed
OpenAI text-embedding-3-large vectors (oai_nca_vecs.pkl, shape 432×3072).

Usage:
    retriever = ControlRetriever()
    controls  = retriever.search("identity and access management", top_k=12)
    ctx_block = retriever.format_for_prompt(controls)
"""
from __future__ import annotations

import json
import pickle
import re
from pathlib import Path
from functools import lru_cache

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

_BASE = Path(__file__).resolve().parent.parent.parent   # …/backend


class ControlRetriever:
    """Semantic search over NCA OSCAL catalog using pre-computed embeddings."""

    def __init__(self):
        self._controls: list[dict] = []
        self._vecs: np.ndarray | None = None
        self._load()

    # ── Catalog parsing ───────────────────────────────────────────────────────

    def _load(self) -> None:
        catalog_path = _BASE / "nca_oscal_catalog.json"
        with open(catalog_path, encoding="utf-8") as f:
            raw = json.load(f)
        root = raw.get("catalog", raw)
        self._parse_groups(root.get("groups", []))

        vecs_path = _BASE / "oai_nca_vecs.pkl"
        with open(vecs_path, "rb") as f:
            vecs = pickle.load(f)
        self._vecs = vecs if isinstance(vecs, np.ndarray) else np.array(vecs)

    def _parse_groups(self, groups: list, domain_path: str = "") -> None:
        for g in groups:
            title = g.get("title", "")
            if g.get("groups"):
                self._parse_groups(g["groups"], domain_path=title)
            for ctrl in g.get("controls", []):
                self._extract_control(ctrl, domain=title)

    def _extract_control(self, ctrl: dict, domain: str) -> None:
        cid   = ctrl.get("id", "")
        title = ctrl.get("title", "")

        # canonical display label: prefer the 'label' prop (e.g. "1-1-1")
        label = cid
        framework = "NCA"
        for p in ctrl.get("props", []):
            if p.get("name") == "label":
                label = p.get("value", label)
            if p.get("name") == "framework":
                framework = p.get("value", framework)

        # collect statement + objective prose
        prose_parts: list[str] = []
        for part in ctrl.get("parts", []):
            prose = part.get("prose", "")
            if prose:
                prose_parts.append(_clean(prose))
            for sub in part.get("parts", []):
                sub_prose = sub.get("prose", "")
                if sub_prose:
                    prose_parts.append(_clean(sub_prose))

        full_text = f"{domain} > {title}. " + " ".join(prose_parts)

        self._controls.append({
            "id":          cid,
            "display_id":  f"{framework} {label}",
            "framework":   framework,
            "label":       label,
            "title":       title,
            "domain":      domain,
            "text":        full_text,
        })

        for sub in ctrl.get("controls", []):
            self._extract_control(sub, domain=domain)

    # ── Semantic search ───────────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 15,
               openai_client=None) -> list[dict]:
        """Return top_k controls most semantically relevant to query."""
        if not self._controls or self._vecs is None:
            return []

        q_vec = self._embed(query, openai_client)
        n = min(len(self._controls), self._vecs.shape[0])
        scores = cosine_similarity(q_vec, self._vecs[:n])[0]
        top_idx = np.argsort(scores)[::-1][:top_k]

        results = []
        for idx in top_idx:
            entry = self._controls[idx].copy()
            entry["score"] = float(scores[idx])
            results.append(entry)
        return results

    def _embed(self, text: str, client=None) -> np.ndarray:
        if client is None:
            from openai import OpenAI
            from app.policy_factory.config import OPENAI_API_KEY
            client = OpenAI()
        resp = client.embeddings.create(
            model="text-embedding-3-large", input=text
        )
        return np.array(resp.data[0].embedding).reshape(1, -1)

    # ── Prompt formatting ─────────────────────────────────────────────────────

    def format_for_prompt(self, controls: list[dict],
                          max_chars: int = 4000) -> str:
        """Format retrieved controls as a numbered list for the LLM prompt."""
        lines = []
        total = 0
        for c in controls:
            snippet = c["text"][:250].rstrip()
            line = f"[{c['display_id']}] {c['title']}\n  → {snippet}"
            total += len(line)
            if total > max_chars:
                break
            lines.append(line)
        return "\n\n".join(lines)

    def get_by_id(self, display_id: str) -> dict | None:
        for c in self._controls:
            if c["display_id"] == display_id:
                return c
        return None


@lru_cache(maxsize=1)
def get_retriever() -> ControlRetriever:
    return ControlRetriever()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
