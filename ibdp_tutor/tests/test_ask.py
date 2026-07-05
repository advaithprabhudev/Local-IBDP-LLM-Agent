from pathlib import Path

import pytest

from ib_tutor.ask import ask, build_messages, format_context, generate_answer
from ib_tutor.config import Config
from ib_tutor.ingest import Chunk
from ib_tutor.retrieve import RetrievedChunk
from ib_tutor.store import OllamaUnavailable, get_collection, upsert_chunks


def sample_chunks() -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            text="Momentum is conserved in an elastic collision.",
            metadata={"filename": "physics_pp_2023_may_p1_sl.pdf", "page": 2},
            score=0.9,
        )
    ]


def test_format_context_includes_filename_and_page() -> None:
    ctx = format_context(sample_chunks())
    assert "physics_pp_2023_may_p1_sl.pdf" in ctx
    assert "p.2" in ctx
    assert "Momentum is conserved" in ctx


def test_build_messages_has_system_and_user_roles() -> None:
    messages = build_messages("What is conserved?", sample_chunks())
    assert messages[0]["role"] == "system"
    assert "cite" in messages[0]["content"].lower()
    assert messages[1]["role"] == "user"
    assert "What is conserved?" in messages[1]["content"]


class FakeChatClient:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.last_messages: list[dict[str, str]] | None = None

    def chat(self, model: str, messages: list[dict[str, str]]) -> dict:
        self.last_messages = messages
        return {"message": {"content": self.reply}}


class BrokenChatClient:
    def chat(self, model: str, messages: list[dict[str, str]]) -> dict:
        raise ConnectionError("no server")


def test_generate_answer_returns_model_reply() -> None:
    client = FakeChatClient("Momentum is conserved [physics_pp_2023_may_p1_sl.pdf, p.2].")
    answer = generate_answer("What is conserved?", sample_chunks(), "qwen2.5:7b-instruct", client=client)
    assert "conserved" in answer
    assert client.last_messages is not None


def test_generate_answer_raises_actionable_error_when_unreachable() -> None:
    with pytest.raises(OllamaUnavailable, match="ollama serve"):
        generate_answer("q", sample_chunks(), "qwen2.5:7b-instruct", client=BrokenChatClient())


def test_ask_retrieves_then_generates(tmp_path: Path) -> None:
    collection = get_collection(tmp_path)

    def fake_embed(texts: list[str], model: str) -> list[list[float]]:
        return [[1.0 if "momentum" in t.lower() else 0.0] for t in texts]

    chunk = Chunk(
        text="Momentum is conserved in an elastic collision.",
        metadata={
            "subject": "physics",
            "type": "pp",
            "year": 2023,
            "session": "may",
            "paper": "p1",
            "level": "sl",
            "tz": "",
            "filename": "physics_pp_2023_may_p1_sl.pdf",
            "page": 2,
            "question_id": "",
            "topic": "",
            "parse_quality": "ok",
        },
    )
    upsert_chunks(collection, [chunk], model="fake", embed_fn=fake_embed)

    client = FakeChatClient("Momentum is conserved [physics_pp_2023_may_p1_sl.pdf, p.2].")
    cfg = Config(top_k=8)
    answer = ask(collection, "What is conserved?", cfg, embed_fn=fake_embed, client=client)
    assert "conserved" in answer
    assert client.last_messages is not None
    assert "physics_pp_2023_may_p1_sl.pdf" in client.last_messages[1]["content"]
