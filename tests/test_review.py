from pathlib import Path

from ibstudy import db
from ibstudy.review import fetch_due_cards, persist_grade
from ibstudy.srs import ScheduleState, grade


def make_conn(tmp_path: Path):
    return db.connect(tmp_path / "test.db")


def insert_test_card(conn, due_at_utc="2020-01-01T00:00:00+00:00"):
    conn.execute(
        "INSERT INTO cards (front, back, subject, topic, source_file, front_hash, "
        "created_at_utc, ef, repetitions, interval_days, due_at_utc) "
        "VALUES ('Q1', 'A1', 'Economics HL', NULL, 'x.md', 'hash1', ?, 2.5, 0, 0, ?)",
        (due_at_utc, due_at_utc),
    )
    conn.commit()
    return conn.execute("SELECT * FROM cards").fetchone()["id"]


def test_review_session_persists_and_reschedules_q4_streak(tmp_path):
    conn = make_conn(tmp_path)
    card_id = insert_test_card(conn)

    due = fetch_due_cards(conn)
    assert len(due) == 1
    assert due[0]["id"] == card_id

    state = ScheduleState(ef=2.5, repetitions=0, interval_days=0)
    expected_intervals = [1, 6, 15]

    for expected_interval in expected_intervals:
        state = grade(state, 4)
        persist_grade(conn, card_id, 4, state)

        row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        assert row["interval_days"] == expected_interval
        assert row["ef"] == 2.5
        assert row["due_at_utc"] > "2020-01-01"

    reviews = conn.execute(
        "SELECT * FROM reviews WHERE card_id = ? ORDER BY id", (card_id,)
    ).fetchall()
    assert [r["interval_days_after"] for r in reviews] == expected_intervals
    assert all(r["quality"] == 4 for r in reviews)


def test_fetch_due_cards_excludes_not_yet_due(tmp_path):
    conn = make_conn(tmp_path)
    insert_test_card(conn, due_at_utc="2099-01-01T00:00:00+00:00")
    assert fetch_due_cards(conn) == []
