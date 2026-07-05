from pathlib import Path

import pytest

from ib_tutor.ingest import Chunk
from ib_tutor.mark import QuestionNotFound
from ib_tutor.quiz import extract_command_term, generate_quiz, reveal_answer
from ib_tutor.store import get_collection, upsert_chunks


def fake_embed(texts: list[str], model: str) -> list[list[float]]:
    return [[float(len(t))] for t in texts]


def make_chunk(text: str, doc_type: str, question_id: str, filename: str, page: int) -> Chunk:
    return Chunk(
        text=text,
        metadata={
            "subject": "physics",
            "type": doc_type,
            "year": 2022,
            "session": "nov",
            "paper": "p2",
            "level": "sl",
            "tz": "",
            "filename": filename,
            "page": page,
            "question_id": question_id,
            "topic": "",
            "parse_quality": "ok",
        },
    )


@pytest.fixture
def seeded(tmp_path: Path):
    collection = get_collection(tmp_path)
    chunks = [
        make_chunk("1. State the units of momentum.", "pp", "1", "physics_pp_2022_nov_p2_sl.pdf", 1),
        make_chunk("M1 correct unit kg m s-1", "ms", "1", "physics_ms_2022_nov_p2_sl.pdf", 1),
        make_chunk("stray header with no question", "pp", "", "physics_pp_2022_nov_p2_sl.pdf", 2),
        make_chunk("(ii) v = u + at, so 12 m/s.", "pp", "1bii", "physics_pp_2022_nov_p2_sl.pdf", 1),
    ]
    upsert_chunks(collection, chunks, model="fake", embed_fn=fake_embed)
    return collection


def test_extract_command_term_finds_known_term() -> None:
    assert extract_command_term("1. State the units of momentum.") == "State"
    assert extract_command_term("no command term here") == ""


def test_generate_quiz_only_lifts_structured_pp_chunks(seeded) -> None:
    items = generate_quiz(seeded, n=5)
    assert len(items) == 1
    item = items[0]
    assert item.question_id == "1"
    assert item.text == "1. State the units of momentum."
    assert item.source_filename == "physics_pp_2022_nov_p2_sl.pdf"
    assert item.command_term == "State"


def test_generate_quiz_skips_subpart_with_no_command_term(seeded) -> None:
    items = generate_quiz(seeded, n=5)
    # "1bii" has a question_id but no command-term stem of its own, so showing
    # it standalone would be unanswerable without its parent question's context
    assert "1bii" not in {i.question_id for i in items}


def test_generate_quiz_respects_n(seeded) -> None:
    items = generate_quiz(seeded, n=0)
    assert items == []


def test_reveal_answer_pairs_with_markscheme(seeded) -> None:
    items = generate_quiz(seeded, n=5)
    ms_chunk = reveal_answer(seeded, items[0])
    assert "M1" in ms_chunk.text
    assert ms_chunk.metadata["question_id"] == "1"


def test_reveal_answer_raises_when_markscheme_missing(tmp_path: Path) -> None:
    collection = get_collection(tmp_path)
    chunk = make_chunk("2. Determine the acceleration.", "pp", "2", "physics_pp_2022_nov_p2_sl.pdf", 3)
    upsert_chunks(collection, [chunk], model="fake", embed_fn=fake_embed)
    items = generate_quiz(collection, n=5)
    with pytest.raises(QuestionNotFound):
        reveal_answer(collection, items[0])
