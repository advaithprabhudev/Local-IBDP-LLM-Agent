from pathlib import Path

import pytest

from ib_tutor.retrieve import (
    NoMatchingChunks,
    build_where,
    hybrid_retrieve,
    normalize_filters,
    reciprocal_rank_fusion,
)
from ib_tutor.store import get_collection, upsert_chunks
from ib_tutor.ingest import Chunk

VOCAB = ["momentum", "photosynthesis", "integral", "tectonic"]


def fake_embed(texts: list[str], model: str) -> list[list[float]]:
    return [[1.0 if word in t.lower() else 0.0 for word in VOCAB] for t in texts]


def make_chunk(text: str, subject: str, doc_type: str, filename: str, page: int) -> Chunk:
    return Chunk(
        text=text,
        metadata={
            "subject": subject,
            "type": doc_type,
            "year": 2023,
            "session": "may",
            "paper": "p1",
            "level": "hl" if subject == "mathaa" else "sl",
            "tz": "",
            "filename": filename,
            "page": page,
            "question_id": "",
            "topic": "",
            "parse_quality": "ok",
        },
    )


@pytest.fixture
def seeded_collection(tmp_path: Path):
    collection = get_collection(tmp_path)
    chunks = [
        make_chunk(
            "Conservation of momentum in an elastic collision between two carts.",
            "physics",
            "pp",
            "physics_pp_2023_may_p1_sl.pdf",
            1,
        ),
        make_chunk(
            "Photosynthesis converts light energy into chemical energy in plants.",
            "physics",
            "notes",
            "physics_notes_bio_crossover.pdf",
            1,
        ),
        make_chunk(
            "Evaluate the definite integral of x squared from 0 to 1.",
            "mathaa",
            "pp",
            "mathaa_pp_2023_may_p1_hl.pdf",
            1,
        ),
        make_chunk(
            "Plate tectonic boundaries cause earthquakes at convergent zones.",
            "physics",
            "notes",
            "physics_notes_geo_crossover.pdf",
            1,
        ),
    ]
    upsert_chunks(collection, chunks, model="fake", embed_fn=fake_embed)
    return collection


def test_hybrid_retrieve_finds_known_relevant_chunk(seeded_collection) -> None:
    results = hybrid_retrieve(
        seeded_collection, "What is conserved in a collision involving momentum?",
        embed_fn=fake_embed, model="fake", k=8,
    )
    assert any("momentum" in r.text.lower() for r in results[:1])


def test_hybrid_retrieve_applies_subject_filter(seeded_collection) -> None:
    filters = normalize_filters(subject="maths")
    results = hybrid_retrieve(
        seeded_collection, "integral", embed_fn=fake_embed, model="fake", filters=filters, k=8
    )
    assert all(r.metadata["subject"] == "mathaa" for r in results)
    assert any("integral" in r.text.lower() for r in results)


def test_hybrid_retrieve_raises_on_zero_match_filter(seeded_collection) -> None:
    filters = normalize_filters(subject="mathaa", type="ms")
    with pytest.raises(NoMatchingChunks):
        hybrid_retrieve(seeded_collection, "anything", embed_fn=fake_embed, model="fake", filters=filters)


def test_normalize_filters_aliases() -> None:
    assert normalize_filters(subject="Maths", type="MS") == {"subject": "mathaa", "type": "ms"}
    assert normalize_filters(subject=None, year=2023) == {"year": 2023}


def test_build_where_and_semantics() -> None:
    assert build_where({}) is None
    assert build_where({"subject": "mathaa"}) == {"subject": "mathaa"}
    assert build_where({"subject": "mathaa", "year": 2023}) == {
        "$and": [{"subject": "mathaa"}, {"year": 2023}]
    }


def test_reciprocal_rank_fusion_rewards_agreement() -> None:
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "a", "c"]])
    assert fused[0][0] in ("a", "b")
    assert fused[-1][0] == "c"
