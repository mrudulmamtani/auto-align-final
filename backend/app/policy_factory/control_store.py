"""
Control Store — loads NIST2.json (with uae_ia_id) and UAE IA controls,
indexes them as ControlChunk objects backed by pre-computed embeddings.
Retrieval is pure cosine similarity; no LLM call needed for search.
"""
import json, pickle, re, hashlib, uuid
from pathlib import Path
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from openai import OpenAI

from .config import (
    OPENAI_API_KEY, NIST_JSON, UAE_JSON, NCA_JSON,
    NIST_VECS_CACHE, UAE_VECS_CACHE, NCA_VECS_CACHE, EMBED_MODEL, RETRIEVAL_TOP_K_PER_QUERY
)
RETRIEVAL_TOP_K = RETRIEVAL_TOP_K_PER_QUERY   # local alias for the retrieve() default
from .models import ControlChunk, RetrievalPacket


def _clean(text: str) -> str:
    text = re.sub(r"\{\{[^}]*\}\}", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _prose(parts: list, seen: set | None = None) -> list[str]:
    if seen is None:
        seen = set()
    out = []
    for p in parts:
        pr = p.get("prose", "").strip()
        if pr and pr not in seen:
            out.append(pr)
            seen.add(pr)
        if "parts" in p:
            out.extend(_prose(p["parts"], seen))
    return out


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class ControlStore:
    """
    In-memory index of all controls with their embeddings.
    Loaded once at pipeline startup; retrieval is sub-millisecond.
    """

    def __init__(self):
        self._client = OpenAI()
        self.chunks: list[ControlChunk] = []
        self._vecs: np.ndarray | None = None
        self._load()

    # ── Loading ───────────────────────────────────────────────────────────────

    def _load(self) -> None:
        nca_chunks,  nca_vecs  = self._load_nca()    # NCA first — primary framework
        nist_chunks, nist_vecs = self._load_nist()   # NIST second — supplementary

        self.chunks = nca_chunks + nist_chunks
        self._vecs  = np.vstack([nca_vecs, nist_vecs]).astype(np.float32)

        print(f"[ControlStore] {len(nca_chunks)} NCA (primary) + "
              f"{len(nist_chunks)} NIST (supplementary) chunks loaded. "
              f"Embedding matrix: {self._vecs.shape}")

    def _load_nist(self) -> tuple[list[ControlChunk], np.ndarray]:
        with open(NIST_JSON, encoding="utf-8") as f:
            catalog = json.load(f)["catalog"]

        with open(NIST_VECS_CACHE, "rb") as f:
            vecs: np.ndarray = pickle.load(f)

        chunks: list[ControlChunk] = []
        for g in catalog["groups"]:
            fid, ftitle = g["id"], g["title"]
            for ctrl in g.get("controls", []):
                chunks.extend(self._nist_ctrl_to_chunks(ctrl, fid, ftitle))

        assert len(chunks) == vecs.shape[0], (
            f"NIST chunk count mismatch: {len(chunks)} chunks vs {vecs.shape[0]} vectors"
        )
        return chunks, vecs

    def _nist_ctrl_to_chunks(
        self, ctrl: dict, fid: str, ftitle: str, parent_id: str | None = None
    ) -> list[ControlChunk]:
        labels = [p["value"] for p in ctrl.get("props", []) if p.get("name") == "label"]
        label = labels[0] if labels else ctrl["id"]
        stmt = _clean(" ".join(_prose(ctrl.get("parts", []))))
        full = _clean(f"{ftitle}: {ctrl['title']}. {stmt}")

        chunks = [ControlChunk(
            chunk_id   = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"nist:{ctrl['id']}")),
            framework  = "NIST_80053",
            control_id = label,
            title      = ctrl["title"],
            statement  = full,
            domain     = ftitle,
            subdomain  = "",
            uae_ia_id  = ctrl.get("uae_ia_id"),
            nca_id     = ctrl.get("nca_id"),
            content_hash = _sha256(full),
            framework_version = "SP800-53r5",
        )]
        for enh in ctrl.get("controls", []):
            chunks.extend(self._nist_ctrl_to_chunks(enh, fid, ftitle, label))
        return chunks

    def _load_uae(self) -> tuple[list[ControlChunk], np.ndarray]:
        with open(UAE_JSON, encoding="utf-8") as f:
            catalog = json.load(f)["catalog"]

        with open(UAE_VECS_CACHE, "rb") as f:
            vecs: np.ndarray = pickle.load(f)

        chunks: list[ControlChunk] = []
        for g in catalog["groups"]:
            for sg in g.get("groups", []):
                for ctrl in sg.get("controls", []):
                    labels = [p["value"] for p in ctrl.get("props", []) if p.get("name") == "label"]
                    label = labels[0] if labels else ctrl["id"]
                    stmt = _clean(" ".join(_prose(ctrl.get("parts", []))))
                    full = _clean(f"{g['title']} > {sg['title']}: {ctrl['title']}. {stmt}")
                    chunks.append(ControlChunk(
                        chunk_id     = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"uae:{ctrl['id']}")),
                        framework    = "UAE_IA",
                        control_id   = label,
                        title        = ctrl["title"],
                        statement    = full,
                        domain       = g["title"],
                        subdomain    = sg["title"],
                        content_hash = _sha256(full),
                        framework_version = "UAE_IA_v1",
                    ))

        assert len(chunks) == vecs.shape[0], (
            f"UAE chunk count mismatch: {len(chunks)} chunks vs {vecs.shape[0]} vectors"
        )
        return chunks, vecs

    def _load_nca(self) -> tuple[list[ControlChunk], np.ndarray]:
        with open(NCA_JSON, encoding="utf-8") as f:
            catalog = json.load(f)["catalog"]

        with open(NCA_VECS_CACHE, "rb") as f:
            vecs: np.ndarray = pickle.load(f)

        chunks: list[ControlChunk] = []
        for top_group in catalog["groups"]:
            top_id  = top_group["id"]
            fw_prop = next((p["value"] for p in top_group.get("props", [])
                            if p.get("name") == "framework"), top_id.upper())
            nca_fw_key = f"NCA_{fw_prop.upper()}"   # "NCA_ECC", "NCA_CSCC", etc.

            for d_group in top_group.get("groups", []):
                d_title = d_group["title"]
                for sd_group in d_group.get("groups", []):
                    sd_title = sd_group["title"]
                    for ctrl in sd_group.get("controls", []):
                        labels = [p["value"] for p in ctrl.get("props", [])
                                  if p.get("name") == "label"]
                        label = labels[0] if labels else ctrl["id"]
                        stmt  = _clean(" ".join(_prose(ctrl.get("parts", []))))
                        full  = _clean(f"{d_title} > {sd_title}: {ctrl['title']}. {stmt}")
                        chunks.append(ControlChunk(
                            chunk_id     = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"nca:{ctrl['id']}")),
                            framework    = nca_fw_key,
                            control_id   = label,
                            title        = ctrl["title"],
                            statement    = full,
                            domain       = d_title,
                            subdomain    = sd_title,
                            nca_id       = label,   # NCA controls reference themselves
                            content_hash = _sha256(full),
                            framework_version = fw_prop,
                        ))

        assert len(chunks) == vecs.shape[0], (
            f"NCA chunk count mismatch: {len(chunks)} chunks vs {vecs.shape[0]} vectors"
        )
        return chunks, vecs

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        top_k: int = RETRIEVAL_TOP_K,
        framework_filter: str | None = None,   # exact match OR prefix match when ends with "_"
        domain_filter: str | None = None,
    ) -> RetrievalPacket:
        q_vec = self._embed_query(query)
        sims = cosine_similarity(q_vec, self._vecs)[0]

        mask = np.ones(len(self.chunks), dtype=bool)
        if framework_filter:
            if framework_filter.endswith("_"):   # prefix match e.g. "NCA_"
                mask &= np.array([c.framework.startswith(framework_filter) for c in self.chunks])
            else:                                # exact match e.g. "NIST_80053"
                mask &= np.array([c.framework == framework_filter for c in self.chunks])
        if domain_filter:
            mask &= np.array([domain_filter.lower() in c.domain.lower() for c in self.chunks])

        masked_sims = np.where(mask, sims, -1.0)
        top_idx = np.argsort(masked_sims)[::-1][:top_k]

        selected = [self.chunks[int(i)] for i in top_idx if masked_sims[int(i)] > 0]
        return RetrievalPacket(query_topic=query, chunks=selected)

    def retrieve_nca(self, query: str, top_k: int = 25) -> RetrievalPacket:
        """Primary retrieval — NCA controls only (all NCA_ frameworks)."""
        return self.retrieve(query, top_k=top_k, framework_filter="NCA_")

    def retrieve_nist(self, query: str, top_k: int = 10) -> RetrievalPacket:
        """Supplementary retrieval — NIST SP 800-53 controls."""
        return self.retrieve(query, top_k=top_k, framework_filter="NIST_80053")

    def retrieve_by_ids(self, control_ids: list[str]) -> list[ControlChunk]:
        id_set = set(control_ids)
        return [c for c in self.chunks if c.control_id in id_set]

    def _embed_query(self, text: str) -> np.ndarray:
        resp = self._client.embeddings.create(model=EMBED_MODEL, input=[text])
        return np.array([resp.data[0].embedding], dtype=np.float32)
