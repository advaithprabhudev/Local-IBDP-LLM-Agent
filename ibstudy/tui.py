"""Textual app shell: dashboard, deck browser, ingest triage, and analytics screens."""

import sqlite3
from datetime import datetime, timezone

import plotext as plt
from rich.table import Table
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Static

from ibstudy import db
from ibstudy.analytics import CardRow, ReviewRow, compute_subject_stats
from ibstudy.ingest import CardCandidate, normalized_front_hash
from ibstudy.review import ReviewScreen, fetch_due_cards


def _due_counts_table(conn) -> Table:
    now = datetime.now(timezone.utc).isoformat()
    table = Table(title="Due Cards by Subject")
    table.add_column("Subject")
    table.add_column("Due", justify="right")
    table.add_column("Total", justify="right")
    for subject in db.SUBJECTS:
        due = conn.execute(
            "SELECT COUNT(*) AS n FROM cards WHERE subject = ? AND due_at_utc <= ?",
            (subject, now),
        ).fetchone()["n"]
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM cards WHERE subject = ?", (subject,)
        ).fetchone()["n"]
        table.add_row(subject, str(due), str(total))
    return table


class DashboardScreen(Screen):
    BINDINGS = [
        Binding("r", "start_review", "Review due"),
        Binding("d", "open_decks", "Decks"),
        Binding("a", "open_analytics", "Analytics"),
        Binding("ctrl+c", "app.quit", "Quit"),
    ]

    def __init__(self, conn):
        super().__init__()
        self.conn = conn

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="due_table")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#due_table", Static).update(_due_counts_table(self.conn))

    def action_start_review(self) -> None:
        cards = fetch_due_cards(self.conn)
        self.app.push_screen(ReviewScreen(self.conn, cards))

    def action_open_decks(self) -> None:
        self.app.push_screen(DeckBrowserScreen(self.conn))

    def action_open_analytics(self) -> None:
        self.app.push_screen(AnalyticsScreen(self.conn))


class DeckBrowserScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def __init__(self, conn):
        super().__init__()
        self.conn = conn

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="deck_table")
        yield Footer()

    def on_mount(self) -> None:
        table = Table(title="All Cards")
        table.add_column("Subject")
        table.add_column("Front")
        table.add_column("Topic")
        table.add_column("Due")
        rows = self.conn.execute(
            "SELECT subject, front, topic, due_at_utc FROM cards ORDER BY subject, due_at_utc"
        ).fetchall()
        for row in rows:
            table.add_row(row["subject"], row["front"][:60], row["topic"] or "", row["due_at_utc"][:10])
        self.query_one("#deck_table", Static).update(table)


def _load_subject_stats(conn, subject: str):
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
    return compute_subject_stats(subject, card_rows, review_rows)


class AnalyticsScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def __init__(self, conn, subject: str | None = None):
        super().__init__()
        self.conn = conn
        self.subject = subject

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="analytics_body")
        yield Footer()

    def on_mount(self) -> None:
        subjects = [self.subject] if self.subject else list(db.SUBJECTS)
        lines = []
        for subject in subjects:
            stats = _load_subject_stats(self.conn, subject)
            lines.append(
                f"{subject}: total={stats.total} mature={stats.mature} young={stats.young} "
                f"new={stats.new} avg_ef={stats.avg_ef} retention_7d={stats.retention_7d} "
                f"retention_30d={stats.retention_30d} reviews/day={stats.reviews_per_day:.2f}"
            )
            plt.clear_figure()
            plt.bar(list(range(1, 15)), stats.due_forecast)
            plt.title(f"{subject}: 14-day due forecast")
            plt.plotsize(60, 12)
            lines.append(plt.build())
        self.query_one("#analytics_body", Static).update("\n\n".join(lines))


class TriageScreen(Screen):
    """Accept/edit/skip unstructured card candidates before they're written to the DB."""

    BINDINGS = [
        Binding("a", "accept", "Accept"),
        Binding("s", "skip", "Skip"),
        Binding("escape", "app.pop_screen", "Done"),
    ]

    def __init__(self, conn, candidates: list[CardCandidate], subject: str, on_done=None):
        super().__init__()
        self.conn = conn
        self.candidates = candidates
        self.subject = subject
        self.index = 0
        self.on_done = on_done
        self.accepted = 0
        self.skipped = 0

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static("", id="candidate_text"),
            Input(placeholder="Edit front (Enter to confirm)", id="front_input"),
            Input(placeholder="Edit back (Enter to confirm)", id="back_input"),
            Static("", id="triage_progress"),
        )
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_view()

    def current(self) -> CardCandidate | None:
        if self.index >= len(self.candidates):
            return None
        return self.candidates[self.index]

    def _refresh_view(self) -> None:
        c = self.current()
        text = self.query_one("#candidate_text", Static)
        front_input = self.query_one("#front_input", Input)
        back_input = self.query_one("#back_input", Input)
        progress = self.query_one("#triage_progress", Static)
        if c is None:
            text.update("No more candidates. Press escape to return.")
            front_input.display = False
            back_input.display = False
        else:
            text.update(f"Source: {c.source_file}")
            front_input.value = c.front
            back_input.value = c.back
        progress.update(
            f"{self.index}/{len(self.candidates)} | accepted={self.accepted} skipped={self.skipped}"
        )

    def action_accept(self) -> None:
        c = self.current()
        if c is None:
            return
        front = self.query_one("#front_input", Input).value.strip()
        back = self.query_one("#back_input", Input).value.strip()
        insert_card(self.conn, front, back, self.subject, None, c.source_file)
        self.accepted += 1
        self._advance()

    def action_skip(self) -> None:
        if self.current() is None:
            return
        self.skipped += 1
        self._advance()

    def _advance(self) -> None:
        self.index += 1
        self._refresh_view()
        if self.current() is None and self.on_done:
            self.on_done(self.accepted, self.skipped)


def insert_card(conn, front: str, back: str, subject: str, topic: str | None, source_file: str) -> bool:
    """Insert one card, deduped by (subject, front_hash). Returns True if inserted."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            "INSERT INTO cards (front, back, subject, topic, source_file, front_hash, "
            "created_at_utc, ef, repetitions, interval_days, due_at_utc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 2.5, 0, 0, ?)",
            (front, back, subject, topic, source_file, normalized_front_hash(front), now, now),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


class IBStudyApp(App):
    def __init__(self, conn):
        super().__init__()
        self.conn = conn

    def on_mount(self) -> None:
        self.push_screen(DashboardScreen(self.conn))
