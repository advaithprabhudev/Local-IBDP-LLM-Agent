"""Embedding (via Ollama) and persistence (ChromaDB) for chunks."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Protocol, cast

import chromadb
import ollama

from ib_tutor.ingest import Chunk


class OllamaUnavailable(RuntimeError):
    """Raised when Ollama isn't reachable or the required model isn't pulled."""


class EmbedClient(Protocol):
    def embeddings(self, model: str, prompt: str) -> dict[str, Any]: ...


def embed_texts(
    texts: list[str], model: str, client: EmbedClient | None = None
) -> list[list[float]]:
    resolved_client: EmbedClient = client or cast(EmbedClient, ollama.Client())
    try:
        responses = [resolved_client.embeddings(model=model, prompt=t) for t in texts]
    except (ConnectionError, ollama.ResponseError) as e:
        raise OllamaUnavailable(
            f"Can't reach Ollama or model '{model}' isn't pulled — "
            f"run `ollama serve` and `ollama pull {model}`."
        ) from e
    try:
        return [r["embedding"] for r in responses]
    except KeyError as e:
        raise OllamaUnavailable(f"Ollama returned an unexpected response missing {e}") from e


def get_collection(persist_dir: Path, name: str = "ib_tutor") -> chromadb.Collection:
    persist_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(persist_dir))
    return client.get_or_create_collection(name)


def _chunk_id(chunk: Chunk) -> str:
    m = chunk.metadata
    digest = hashlib.sha1(chunk.text.encode("utf-8")).hexdigest()[:8]
    return f"{m['filename']}:{m['page']}:{m['question_id']}:{digest}"


def upsert_chunks(
    collection: chromadb.Collection,
    chunks: list[Chunk],
    model: str,
    embed_fn: Any = embed_texts,
) -> None:
    if not chunks:
        return
    texts = [c.text for c in chunks]
    embeddings = embed_fn(texts, model)
    collection.upsert(
        ids=[_chunk_id(c) for c in chunks],
        embeddings=embeddings,
        documents=texts,
        metadatas=[c.metadata for c in chunks],
    )
