from pathlib import Path

import pytest

from ib_tutor.ingest import Chunk
from ib_tutor.store import OllamaUnavailable, embed_texts, get_collection, upsert_chunks


class FakeClient:
    def __init__(self, dim: int = 4) -> None:
        self.dim = dim
        self.calls: list[tuple[str, str]] = []

    def embeddings(self, model: str, prompt: str) -> dict[str, list[float]]:
        self.calls.append((model, prompt))
        return {"embedding": [float(len(prompt))] * self.dim}


class BrokenClient:
    def embeddings(self, model: str, prompt: str) -> dict[str, list[float]]:
        raise ConnectionError("no server")


def test_embed_texts_uses_client() -> None:
    client = FakeClient()
    result = embed_texts(["hello", "world!"], model="nomic-embed-text", client=client)
    assert result == [[5.0] * 4, [6.0] * 4]
    assert client.calls == [("nomic-embed-text", "hello"), ("nomic-embed-text", "world!")]


def test_embed_texts_raises_actionable_error_when_unreachable() -> None:
    with pytest.raises(OllamaUnavailable, match="ollama serve"):
        embed_texts(["hi"], model="nomic-embed-text", client=BrokenClient())


def test_upsert_chunks_persists_with_metadata(tmp_path: Path) -> None:
    collection = get_collection(tmp_path)
    chunks = [
        Chunk(
            text="1. Award 1 mark",
            metadata={
                "subject": "mathaa",
                "type": "ms",
                "year": 2023,
                "session": "may",
                "paper": "p1",
                "level": "hl",
                "tz": "",
                "filename": "mathaa_ms_2023_may_p1_hl.pdf",
                "page": 1,
                "question_id": "1",
                "topic": "",
                "parse_quality": "ok",
            },
        )
    ]

    def fake_embed(texts: list[str], model: str) -> list[list[float]]:
        return [[1.0, 2.0, 3.0] for _ in texts]

    upsert_chunks(collection, chunks, model="nomic-embed-text", embed_fn=fake_embed)

    result = collection.get(ids=collection.get()["ids"])
    assert result["documents"] == ["1. Award 1 mark"]
    assert result["metadatas"][0]["subject"] == "mathaa"


def test_upsert_chunks_noop_on_empty(tmp_path: Path) -> None:
    collection = get_collection(tmp_path)
    upsert_chunks(collection, [], model="nomic-embed-text")
    assert collection.count() == 0
