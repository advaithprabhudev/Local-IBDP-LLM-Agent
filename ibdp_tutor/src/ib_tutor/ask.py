"""Grounded Q&A: retrieve context, generate a cited answer via Ollama."""

from __future__ import annotations

from typing import Any, Protocol, cast

import chromadb
import ollama

from ib_tutor.config import Config
from ib_tutor.retrieve import RetrievedChunk, hybrid_retrieve
from ib_tutor.store import OllamaUnavailable

SYSTEM_PROMPT = """You are an IB Diploma study assistant. Follow these rules strictly:
1. Answer ONLY using the retrieved context below. Never use outside knowledge.
2. Every factual claim must cite its source as [filename, p.N].
3. Use IB command-term-aligned language (state, define, calculate, explain, evaluate, etc.) matching what the question asks for.
4. If the context does not contain enough information to answer, say "Not in sources" instead of guessing.
"""


class ChatClient(Protocol):
    def chat(self, model: str, messages: list[dict[str, str]]) -> dict[str, Any]: ...


def format_context(chunks: list[RetrievedChunk]) -> str:
    blocks = []
    for i, c in enumerate(chunks, start=1):
        filename = c.metadata.get("filename", "unknown")
        page = c.metadata.get("page", "?")
        blocks.append(f"[Source {i}: {filename}, p.{page}]\n{c.text}")
    return "\n\n".join(blocks)


def build_messages(question: str, chunks: list[RetrievedChunk]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Context:\n{format_context(chunks)}\n\nQuestion: {question}",
        },
    ]


def generate_answer(
    question: str,
    chunks: list[RetrievedChunk],
    model: str,
    client: ChatClient | None = None,
) -> str:
    resolved_client: ChatClient = client or cast(ChatClient, ollama.Client())
    try:
        response = resolved_client.chat(model=model, messages=build_messages(question, chunks))
    except Exception as e:
        raise OllamaUnavailable(
            f"Can't reach Ollama or model '{model}' isn't pulled — "
            f"run `ollama serve` and `ollama pull {model}`."
        ) from e
    return str(response["message"]["content"])


def ask(
    collection: chromadb.Collection,
    question: str,
    cfg: Config,
    embed_fn: Any,
    filters: dict[str, str | int] | None = None,
    client: ChatClient | None = None,
) -> str:
    chunks = hybrid_retrieve(
        collection, question, embed_fn, cfg.embed_model, filters=filters, k=cfg.top_k
    )
    return generate_answer(question, chunks, cfg.generation_model, client=client)
