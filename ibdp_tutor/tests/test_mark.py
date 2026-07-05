import json
from pathlib import Path

import pytest

from ib_tutor.ingest import Chunk
from ib_tutor.mark import (
    GradingParseError,
    QuestionNotFound,
    find_markscheme_chunk,
    grade,
    render_mark_result,
)
from ib_tutor.store import get_collection, upsert_chunks


def fake_embed(texts: list[str], model: str) -> list[list[float]]:
    return [[float(len(t))] for t in texts]


@pytest.fixture
def collection_with_ms(tmp_path: Path):
    collection = get_collection(tmp_path)
    chunk = Chunk(
        text="(b)(ii) R1 sign argument that f'(x) > 0\nA1 conclusion (strictly increasing)",
        metadata={
            "subject": "mathaa",
            "type": "ms",
            "year": 2023,
            "session": "may",
            "paper": "p1",
            "level": "hl",
            "tz": "",
            "filename": "mathaa_ms_2023_may_p1_hl.pdf",
            "page": 4,
            "question_id": "3bii",
            "topic": "",
            "parse_quality": "ok",
        },
    )
    upsert_chunks(collection, [chunk], model="fake", embed_fn=fake_embed)
    return collection


class FakeChatClient:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    def chat(self, model: str, messages: list[dict[str, str]]) -> dict:
        return {"message": {"content": self.reply}}


GRADING_JSON = json.dumps(
    [
        {"code": "R1", "description": "sign argument", "status": "MISSED", "reason": "no sign argument given"},
        {"code": "A1", "description": "conclusion (strictly increasing)", "status": "HIT", "reason": "stated correctly"},
    ]
)


def test_find_markscheme_chunk_exact_match(collection_with_ms) -> None:
    chunk = find_markscheme_chunk(collection_with_ms, "3bii")
    assert chunk.metadata["question_id"] == "3bii"


def test_find_markscheme_chunk_raises_when_absent(collection_with_ms) -> None:
    with pytest.raises(QuestionNotFound):
        find_markscheme_chunk(collection_with_ms, "9zzz")


def test_grade_computes_hit_missed_and_total(collection_with_ms) -> None:
    client = FakeChatClient(GRADING_JSON)
    result = grade(
        "The derivative is positive so f is increasing.",
        "3bii",
        collection_with_ms,
        model="qwen2.5:7b-instruct",
        client=client,
    )
    assert result.total == 1
    assert result.available == 2
    assert result.points[0].status == "MISSED"
    assert result.points[1].status == "HIT"


def test_grade_awards_half_credit_for_partial(collection_with_ms) -> None:
    partial_json = json.dumps(
        [
            {"code": "R1", "description": "sign argument", "status": "PARTIAL", "reason": "incomplete"},
            {"code": "A1", "description": "conclusion (strictly increasing)", "status": "HIT", "reason": "stated correctly"},
        ]
    )
    client = FakeChatClient(partial_json)
    result = grade("answer", "3bii", collection_with_ms, model="qwen2.5:7b-instruct", client=client)
    assert result.total == 1.5  # 0.5 (PARTIAL) + 1 (HIT), not 1 (PARTIAL treated as MISSED)
    assert result.available == 2


def test_render_mark_result_matches_contract_shape(collection_with_ms) -> None:
    client = FakeChatClient(GRADING_JSON)
    result = grade("answer", "3bii", collection_with_ms, model="qwen2.5:7b-instruct", client=client)
    rendered = render_mark_result(result)
    assert "Question 3bii — [2 marks]" in rendered
    assert "✗ R1" in rendered
    assert "✓ A1" in rendered
    assert "Total: 1/2" in rendered


def test_grade_raises_on_unparseable_response(collection_with_ms) -> None:
    client = FakeChatClient("not json at all")
    with pytest.raises(GradingParseError):
        grade("answer", "3bii", collection_with_ms, model="qwen2.5:7b-instruct", client=client)


def test_grade_ignores_trailing_null_code_filler_point(collection_with_ms) -> None:
    """Regression test: the real qwen2.5 model sometimes appends a trailing
    {"code": null, ...} entry to say "no further points" after enumerating the
    real markscheme points. _mark_value(None) used to crash with a TypeError
    from re.search; such codeless entries should just be dropped.
    """
    raw = json.dumps(
        [
            {"code": "M1", "description": "correct unit", "status": "HIT", "reason": "correct"},
            {"code": None, "description": "", "status": "MISSED", "reason": "no further points"},
        ]
    )
    client = FakeChatClient(raw)
    result = grade("answer", "3bii", collection_with_ms, model="qwen2.5:7b-instruct", client=client)
    assert result.total == 1
    assert result.available == 1
