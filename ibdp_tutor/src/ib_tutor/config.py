"""Load config.toml: model names, chunk size, top-k, sources/data paths."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    generation_model: str = "qwen2.5:7b-instruct"
    embed_model: str = "nomic-embed-text"
    chunk_size: int = 512
    chunk_overlap: int = 64
    top_k: int = 8
    sources_dir: Path = Path("sources")
    data_dir: Path = Path("data")


def load_config(path: Path = Path("config.toml")) -> Config:
    if not path.exists():
        return Config()
    with path.open("rb") as f:
        data = tomllib.load(f)
    ollama = data.get("ollama", {})
    chunking = data.get("chunking", {})
    retrieval = data.get("retrieval", {})
    paths = data.get("paths", {})
    return Config(
        generation_model=ollama.get("generation_model", Config.generation_model),
        embed_model=ollama.get("embed_model", Config.embed_model),
        chunk_size=chunking.get("size", Config.chunk_size),
        chunk_overlap=chunking.get("overlap", Config.chunk_overlap),
        top_k=retrieval.get("top_k", Config.top_k),
        sources_dir=Path(paths.get("sources", "sources")),
        data_dir=Path(paths.get("data", "data")),
    )
