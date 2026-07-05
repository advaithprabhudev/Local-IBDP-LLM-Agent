"""Entry point: `ibstudy` command. Argparse subcommands + bare TUI launch."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from ibstudy import db
from ibstudy.analytics import CardRow, ReviewRow, compute_subject_stats
from ibstudy.ingest import candidates_for_file, iter_supported_files, normalized_front_hash


def _existing_hashes(conn, subject: str) -> set[str]:
    rows = conn.execute("SELECT front_hash FROM cards WHERE subject = ?", (subject,)).fetchall()
    return {r["front_hash"] for r in rows}


def cmd_ingest(args: argparse.Namespace) -> int:
    from ibstudy.tui import insert_card

    conn = db.connect(args.db)
    path = Path(args.path)
    if not path.exists():
        print(f"Path not found: {path}", file=sys.stderr)
        return 1

    subject = args.subject
    if subject is None:
        from rich.prompt import Prompt

        subject = Prompt.ask("Subject", choices=list(db.SUBJECTS))

    files = iter_supported_files(path)
    structured_inserted = 0
    unstructured_pending = []

    for f in files:
        candidates = candidates_for_file(f)
        seen = _existing_hashes(conn, subject)
        for c in candidates:
            h = normalized_front_hash(c.front)
            if h in seen:
                continue
            seen.add(h)
            if c.structured:
                if insert_card(conn, c.front, c.back, subject, args.topic, c.source_file):
                    structured_inserted += 1
            else:
                unstructured_pending.append(c)

    print(f"Inserted {structured_inserted} structured card(s) into '{subject}'.")

    if unstructured_pending:
        if sys.stdin.isatty() and sys.stdout.isatty() and not args.no_triage:
            from textual.app import App

            from ibstudy.tui import TriageScreen

            class TriageApp(App):
                def on_mount(self) -> None:
                    self.push_screen(TriageScreen(conn, unstructured_pending, subject))

            TriageApp().run()
        else:
            print(
                f"{len(unstructured_pending)} unstructured candidate(s) need triage. "
                "Run `ibstudy` interactively to accept/edit/skip them."
            )
    return 0


def cmd_due(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    now = datetime.now(timezone.utc).isoformat()
    for subject in db.SUBJECTS:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM cards WHERE subject = ? AND due_at_utc <= ?",
            (subject, now),
        ).fetchone()["n"]
        print(f"{subject}: {count}")
    return 0


def _subject_stats_dict(conn, subject: str) -> dict:
    card_rows = [
        CardRow(subject=r["subject"], ef=r["ef"], repetitions=r["repetitions"],
                interval_days=r["interval_days"], due_at_utc=r["due_at_utc"])
        for r in conn.execute("SELECT * FROM cards WHERE subject = ?", (subject,)).fetchall()
    ]
    review_rows = [
        ReviewRow(subject=subject, reviewed_at_utc=r["reviewed_at_utc"], quality=r["quality"])
        for r in conn.execute(
            "SELECT reviews.* FROM reviews JOIN cards ON cards.id = reviews.card_id "
            "WHERE cards.subject = ?",
            (subject,),
        ).fetchall()
    ]
    stats = compute_subject_stats(subject, card_rows, review_rows)
    return {
        "subject": stats.subject,
        "total": stats.total,
        "mature": stats.mature,
        "young": stats.young,
        "new": stats.new,
        "retention_7d": stats.retention_7d,
        "retention_30d": stats.retention_30d,
        "avg_ef": stats.avg_ef,
        "reviews_per_day": stats.reviews_per_day,
        "due_forecast": stats.due_forecast,
    }


def cmd_stats(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    subjects = [args.subject] if args.subject else list(db.SUBJECTS)
    results = [_subject_stats_dict(conn, s) for s in subjects]

    if args.json:
        print(json.dumps(results if args.subject is None else results[0]))
        return 0

    from rich.console import Console
    from rich.table import Table

    table = Table(title="Subject Stats")
    for col in ("Subject", "Total", "Mature", "Young", "New", "Ret7d", "Ret30d", "AvgEF", "Rev/day"):
        table.add_column(col)
    for s in results:
        table.add_row(
            s["subject"], str(s["total"]), str(s["mature"]), str(s["young"]), str(s["new"]),
            f"{s['retention_7d']:.2f}" if s["retention_7d"] is not None else "-",
            f"{s['retention_30d']:.2f}" if s["retention_30d"] is not None else "-",
            f"{s['avg_ef']:.2f}" if s["avg_ef"] is not None else "-",
            f"{s['reviews_per_day']:.2f}",
        )
    Console().print(table)
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    from textual.app import App

    from ibstudy.review import ReviewScreen, fetch_due_cards

    conn = db.connect(args.db)
    cards = fetch_due_cards(conn, args.subject)
    if not cards:
        print("No cards due.")
        return 0

    class ReviewApp(App):
        def on_mount(self) -> None:
            self.push_screen(ReviewScreen(conn, cards))

    ReviewApp().run()
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    from ibstudy.tui import IBStudyApp

    conn = db.connect(args.db)
    IBStudyApp(conn).run()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ibstudy")
    parser.add_argument("--db", default=db.DEFAULT_DB_PATH, help="Path to SQLite database")
    parser.set_defaults(func=cmd_dashboard)

    subparsers = parser.add_subparsers(dest="command")

    p_ingest = subparsers.add_parser("ingest", help="Ingest a file or directory of notes")
    p_ingest.add_argument("path")
    p_ingest.add_argument("--subject", choices=db.SUBJECTS, default=None)
    p_ingest.add_argument("--topic", default=None)
    p_ingest.add_argument("--no-triage", action="store_true", help="Skip interactive triage")
    p_ingest.set_defaults(func=cmd_ingest)

    p_due = subparsers.add_parser("due", help="Print due-count per subject")
    p_due.set_defaults(func=cmd_due)

    p_stats = subparsers.add_parser("stats", help="Print per-subject analytics")
    p_stats.add_argument("--subject", choices=db.SUBJECTS, default=None)
    p_stats.add_argument("--json", action="store_true")
    p_stats.set_defaults(func=cmd_stats)

    p_review = subparsers.add_parser("review", help="Start a review session")
    p_review.add_argument("--subject", choices=db.SUBJECTS, default=None)
    p_review.set_defaults(func=cmd_review)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
