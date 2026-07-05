"""Attempt tracking (SQLite) and per-subject analytics."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rich.table import Table

SCHEMA = """
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    subject TEXT NOT NULL,
    topic TEXT NOT NULL,
    question_id TEXT NOT NULL,
    marks_gained REAL NOT NULL,
    marks_available INTEGER NOT NULL
)
"""


def get_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(SCHEMA)
    conn.commit()
    return conn


def record_attempt(
    conn: sqlite3.Connection,
    subject: str,
    topic: str,
    question_id: str,
    marks_gained: float,
    marks_available: int,
) -> None:
    conn.execute(
        "INSERT INTO attempts (timestamp, subject, topic, question_id, marks_gained, marks_available) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (datetime.now(UTC).isoformat(), subject, topic, question_id, marks_gained, marks_available),
    )
    conn.commit()


@dataclass
class SubjectStats:
    subject: str
    questions_attempted: int
    marks_gained: float
    marks_available: int


@dataclass
class TopicStat:
    topic: str
    marks_gained: float
    marks_available: int

    @property
    def percentage(self) -> float:
        return 100.0 * self.marks_gained / self.marks_available if self.marks_available else 0.0


def subject_stats(conn: sqlite3.Connection, subject: str) -> SubjectStats:
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(marks_gained), 0), COALESCE(SUM(marks_available), 0) "
        "FROM attempts WHERE subject = ?",
        (subject,),
    ).fetchone()
    return SubjectStats(subject=subject, questions_attempted=row[0], marks_gained=row[1], marks_available=row[2])


def weak_topics(conn: sqlite3.Connection, subject: str, limit: int = 5) -> list[TopicStat]:
    rows = conn.execute(
        "SELECT topic, SUM(marks_gained), SUM(marks_available) FROM attempts "
        "WHERE subject = ? AND topic != '' GROUP BY topic",
        (subject,),
    ).fetchall()
    stats = [TopicStat(topic=r[0], marks_gained=r[1], marks_available=r[2]) for r in rows]
    stats.sort(key=lambda s: s.percentage)
    return stats[:limit]


def render_stats(stats: SubjectStats, weak: list[TopicStat]) -> Table:
    table = Table(title=f"{stats.subject} — stats")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("Questions attempted", str(stats.questions_attempted))
    table.add_row(
        "Marks",
        f"{stats.marks_gained:g}/{stats.marks_available}"
        + (f" ({100.0 * stats.marks_gained / stats.marks_available:.0f}%)" if stats.marks_available else ""),
    )
    for t in weak:
        table.add_row(f"Weak topic: {t.topic}", f"{t.marks_gained:g}/{t.marks_available} ({t.percentage:.0f}%)")
    return table
