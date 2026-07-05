"""Typer CLI entry point for ib-tutor. Wires the library modules to subcommands."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import typer
from rich.console import Console

import ib_tutor.store as store
from ib_tutor.ask import ask as ask_answer
from ib_tutor.config import Config, load_config
from ib_tutor.ingest import (
    IngestError,
    build_parsed_meta,
    chunk_document,
    extract_pages,
    parse_filename,
    prompt_missing_fields,
)
from ib_tutor.mark import (
    GradingParseError,
    QuestionMismatch,
    QuestionNotFound,
    grade,
    render_mark_result,
)
from ib_tutor.quiz import generate_quiz
from ib_tutor.retrieve import NoMatchingChunks, normalize_filters
from ib_tutor.stats import get_db, record_attempt, render_stats, subject_stats, weak_topics

app = typer.Typer()


@app.callback()
def _main() -> None:
    """ib-tutor: terminal RAG study assistant for IB Diploma materials."""
    # Windows consoles/pipes often default stdout/stderr to a non-UTF-8 codepage
    # (e.g. cp1252), which can't encode the ✓/✗/~ symbols in render_mark_result.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper) and stream.encoding.lower() != "utf-8":
            stream.reconfigure(encoding="utf-8", errors="replace")


def _config() -> Config:
    return load_config(Path("config.toml"))


def _collect_targets(path: Path | None, cfg: Config) -> list[Path]:
    target = path if path is not None else cfg.sources_dir
    if target.is_dir():
        return sorted(target.glob("*.pdf")) + sorted(target.glob("*.md"))
    if target.is_file():
        return [target]
    typer.secho(f"No such file or directory: {target}", fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


@app.command("ingest")
def ingest(
    path: Path | None = typer.Argument(
        None, help="File or directory to ingest; defaults to config's sources_dir"
    ),
) -> None:
    cfg = _config()
    files = _collect_targets(path, cfg)

    collection = store.get_collection(cfg.data_dir)
    had_failure = False
    for file in files:
        try:
            fields, missing = parse_filename(file.name)
            had_to_prompt = bool(missing)
            if missing:
                fields = prompt_missing_fields(fields, missing)
            meta = build_parsed_meta(fields, had_to_prompt)
            pages = extract_pages(file)
            chunks = chunk_document(
                pages, meta, file.name, size=cfg.chunk_size, overlap=cfg.chunk_overlap
            )
            store.upsert_chunks(
                collection, chunks, cfg.embed_model, embed_fn=store.embed_texts
            )
            typer.echo(f"{file.name}: {len(chunks)} chunks ingested")
        except IngestError as e:
            typer.secho(str(e), fg=typer.colors.RED, err=True)
            had_failure = True
        except store.OllamaUnavailable as e:
            typer.secho(str(e), fg=typer.colors.RED, err=True)
            raise typer.Exit(1) from e

    if had_failure:
        raise typer.Exit(1)


@app.command("ask")
def ask_cmd(
    question: str,
    subject: str | None = typer.Option(None),
    type: str | None = typer.Option(None),
    topic: str | None = typer.Option(None),
    year: int | None = typer.Option(None),
    paper: str | None = typer.Option(None),
    level: str | None = typer.Option(None),
    tz: str | None = typer.Option(None),
) -> None:
    cfg = _config()
    filters = normalize_filters(
        subject=subject, type=type, topic=topic, year=year, paper=paper, level=level, tz=tz
    )
    collection = store.get_collection(cfg.data_dir)
    try:
        answer = ask_answer(
            collection, question, cfg, embed_fn=store.embed_texts, filters=filters
        )
        typer.echo(answer)
    except (store.OllamaUnavailable, NoMatchingChunks) as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e


@app.command("mark")
def mark_cmd(
    question_id: str,
    answer: str | None = typer.Option(None, help="Answer text; if omitted, prompts interactively"),
    subject: str | None = typer.Option(None),
    topic: str | None = typer.Option(None),
) -> None:
    if answer is None:
        answer = typer.prompt("Your answer")

    cfg = _config()
    filters = normalize_filters(subject=subject, topic=topic)
    collection = store.get_collection(cfg.data_dir)
    try:
        result = grade(answer, question_id, collection, cfg.generation_model, filters=filters)
    except (QuestionNotFound, QuestionMismatch, GradingParseError, store.OllamaUnavailable) as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e

    typer.echo(render_mark_result(result))
    conn = get_db(cfg.data_dir / "attempts.sqlite")
    record_attempt(
        conn,
        str(filters.get("subject", "")),
        str(filters.get("topic", "")),
        question_id,
        result.total,
        result.available,
    )


@app.command("quiz")
def quiz_cmd(
    n: int = typer.Option(5, help="Number of questions"),
    subject: str | None = typer.Option(None),
    topic: str | None = typer.Option(None),
    type: str | None = typer.Option(None),
    year: int | None = typer.Option(None),
    paper: str | None = typer.Option(None),
    level: str | None = typer.Option(None),
    tz: str | None = typer.Option(None),
) -> None:
    cfg = _config()
    filters = normalize_filters(
        subject=subject, topic=topic, type=type, year=year, paper=paper, level=level, tz=tz
    )
    collection = store.get_collection(cfg.data_dir)
    items = generate_quiz(collection, n, filters=filters)

    if not items:
        typer.echo("No matching questions found.")
        return

    conn = get_db(cfg.data_dir / "attempts.sqlite")
    for item in items:
        typer.echo(item.text)
        answer = typer.prompt("Your answer")
        try:
            result = grade(
                answer, item.question_id, collection, cfg.generation_model, filters=filters
            )
        except (QuestionNotFound, QuestionMismatch, GradingParseError, store.OllamaUnavailable) as e:
            typer.secho(str(e), fg=typer.colors.RED, err=True)
            continue

        typer.echo(render_mark_result(result))
        record_attempt(
            conn,
            str(filters.get("subject", "")),
            str(filters.get("topic", "")),
            item.question_id,
            result.total,
            result.available,
        )


@app.command("stats")
def stats_cmd(subject: str) -> None:
    cfg = _config()
    conn = get_db(cfg.data_dir / "attempts.sqlite")
    subj = str(normalize_filters(subject=subject).get("subject", subject))
    stats = subject_stats(conn, subj)
    weak = weak_topics(conn, subj)
    Console().print(render_stats(stats, weak))
