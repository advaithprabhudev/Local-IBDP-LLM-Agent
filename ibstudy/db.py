"""SQLite schema, migrations, and connection management. No business logic here."""

import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path("./data/study.db")

SUBJECTS = (
    "Math AA HL",
    "Economics HL",
    "CS HL",
    "Physics SL",
    "English LL SL",
    "Spanish ab initio",
)

SCHEMA_VERSION = 1

_MIGRATIONS: dict[int, str] = {
    1: """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            front TEXT NOT NULL,
            back TEXT NOT NULL,
            subject TEXT NOT NULL,
            topic TEXT,
            source_file TEXT,
            front_hash TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            ef REAL NOT NULL DEFAULT 2.5,
            repetitions INTEGER NOT NULL DEFAULT 0,
            interval_days INTEGER NOT NULL DEFAULT 0,
            due_at_utc TEXT NOT NULL,
            UNIQUE (subject, front_hash)
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id INTEGER NOT NULL REFERENCES cards(id),
            reviewed_at_utc TEXT NOT NULL,
            quality INTEGER NOT NULL,
            ef_after REAL NOT NULL,
            interval_days_after INTEGER NOT NULL,
            repetitions_after INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_cards_subject ON cards(subject);
        CREATE INDEX IF NOT EXISTS idx_cards_due ON cards(due_at_utc);
        CREATE INDEX IF NOT EXISTS idx_reviews_card ON reviews(card_id);
        CREATE INDEX IF NOT EXISTS idx_reviews_time ON reviews(reviewed_at_utc);
    """,
}


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a connection to the study database, creating/migrating it if needed."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """Apply any migrations newer than the database's current schema_version. Idempotent."""
    has_version_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    current = 0
    if has_version_table:
        row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        current = row["v"] or 0

    for version in sorted(_MIGRATIONS):
        if version <= current:
            continue
        conn.executescript(_MIGRATIONS[version])
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
        conn.commit()
