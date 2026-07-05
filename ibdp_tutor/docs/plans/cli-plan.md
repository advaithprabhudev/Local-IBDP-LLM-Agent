# Plan: Typer CLI for ib-tutor

## Goal

Wire the 7 already-tested library modules (`ingest`, `store`, `retrieve`, `ask`,
`mark`, `quiz`, `stats`) behind the Typer entry point `pyproject.toml` already
declares (`ib-tutor = "ib_tutor.cli:app"`), so `uv run ib-tutor <subcommand>`
works from a terminal. No library-module logic changes — this plan only adds
`src/ib_tutor/cli.py` and `tests/test_cli.py`.

## Global Constraints

- Python 3.11+. `uv run ruff check` and `uv run mypy --strict` must pass on
  every commit; `uv run pytest` must pass.
- One new source file: `src/ib_tutor/cli.py`, built incrementally across the
  tasks below (each task adds to the same file — expect sequential edits,
  not parallel).
- Load config once per invocation via
  `ib_tutor.config.load_config(Path("config.toml"))`.
- Get the ChromaDB collection via `ib_tutor.store.get_collection(cfg.data_dir)`.
- Any CLI options that become retrieval/grading/quiz filters (subject, type,
  topic, year, paper, level, tz) MUST be passed through
  `ib_tutor.retrieve.normalize_filters(**kwargs)` before being handed to
  `hybrid_retrieve`/`ask`/`grade`/`generate_quiz`/`find_markscheme_chunk` —
  these functions expect already-normalized filters and never normalize
  internally (documented contract in `retrieve.py`). Only pass the kwargs
  that were actually supplied (skip `None` values — `normalize_filters`
  already drops `None`s, so it's safe to pass all of them through unconditionally).
- **Known gotcha — do not rely on `upsert_chunks`'s bound default for
  `embed_fn`.** `store.upsert_chunks(collection, chunks, model, embed_fn=embed_texts)`
  binds its default at `store.py`'s definition time, so
  `monkeypatch.setattr(ib_tutor.store, "embed_texts", fake)` in a test will
  **not** reach a call that relies on that default. `cli.py` must always pass
  `embed_fn=store.embed_texts` explicitly (a module-attribute lookup
  resolved at call time), so patching `ib_tutor.store.embed_texts` in a test
  takes effect. Same reasoning applies anywhere `cli.py` calls
  `hybrid_retrieve`, which has no default and must also be passed
  `embed_fn=store.embed_texts` explicitly.
- Error handling at the CLI boundary: catch `ib_tutor.store.OllamaUnavailable`,
  `ib_tutor.retrieve.NoMatchingChunks`, `ib_tutor.mark.QuestionNotFound`,
  `ib_tutor.mark.QuestionMismatch`, `ib_tutor.mark.GradingParseError`,
  `ib_tutor.ingest.IngestError` at each subcommand's top level. Print
  `str(exc)` via `typer.secho(str(exc), fg=typer.colors.RED, err=True)` and
  `raise typer.Exit(code=1)`. Never let these propagate as raw tracebacks.
- Attempts DB path: `cfg.data_dir / "attempts.sqlite"`.
- Tests use `typer.testing.CliRunner` and the existing `Fake*Client` /
  `tmp_path` + `monkeypatch` pattern already used in `tests/test_ask.py`,
  `tests/test_mark.py`, `tests/test_quiz.py`, `tests/test_store.py` — no real
  Ollama or network calls in tests.
- No web framework, GUI, or cloud API usage (already locked project-wide).

## Task 1: CLI skeleton, config/collection wiring, and `ingest` subcommand

Create `src/ib_tutor/cli.py`:

- `app = typer.Typer()` — this is the object `pyproject.toml`'s
  `ib-tutor = "ib_tutor.cli:app"` entry point resolves.
- A private helper `_config() -> Config` that calls
  `load_config(Path("config.toml"))`.
- `@app.command("ingest")` — signature:
  `def ingest(path: Path | None = typer.Argument(None, help="File or directory to ingest; defaults to config's sources_dir")) -> None`.
  - Resolve the target: if `path` is `None`, use `cfg.sources_dir`. If the
    resolved path is a directory, collect `*.pdf` and `*.md` files directly
    inside it (`sorted(path.glob("*.pdf")) + sorted(path.glob("*.md"))`, not
    recursive). If it's a single file, ingest just that file. If neither
    exists, print a red error and `raise typer.Exit(1)`.
  - Per file: `fields, missing = parse_filename(file.name)`; if `missing`,
    `fields = prompt_missing_fields(fields, missing)` and track
    `had_to_prompt = True`, else `had_to_prompt = False`;
    `meta = build_parsed_meta(fields, had_to_prompt)`;
    `pages = extract_pages(file)`;
    `chunks = chunk_document(pages, meta, file.name, size=cfg.chunk_size, overlap=cfg.chunk_overlap)`;
    `collection = get_collection(cfg.data_dir)` (call once before the loop,
    not per file);
    `upsert_chunks(collection, chunks, cfg.embed_model, embed_fn=store.embed_texts)`
    (see Global Constraints gotcha — must pass `embed_fn` explicitly).
  - Print `f"{file.name}: {len(chunks)} chunks ingested"` per file on success.
  - On `IngestError` for one file: print the error in red and continue to the
    next file; track that at least one failure happened and, after the loop,
    `raise typer.Exit(1)` if any file failed.
  - On `store.OllamaUnavailable`: this will fail identically for every
    remaining file, so print the error and `raise typer.Exit(1)` immediately
    instead of continuing the loop.
  - Import `ib_tutor.store as store` (module import, not
    `from ib_tutor.store import embed_texts`) so the explicit
    `embed_fn=store.embed_texts` lookup happens at call time.

Add `tests/test_cli.py`:
- `runner = CliRunner()` at module scope or per test.
- Test: ingesting a single `.md` file with a fully-parseable filename (e.g.
  `physics_pp_2023_may_p1_sl.md`) and simple question-like content succeeds,
  reports a chunk count, and the chunk ends up queryable in the collection at
  `cfg.data_dir` — monkeypatch `ib_tutor.store.embed_texts` to a
  deterministic fake (same style as `tests/test_ask.py`'s `fake_embed`) and
  point `cfg.data_dir`/`config.toml` at `tmp_path` (write a temp
  `config.toml` there, or monkeypatch `ib_tutor.cli.load_config`/`_config` —
  pick whichever keeps the test simplest and note the choice in the report).
- Test: ingesting a file whose filename is completely unparseable, with
  stdin providing the prompted answers via `CliRunner.invoke(app, [...], input="...\n...")`.
- Test: an `IngestError` (e.g. an invalid enum value not caught by prompting)
  prints a red-flagged message and exits non-zero, without crashing.

Run `uv run pytest tests/test_cli.py -v`, `uv run mypy --strict src`,
`uv run ruff check` before committing.

## Task 2: `ask` subcommand

Add to `src/ib_tutor/cli.py`:

- `@app.command("ask")` — signature:
  `def ask_cmd(question: str, subject: str | None = typer.Option(None), type: str | None = typer.Option(None), topic: str | None = typer.Option(None), year: int | None = typer.Option(None), paper: str | None = typer.Option(None), level: str | None = typer.Option(None), tz: str | None = typer.Option(None)) -> None`.
  - `cfg = _config()`; `filters = normalize_filters(subject=subject, type=type, topic=topic, year=year, paper=paper, level=level, tz=tz)`;
    `collection = get_collection(cfg.data_dir)`;
    `answer = ask(collection, question, cfg, embed_fn=store.embed_texts, filters=filters)`
    (the library function is also named `ask` — import it as
    `from ib_tutor.ask import ask as ask_answer` or call the module
    qualified as `ib_tutor.ask.ask(...)` to avoid shadowing the Typer command
    function `ask_cmd`; pick one and be consistent).
  - Print the answer via `typer.echo(answer)`.
  - Catch `store.OllamaUnavailable` and `retrieve.NoMatchingChunks` per the
    Global Constraints error-handling contract.

Add to `tests/test_cli.py`:
- Test: `ask` with a pre-seeded collection (reuse the ingest-then-query
  pattern from `tests/test_ask.py`'s `test_ask_retrieves_then_generates`,
  but drive it through `CliRunner.invoke`) returns the fake model's answer
  text on stdout. Monkeypatch `ollama.Client` (or however `ask()`/`generate_answer()`
  resolves its `ChatClient` when none is passed — check `ib_tutor/ask.py`) so
  no real network call happens; the CLI command has no way to inject a
  `ChatClient` (unlike the library function's `client` param), so patch
  `ollama.Client` at the module level the same way `tests/test_store.py`
  likely already demonstrates for `embed_texts`'s Ollama client.
- Test: `NoMatchingChunks` on an empty collection prints a red error and
  exits non-zero instead of crashing.

Run `uv run pytest tests/test_cli.py -v`, `uv run mypy --strict src`,
`uv run ruff check` before committing.

## Task 3: `quiz` and `mark` subcommands

Add to `src/ib_tutor/cli.py`:

- `@app.command("mark")` — signature:
  `def mark_cmd(question_id: str, answer: str | None = typer.Option(None, help="Answer text; if omitted, prompts interactively"), subject: str | None = typer.Option(None), topic: str | None = typer.Option(None)) -> None`.
  - If `answer` is `None`, prompt with `typer.prompt("Your answer")`.
  - `cfg = _config()`; `filters = normalize_filters(subject=subject, topic=topic)`;
    `collection = get_collection(cfg.data_dir)`;
    `result = grade(answer, question_id, collection, cfg.generation_model, filters=filters)`
    (import `ib_tutor.mark.grade`; qualify if it collides with anything).
  - Print `render_mark_result(result)` via `typer.echo`.
  - Record the attempt: `conn = get_db(cfg.data_dir / "attempts.sqlite")`;
    `record_attempt(conn, subject or "", topic or "", question_id, round(result.total), result.available)`.
  - Catch `QuestionNotFound`, `QuestionMismatch`, `GradingParseError`,
    `store.OllamaUnavailable` per the error-handling contract.

- `@app.command("quiz")` — signature:
  `def quiz_cmd(n: int = typer.Option(5, help="Number of questions"), subject: str | None = typer.Option(None), topic: str | None = typer.Option(None), type: str | None = typer.Option(None), year: int | None = typer.Option(None), paper: str | None = typer.Option(None), level: str | None = typer.Option(None), tz: str | None = typer.Option(None)) -> None`.
  - `cfg = _config()`;
    `filters = normalize_filters(subject=subject, topic=topic, type=type, year=year, paper=paper, level=level, tz=tz)`;
    `collection = get_collection(cfg.data_dir)`;
    `items = generate_quiz(collection, n, filters=filters)`.
  - If `items` is empty, print a message ("no matching questions") and
    return without error (this is a legitimate empty result, not an
    exception — `generate_quiz` doesn't raise `NoMatchingChunks`).
  - For each item, in order: print `item.text`; prompt
    `answer = typer.prompt("Your answer")`; call
    `grade(answer, item.question_id, collection, cfg.generation_model, filters=filters)`;
    print `render_mark_result(result)`; record the attempt the same way
    `mark_cmd` does (`subject or ""`, `topic or ""`, `item.question_id`,
    `round(result.total)`, `result.available`).
  - Wrap the per-item grading in a try/except for the same exception set as
    `mark_cmd` — on failure for one item, print the error in red and continue
    to the next item (don't abort the whole quiz over one bad grading call).

Add to `tests/test_cli.py`:
- Test: `mark` on a seeded collection with a markscheme chunk (reuse the
  seeding pattern from `tests/test_mark.py`) grades correctly given
  `input=` for the prompted answer, prints the rendered result, and inserts
  one row into `attempts.sqlite` under `cfg.data_dir`.
- Test: `mark` with `--answer` supplied on the command line does not prompt.
- Test: `quiz --n 2` on a seeded collection with two gradeable past-paper
  questions prompts twice (via `input="ans1\nans2\n"`), prints two rendered
  results, and inserts two attempt rows.
- Test: `quiz` when `generate_quiz` returns no items prints a message and
  exits 0.

Run `uv run pytest tests/test_cli.py -v`, `uv run mypy --strict src`,
`uv run ruff check` before committing.

## Task 4: `stats` subcommand

Add to `src/ib_tutor/cli.py`:

- `@app.command("stats")` — signature: `def stats_cmd(subject: str) -> None`.
  - `cfg = _config()`; `conn = get_db(cfg.data_dir / "attempts.sqlite")`;
    `subj = normalize_filters(subject=subject).get("subject", subject)` (stay
    consistent with however `mark`/`quiz` canonicalized `subject` before
    calling `record_attempt`); `stats = subject_stats(conn, subj)`;
    `weak = weak_topics(conn, subj)`; render with
    `rich.console.Console().print(render_stats(stats, weak))`.

Add to `tests/test_cli.py`:
- Test: recording two attempts (directly via `record_attempt`, or via prior
  `mark` calls) then running `stats <subject>` prints a table containing the
  aggregated marks.
- Test: `stats` for a subject with no recorded attempts prints a table with
  zero counts, not an error.

Run the full suite (`uv run pytest`, `uv run mypy --strict src`,
`uv run ruff check`) before committing — this is the last task touching
`cli.py`, so also confirm `uv run ib-tutor --help` lists all five
subcommands (`ingest`, `ask`, `quiz`, `mark`, `stats`) without error (run
manually once, not as an automated test, since it depends on the installed
console-script entry point).
