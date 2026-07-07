# Local IBDP LLM Agent

Monorepo of three offline, terminal-only tools built around a local Ollama
LLM — no cloud calls, no browser. Each is an independent `uv` project.

| Project | What it does | Command |
|---|---|---|
| [`ibdp_tutor`](ibdp_tutor) | RAG study assistant over IB past papers/markschemes/textbooks | `ib-tutor` |
| [`glm_agent`](glm_agent) | Plain local chat CLI, fallback when `ib-tutor`'s model/pipeline isn't usable | `glm-agent` |
| [`ibstudy`](ibstudy) | SM-2 spaced-repetition flashcard app (no LLM) | `ibstudy` |

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com), running locally

## Setup

Each project has its own environment and lockfile — `cd` into it and sync.

### ibdp_tutor (primary RAG tutor)

```bash
cd ibdp_tutor
ollama pull glm4:9b
ollama pull nomic-embed-text
uv sync
uv run ib-tutor ingest    # drop source PDFs/MD into sources/ first
uv run ib-tutor ask "your question"
```

Config (model, chunk size, top-k, paths) lives in `ibdp_tutor/config.toml`.
Subcommands: `ingest`, `ask`, `quiz`, `mark`, `stats`.

### glm_agent (fallback chat)

```bash
cd glm_agent
ollama pull glm4:9b
uv sync
uv run glm-agent chat
```

Override the model with `--model` or `GLM_AGENT_MODEL` (e.g. `glm-4.7-flash:latest`).
Type `exit`/`quit` or Ctrl+C to leave the session.

### ibstudy (flashcards, no LLM)

```bash
cd ibstudy
uv sync
uv run ibstudy
```

## Notes

- `sources/` and `data/` under `ibdp_tutor` are gitignored — they hold your
  personal study material and the ChromaDB/SQLite state.
- If Ollama isn't running or a model isn't pulled, each tool fails with a
  single actionable message rather than crashing.
- Still working on improving the model, and responses
  
