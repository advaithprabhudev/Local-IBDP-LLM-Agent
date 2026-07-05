"""Hybrid retrieval: dense (ChromaDB) + BM25, fused with reciprocal rank fusion."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import chromadb
from rank_bm25 import BM25Okapi

SUBJECT_ALIASES = {
    "math aa": "mathaa",
    "maths": "mathaa",
    "math": "mathaa",
    "aa": "mathaa",
    "mathaa": "mathaa",
    "physics": "physics",
}
TYPE_ALIASES = {
    "markscheme": "ms",
    "ms": "ms",
    "past paper": "pp",
    "pastpaper": "pp",
    "pp": "pp",
    "textbook": "tb",
    "tb": "tb",
    "notes": "notes",
}
FILTER_ALIAS_TABLES = {"subject": SUBJECT_ALIASES, "type": TYPE_ALIASES}


@dataclass
class RetrievedChunk:
    text: str
    metadata: dict[str, Any]
    score: float


class NoMatchingChunks(Exception):
    def __init__(self, filters: dict[str, Any]) -> None:
        self.filters = filters
        super().__init__(f"No chunks match filters: {filters}")


def normalize_filters(**kwargs: str | int | None) -> dict[str, str | int]:
    """Resolve user-facing aliases (e.g. "math aa" -> "mathaa") to canonical values.

    Callers must invoke this on raw user/CLI input before passing filters to
    hybrid_retrieve()/ask()/grade()/generate_quiz() — those functions expect
    already-normalized filters and never call this themselves.
    """
    filters: dict[str, str | int] = {}
    for key, value in kwargs.items():
        if value is None:
            continue
        if isinstance(value, str):
            table = FILTER_ALIAS_TABLES.get(key, {})
            value = table.get(value.lower(), value.lower())
        filters[key] = value
    return filters


def build_where(filters: dict[str, str | int]) -> dict[str, Any] | None:
    if not filters:
        return None
    conds = [{k: v} for k, v in filters.items()]
    if len(conds) == 1:
        return conds[0]
    return {"$and": conds}


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def reciprocal_rank_fusion(
    rankings: list[list[str]], k: int = 60
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda kv: -kv[1])


def hybrid_retrieve(
    collection: chromadb.Collection,
    query: str,
    embed_fn: Any,
    model: str,
    filters: dict[str, str | int] | None = None,
    k: int = 8,
) -> list[RetrievedChunk]:
    where = build_where(filters or {})
    candidates = collection.get(where=where) if where else collection.get()
    ids: list[str] = list(candidates["ids"] or [])
    if not ids:
        raise NoMatchingChunks(filters or {})
    docs: list[str] = list(candidates["documents"] or [])
    metas: list[dict[str, Any]] = [dict(m) for m in (candidates["metadatas"] or [])]

    pool = min(k * 4, len(ids))

    query_embedding = embed_fn([query], model)[0]
    dense_res = collection.query(
        query_embeddings=[query_embedding], where=where, n_results=pool
    )
    dense_ids: list[str] = dense_res["ids"][0]

    bm25 = BM25Okapi([_tokenize(d) for d in docs])
    bm25_scores = bm25.get_scores(_tokenize(query))
    bm25_ids = [ids[i] for i in sorted(range(len(ids)), key=lambda i: -bm25_scores[i])[:pool]]

    fused = reciprocal_rank_fusion([dense_ids, bm25_ids])[:k]

    id_to_doc = dict(zip(ids, docs, strict=True))
    id_to_meta = dict(zip(ids, metas, strict=True))
    return [
        RetrievedChunk(text=id_to_doc[cid], metadata=id_to_meta[cid], score=score)
        for cid, score in fused
    ]
