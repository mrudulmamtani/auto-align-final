"""
Document dependency graph loaded from docGenConstruct.json.

Provides document metadata, dependency resolution, and topological ordering
for the full 110-document governance catalog.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

_CONSTRUCT_PATH = os.path.join(
    Path(__file__).resolve().parent.parent.parent, "docGenConstruct.json"
)


class DocMeta(TypedDict):
    id: str
    type: str           # "policy" | "standard" | "procedure"
    name_en: str
    name_ar: str
    wave: int
    depends_on: list[str]


@lru_cache(maxsize=1)
def _load() -> tuple[dict[str, DocMeta], list[tuple[str, list[str]]]]:
    """Returns (doc_map, wave_order).  wave_order: [(wave_key, [doc_ids]), ...]"""
    with open(_CONSTRUCT_PATH, encoding="utf-8") as f:
        data = json.load(f)

    doc_map: dict[str, DocMeta] = {}
    for d in data["documents"]:
        doc_map[d["id"]] = DocMeta(
            id=d["id"],
            type=d["type"],
            name_en=d["name_en"],
            name_ar=d.get("name_ar", ""),
            wave=d["wave"],
            depends_on=d.get("depends_on", []),
        )

    wave_order = list(data["generation_order"].items())
    return doc_map, wave_order


def get_all_documents() -> list[DocMeta]:
    """Return all 110 documents in wave order."""
    doc_map, wave_order = _load()
    seen: set[str] = set()
    result: list[DocMeta] = []
    for _, ids in wave_order:
        for doc_id in ids:
            if doc_id in doc_map and doc_id not in seen:
                result.append(doc_map[doc_id])
                seen.add(doc_id)
    for doc_id, meta in doc_map.items():
        if doc_id not in seen:
            result.append(meta)
    return result


def get_all_waves() -> list[tuple[str, list[str]]]:
    """Return all waves as [(wave_key, [doc_ids]), ...]."""
    _, wave_order = _load()
    return wave_order


def get_document(doc_id: str) -> DocMeta | None:
    doc_map, _ = _load()
    return doc_map.get(doc_id)


def get_dependencies(doc_id: str) -> list[DocMeta]:
    """Direct (one-hop) dependencies only."""
    doc_map, _ = _load()
    doc = doc_map.get(doc_id)
    if not doc:
        return []
    return [doc_map[d] for d in doc["depends_on"] if d in doc_map]


def get_all_dependencies(doc_id: str) -> list[DocMeta]:
    """All transitive dependencies in topological order (deps first, self excluded)."""
    doc_map, _ = _load()
    visited: set[str] = set()
    order: list[str] = []

    def visit(did: str) -> None:
        if did in visited:
            return
        visited.add(did)
        for dep in doc_map.get(did, {}).get("depends_on", []):
            visit(dep)
        order.append(did)

    doc = doc_map.get(doc_id)
    if not doc:
        return []
    for dep in doc["depends_on"]:
        visit(dep)
    return [doc_map[d] for d in order if d != doc_id and d in doc_map]


def get_dependents(doc_id: str) -> list[DocMeta]:
    """Documents that directly (one-hop) depend on this document."""
    doc_map, _ = _load()
    return [d for d in doc_map.values() if doc_id in d["depends_on"]]


def get_all_dependents(doc_id: str) -> list[DocMeta]:
    """All documents that transitively depend on this document (downstream)."""
    doc_map, _ = _load()
    result: list[DocMeta] = []
    seen: set[str] = set()

    def visit(did: str) -> None:
        for d in doc_map.values():
            if did in d["depends_on"] and d["id"] not in seen:
                seen.add(d["id"])
                result.append(d)
                visit(d["id"])

    visit(doc_id)
    return result


def get_generation_order(doc_ids: list[str]) -> list[str]:
    """
    Return the given doc_ids + their transitive dependencies in topological
    generation order (all dependencies appear before their dependents).
    """
    doc_map, _ = _load()
    visited: set[str] = set()
    order: list[str] = []

    def visit(did: str) -> None:
        if did in visited or did not in doc_map:
            return
        visited.add(did)
        for dep in doc_map[did]["depends_on"]:
            visit(dep)
        order.append(did)

    for did in doc_ids:
        visit(did)
    return order
