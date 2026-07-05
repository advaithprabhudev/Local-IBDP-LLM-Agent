"""Point-by-point grading against a named markscheme question chunk."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import cast

import chromadb
import ollama

from ib_tutor.ask import ChatClient
from ib_tutor.retrieve import RetrievedChunk, build_where
from ib_tutor.store import OllamaUnavailable

GRADING_SYSTEM_PROMPT = """You are an IB examiner grading a candidate's answer against an \
official markscheme excerpt. IB mark codes: M=method (valid attempt, even with numerical \
errors), A=accuracy (requires correct value, usually depends on the preceding M), \
R=reasoning/justification, AG=answer given (full working required, restating the final \
line alone earns nothing), ft=follow-through (an earlier error is not re-penalised; grade \
later steps against the candidate's own carried value).

Rules:
- Enumerate every marking point in the markscheme excerpt, in order.
- Classify each as "HIT", "MISSED", or "PARTIAL" with a one-line reason.
- Apply follow-through: if an early mark is missed, grade subsequent points against the \
candidate's own carried-forward value rather than re-penalising the same error.
- Never award marks for content that is not in the markscheme excerpt. Never invent \
marking points.
- Respond with ONLY a JSON array, no prose: \
[{"code": "M1", "description": "...", "status": "HIT", "reason": "..."}, ...]
"""


class QuestionNotFound(Exception):
    def __init__(self, question_id: str) -> None:
        self.question_id = question_id
        super().__init__(f"No markscheme chunk found for question {question_id!r}")


class QuestionMismatch(Exception):
    def __init__(self, requested: str, got: str) -> None:
        self.requested = requested
        self.got = got
        super().__init__(f"Retrieved chunk is for question {got!r}, not {requested!r} — refusing to grade")


class GradingParseError(Exception):
    pass


@dataclass
class MarkPoint:
    code: str
    description: str
    status: str  # "HIT" | "MISSED" | "PARTIAL"
    reason: str


@dataclass
class MarkResult:
    question_id: str
    points: list[MarkPoint]
    total: float
    available: int


def find_markscheme_chunk(
    collection: chromadb.Collection,
    question_id: str,
    filters: dict[str, str | int] | None = None,
) -> RetrievedChunk:
    where = build_where({**(filters or {}), "question_id": question_id, "type": "ms"})
    result = collection.get(where=where)
    ids: list[str] = list(result["ids"] or [])
    if not ids:
        raise QuestionNotFound(question_id)
    metadatas = list(result["metadatas"] or [])
    documents = list(result["documents"] or [])
    metadata = dict(metadatas[0])
    if metadata.get("question_id") != question_id:
        raise QuestionMismatch(question_id, str(metadata.get("question_id")))
    return RetrievedChunk(text=documents[0], metadata=metadata, score=1.0)


def _mark_value(code: str) -> int:
    m = re.search(r"\d+", code)
    return int(m.group()) if m else 0


def build_grading_messages(candidate_answer: str, ms_chunk: RetrievedChunk) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": GRADING_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Markscheme excerpt (question {ms_chunk.metadata.get('question_id')}):\n"
                f"{ms_chunk.text}\n\nCandidate answer:\n{candidate_answer}"
            ),
        },
    ]


def _parse_grading_response(raw: str) -> list[MarkPoint]:
    try:
        data = json.loads(raw)
        return [
            MarkPoint(
                code=item["code"],
                description=item["description"],
                status=item["status"],
                reason=item["reason"],
            )
            for item in data
            # models occasionally append a codeless "no further points" filler
            # entry after enumerating the real marking points; it carries no
            # mark value, so drop it rather than let _mark_value(None) crash.
            if item["code"]
        ]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise GradingParseError(f"Could not parse grading response as JSON: {raw!r}") from e


def grade(
    candidate_answer: str,
    question_id: str,
    collection: chromadb.Collection,
    model: str,
    filters: dict[str, str | int] | None = None,
    client: ChatClient | None = None,
) -> MarkResult:
    ms_chunk = find_markscheme_chunk(collection, question_id, filters)
    resolved_client: ChatClient = client or cast(ChatClient, ollama.Client())
    messages = build_grading_messages(candidate_answer, ms_chunk)
    try:
        response = resolved_client.chat(model=model, messages=messages)
    except Exception as e:
        raise OllamaUnavailable(
            f"Can't reach Ollama or model '{model}' isn't pulled — "
            f"run `ollama serve` and `ollama pull {model}`."
        ) from e
    points = _parse_grading_response(response["message"]["content"])
    total = sum(
        _mark_value(p.code) if p.status == "HIT" else _mark_value(p.code) / 2
        for p in points
        if p.status in ("HIT", "PARTIAL")
    )
    available = sum(_mark_value(p.code) for p in points)
    return MarkResult(question_id=question_id, points=points, total=total, available=available)


def render_mark_result(result: MarkResult) -> str:
    lines = [f"Question {result.question_id} — [{result.available} marks]"]
    symbols = {"HIT": "✓", "PARTIAL": "~"}
    for p in result.points:
        mark = symbols.get(p.status, "✗")
        suffix = "HIT" if p.status == "HIT" else f"{p.status}: {p.reason}"
        lines.append(f"{mark} {p.code}  {p.description:<45} — {suffix}")
    lines.append(f"Total: {result.total:g}/{result.available}")
    return "\n".join(lines)
