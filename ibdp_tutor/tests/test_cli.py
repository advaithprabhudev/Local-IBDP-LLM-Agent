import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import ib_tutor.ask as ask_module
import ib_tutor.cli as cli
import ib_tutor.mark as mark_module
from ib_tutor.config import Config
from ib_tutor.ingest import Chunk, IngestError
from ib_tutor.store import get_collection, upsert_chunks

runner = CliRunner()


def fake_embed(texts: list[str], model: str) -> list[list[float]]:
    return [[1.0 if "momentum" in t.lower() else 0.0] for t in texts]


def _patch_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Config:
    cfg = Config(data_dir=tmp_path / "data", sources_dir=tmp_path / "sources")
    monkeypatch.setattr(cli, "_config", lambda: cfg)
    monkeypatch.setattr("ib_tutor.store.embed_texts", fake_embed)
    return cfg


def test_ingest_single_parseable_md_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = _patch_config(monkeypatch, tmp_path)
    md = tmp_path / "physics_pp_2023_may_p1_sl.md"
    md.write_text("1. Momentum is conserved in an elastic collision.")

    result = runner.invoke(cli.app, ["ingest", str(md)])

    assert result.exit_code == 0, result.output
    assert "chunks ingested" in result.output

    from ib_tutor.store import get_collection

    collection = get_collection(cfg.data_dir)
    got = collection.get()
    assert len(got["ids"]) >= 1
    assert any("Momentum" in doc for doc in got["documents"])


def test_ingest_unparseable_filename_prompts_for_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_config(monkeypatch, tmp_path)
    md = tmp_path / "randomfile.md"
    md.write_text("Some notes content over here.")

    # missing == ["subject", "type"]; type "notes" then requires year/session/paper/level.
    answers = "physics\nnotes\n2023\nmay\np1\nsl\n"
    result = runner.invoke(cli.app, ["ingest", str(md)], input=answers)

    assert result.exit_code == 0, result.output
    assert "chunks ingested" in result.output


def test_ingest_error_prints_red_and_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_config(monkeypatch, tmp_path)
    md = tmp_path / "physics_pp_2023_may_p1_sl.md"
    md.write_text("1. Momentum is conserved.")

    def boom(fields: dict[str, str], had_to_prompt: bool) -> Any:
        raise IngestError("invalid enum value for field 'level'")

    monkeypatch.setattr(cli, "build_parsed_meta", boom)

    result = runner.invoke(cli.app, ["ingest", str(md)])

    assert result.exit_code == 1
    assert "invalid enum value" in result.output


class FakeChatClient:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    def chat(self, model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
        return {"message": {"content": self.reply}}


def test_ask_retrieves_then_generates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = _patch_config(monkeypatch, tmp_path)
    collection = get_collection(cfg.data_dir)
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

    reply = "Momentum is conserved [physics_pp_2023_may_p1_sl.pdf, p.2]."
    monkeypatch.setattr(ask_module.ollama, "Client", lambda: FakeChatClient(reply))

    result = runner.invoke(cli.app, ["ask", "What is conserved?"])

    assert result.exit_code == 0, result.output
    assert "conserved" in result.output


def test_ask_no_matching_chunks_prints_red_and_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_config(monkeypatch, tmp_path)
    get_collection(tmp_path / "data")  # ensure empty collection exists

    result = runner.invoke(cli.app, ["ask", "What is conserved?"])

    assert result.exit_code == 1
    assert "No chunks match filters" in result.output


GRADING_JSON = json.dumps(
    [
        {"code": "R1", "description": "sign argument", "status": "MISSED", "reason": "no sign argument"},
        {"code": "A1", "description": "conclusion", "status": "HIT", "reason": "stated correctly"},
    ]
)


def _seed_markscheme(collection: Any, question_id: str = "3bii") -> None:
    chunk = Chunk(
        text="(b)(ii) R1 sign argument that f'(x) > 0\nA1 conclusion (strictly increasing)",
        metadata={
            "subject": "mathaa",
            "type": "ms",
            "year": 2023,
            "session": "may",
            "paper": "p1",
            "level": "hl",
            "tz": "",
            "filename": "mathaa_ms_2023_may_p1_hl.pdf",
            "page": 4,
            "question_id": question_id,
            "topic": "",
            "parse_quality": "ok",
        },
    )
    upsert_chunks(collection, [chunk], model="fake", embed_fn=fake_embed)


def test_mark_prompts_for_answer_and_records_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = _patch_config(monkeypatch, tmp_path)
    collection = get_collection(cfg.data_dir)
    _seed_markscheme(collection)
    monkeypatch.setattr(mark_module.ollama, "Client", lambda: FakeChatClient(GRADING_JSON))

    result = runner.invoke(cli.app, ["mark", "3bii"], input="The derivative is positive.\n")

    assert result.exit_code == 0, result.output
    assert "Question 3bii" in result.output
    assert "Total: 1/2" in result.output

    import sqlite3

    conn = sqlite3.connect(cfg.data_dir / "attempts.sqlite")
    rows = conn.execute("SELECT question_id, marks_gained, marks_available FROM attempts").fetchall()
    assert rows == [("3bii", 1, 2)]


def test_mark_records_fractional_marks_for_partial_verdict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression test: a PARTIAL-only verdict earns 0.5 marks (per grade()'s
    half-credit rule). Previously cli.py rounded this to round(0.5) == 0 before
    persisting, silently discarding all earned partial credit from stats.
    """
    cfg = _patch_config(monkeypatch, tmp_path)
    collection = get_collection(cfg.data_dir)
    _seed_markscheme(collection)
    partial_json = json.dumps(
        [{"code": "R1", "description": "sign argument", "status": "PARTIAL", "reason": "incomplete"}]
    )
    monkeypatch.setattr(mark_module.ollama, "Client", lambda: FakeChatClient(partial_json))

    result = runner.invoke(cli.app, ["mark", "3bii"], input="The derivative is positive.\n")

    assert result.exit_code == 0, result.output
    assert "Total: 0.5/1" in result.output

    import sqlite3

    conn = sqlite3.connect(cfg.data_dir / "attempts.sqlite")
    rows = conn.execute("SELECT question_id, marks_gained, marks_available FROM attempts").fetchall()
    assert rows == [("3bii", 0.5, 1)]


def test_mark_with_answer_option_does_not_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = _patch_config(monkeypatch, tmp_path)
    collection = get_collection(cfg.data_dir)
    _seed_markscheme(collection)
    monkeypatch.setattr(mark_module.ollama, "Client", lambda: FakeChatClient(GRADING_JSON))

    result = runner.invoke(cli.app, ["mark", "3bii", "--answer", "The derivative is positive."])

    assert result.exit_code == 0, result.output
    assert "Total: 1/2" in result.output


def _seed_quiz_questions(collection: Any) -> None:
    def make_chunk(text: str, doc_type: str, question_id: str, filename: str, page: int) -> Chunk:
        return Chunk(
            text=text,
            metadata={
                "subject": "physics",
                "type": doc_type,
                "year": 2022,
                "session": "nov",
                "paper": "p2",
                "level": "sl",
                "tz": "",
                "filename": filename,
                "page": page,
                "question_id": question_id,
                "topic": "",
                "parse_quality": "ok",
            },
        )

    chunks = [
        make_chunk("1. State the units of momentum.", "pp", "1", "physics_pp_2022_nov_p2_sl.pdf", 1),
        make_chunk("M1 correct unit kg m s-1", "ms", "1", "physics_ms_2022_nov_p2_sl.pdf", 1),
        make_chunk("2. Calculate the acceleration.", "pp", "2", "physics_pp_2022_nov_p2_sl.pdf", 2),
        make_chunk("M1 correct value 9.8", "ms", "2", "physics_ms_2022_nov_p2_sl.pdf", 2),
    ]
    upsert_chunks(collection, chunks, model="fake", embed_fn=fake_embed)


def test_mark_records_attempt_under_canonical_subject_for_alias_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression test: mark --subject "Physics" (non-canonical case) must record
    the attempt under the normalized subject "physics" so that `stats physics`
    finds it. Previously record_attempt() was called with the raw, un-normalized
    subject string, so the attempt was stored as "Physics" and stats (which
    normalizes its own lookup) silently found nothing.
    """
    cfg = _patch_config(monkeypatch, tmp_path)
    collection = get_collection(cfg.data_dir)
    chunk = Chunk(
        text="(b)(ii) R1 sign argument that f'(x) > 0\nA1 conclusion (strictly increasing)",
        metadata={
            "subject": "physics",
            "type": "ms",
            "year": 2023,
            "session": "may",
            "paper": "p1",
            "level": "sl",
            "tz": "",
            "filename": "physics_ms_2023_may_p1_sl.pdf",
            "page": 4,
            "question_id": "3bii",
            "topic": "",
            "parse_quality": "ok",
        },
    )
    upsert_chunks(collection, [chunk], model="fake", embed_fn=fake_embed)
    monkeypatch.setattr(mark_module.ollama, "Client", lambda: FakeChatClient(GRADING_JSON))

    result = runner.invoke(
        cli.app,
        ["mark", "3bii", "--subject", "Physics", "--answer", "The derivative is positive."],
    )

    assert result.exit_code == 0, result.output

    stats_result = runner.invoke(cli.app, ["stats", "physics"])

    assert stats_result.exit_code == 0, stats_result.output
    assert "1/2" in stats_result.output


def test_quiz_prompts_twice_and_records_two_attempts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = _patch_config(monkeypatch, tmp_path)
    collection = get_collection(cfg.data_dir)
    _seed_quiz_questions(collection)
    reply = json.dumps(
        [{"code": "M1", "description": "correct value", "status": "HIT", "reason": "correct"}]
    )
    monkeypatch.setattr(mark_module.ollama, "Client", lambda: FakeChatClient(reply))

    result = runner.invoke(cli.app, ["quiz", "--n", "2"], input="ans1\nans2\n")

    assert result.exit_code == 0, result.output
    assert result.output.count("Total: 1/1") == 2

    import sqlite3

    conn = sqlite3.connect(cfg.data_dir / "attempts.sqlite")
    rows = conn.execute("SELECT question_id FROM attempts").fetchall()
    assert len(rows) == 2


def test_quiz_no_matching_questions_prints_message_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = _patch_config(monkeypatch, tmp_path)
    get_collection(cfg.data_dir)  # empty collection

    result = runner.invoke(cli.app, ["quiz"])

    assert result.exit_code == 0, result.output
    assert "no matching questions" in result.output.lower()


def test_stats_prints_table_with_aggregated_marks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from ib_tutor.stats import get_db, record_attempt

    cfg = _patch_config(monkeypatch, tmp_path)
    conn = get_db(cfg.data_dir / "attempts.sqlite")
    record_attempt(conn, "physics", "mechanics", "1", 1, 2)
    record_attempt(conn, "physics", "mechanics", "2", 2, 2)

    result = runner.invoke(cli.app, ["stats", "physics"])

    assert result.exit_code == 0, result.output
    assert "3/4" in result.output


def test_stats_for_subject_with_no_attempts_prints_zero_counts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_config(monkeypatch, tmp_path)

    result = runner.invoke(cli.app, ["stats", "physics"])

    assert result.exit_code == 0, result.output
    assert "0" in result.output
