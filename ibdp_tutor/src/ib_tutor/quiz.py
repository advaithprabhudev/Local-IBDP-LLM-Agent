"""Quiz generation: lift questions verbatim from past-paper chunks, reveal via mark."""

from __future__ import annotations

import re
from dataclasses import dataclass

import chromadb

from ib_tutor.mark import find_markscheme_chunk
from ib_tutor.retrieve import RetrievedChunk, build_where

COMMAND_TERMS = [
    "Define",
    "State",
    "Calculate",
    "Determine",
    "Show that",
    "Hence",
    "Explain",
    "Evaluate",
    "Describe",
    "Justify",
    "Compare",
    "Estimate",
    "Sketch",
    "Deduce",
]
_COMMAND_TERM_RE = re.compile(
    "|".join(re.escape(t) for t in COMMAND_TERMS), re.IGNORECASE
)


@dataclass
class QuizItem:
    question_id: str
    text: str
    source_filename: str
    source_page: int
    command_term: str


def extract_command_term(text: str) -> str:
    m = _COMMAND_TERM_RE.search(text)
    return m.group(0) if m else ""


def generate_quiz(
    collection: chromadb.Collection,
    n: int,
    filters: dict[str, str | int] | None = None,
) -> list[QuizItem]:
    """Pull n past-paper question chunks verbatim. Filters (subject/topic/...) are
    combined with type="pp" and applied with AND semantics."""
    where = build_where({**(filters or {}), "type": "pp"})
    result = collection.get(where=where)
    documents: list[str] = list(result["documents"] or [])
    metadatas: list[dict[str, object]] = [dict(m) for m in (result["metadatas"] or [])]

    items = [
        QuizItem(
            question_id=str(meta.get("question_id", "")),
            text=doc,
            source_filename=str(meta.get("filename", "")),
            source_page=int(str(meta.get("page", 0))),
            command_term=extract_command_term(doc),
        )
        for doc, meta in zip(documents, metadatas, strict=True)
        # skip headerless/unstructured chunks, and subpart fragments with no
        # command term of their own (e.g. "(ii) Hence deduce...") that would be
        # unanswerable shown standalone without their parent question's stem
        if meta.get("question_id") and extract_command_term(doc)
    ]
    return items[:n]


def reveal_answer(
    collection: chromadb.Collection,
    item: QuizItem,
    filters: dict[str, str | int] | None = None,
) -> RetrievedChunk:
    """Retrieve the markscheme chunk for this quiz item's question_id.

    Raises QuestionNotFound (from mark.py) if no matching markscheme was ingested
    (e.g. only the past paper, not its markscheme, was added to sources/).
    """
    return find_markscheme_chunk(collection, item.question_id, filters)
