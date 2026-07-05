# CLAUDE.md — ib-tutor

Terminal-only RAG study assistant for IB Diploma materials (past papers, markschemes, textbooks). Local LLM via Ollama. No browser, no GUI, no cloud calls.

## Architecture (fixed — do not redesign)

```
sources/ (PDF/MD) → ingest (PyMuPDF) → chunk → embed (ChromaDB) → hybrid retrieve (dense + BM25, RRF, k=8) → Ollama generate
```

Subcommands: `ingest`, `ask`, `quiz`, `mark`, `stats`.

Module build order: `ingestion → store → retrieval → ask → mark → quiz → stats`. Do not start module N+1 until module N's tests pass.

## Stack (locked)

- Python 3.11+, fully typed. `ruff check` and `mypy --strict` must pass before any commit.
- Dependencies: PyMuPDF, chromadb, sentence-transformers (or `nomic-embed-text` via Ollama), rank_bm25, typer, rich. SQLite via stdlib for attempt tracking.
- Default generation model: `qwen2.5:7b-instruct`, configurable in `config.toml` (also: chunk size, top-k, sources path).
- Forbidden: web frameworks, GUI libs, cloud APIs, LangChain/LlamaIndex (build retrieval directly — no framework abstraction).

## Development discipline

- **Tests after each module.** Every module ships with its pytest file in the same PR/commit. Retrieval gets seeded-corpus tests: known-relevant chunk must appear in top-k.
- Before writing any module, state the module's public interface (function signatures) in ≤6 lines.
- No abstraction layers not required by the current module. No speculative generality.
- Graceful failure: if Ollama isn't running, exit with one actionable line, non-zero code.
- Scanned/image-only PDF pages: skip with a warning, never crash.

## Grounding rules (generation)

The system prompt sent to Ollama must enforce:
1. Answer only from retrieved context.
2. Every factual claim cites `[filename, page]`.
3. Use IB command-term-aligned language.
4. If context is insufficient: say "not in sources" — never guess.

## Project skills — consult before relevant work

- `.claude/skills/markscheme-marking/` — MANDATORY before writing or modifying any code in the `mark` or `quiz` subcommands, markscheme chunking, or grading logic.
- `.claude/skills/ib-metadata-conventions/` — MANDATORY before writing ingestion, filename parsing, metadata schemas, or subject/topic filters.

## v1 scope

Subjects: **Mathematics AA HL** and **Physics SL** only. Metadata schema must be extensible to the remaining four IB subjects but do not implement their conventions yet.

Out of scope entirely: fine-tuning (LoRA/QLoRA), flashcard UI, spaced repetition. Do not propose them.

## Data layout

```
ib-tutor/
├── sources/          # user drops PDFs/MD here (gitignored)
├── data/             # chromadb persist dir + attempts.sqlite (gitignored)
├── config.toml
├── src/ib_tutor/
└── tests/
```
