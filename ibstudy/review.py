"""Textual review session screen: show due cards, reveal, grade via keys 0-5."""

from datetime import datetime, timedelta, timezone

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Static

from ibstudy.srs import ScheduleState, grade


class ReviewScreen(Screen):
    """One review session over a fixed list of due card rows for a subject (or all subjects)."""

    BINDINGS = [
        Binding("space", "reveal", "Reveal"),
        Binding("0", "grade(0)", "0"),
        Binding("1", "grade(1)", "1"),
        Binding("2", "grade(2)", "2"),
        Binding("3", "grade(3)", "3"),
        Binding("4", "grade(4)", "4"),
        Binding("5", "grade(5)", "5"),
        Binding("q", "app.pop_screen", "Quit session"),
    ]

    def __init__(self, conn, cards: list[dict]):
        super().__init__()
        self.conn = conn
        self.cards = cards
        self.index = 0
        self.revealed = False
        self.session_reviewed = 0
        self.session_correct = 0

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("", id="card_text"),
            Static("", id="progress"),
            id="review_body",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_view()

    def current_card(self) -> dict | None:
        if self.index >= len(self.cards):
            return None
        return self.cards[self.index]

    def _refresh_view(self) -> None:
        card = self.current_card()
        card_text = self.query_one("#card_text", Static)
        progress = self.query_one("#progress", Static)
        if card is None:
            card_text.update("No more cards due. Press q to exit.")
            progress.update(
                f"Session done: {self.session_reviewed} reviewed, "
                f"{self.session_correct} correct."
            )
            return
        if self.revealed:
            card_text.update(f"Q: {card['front']}\n\nA: {card['back']}")
        else:
            card_text.update(f"Q: {card['front']}\n\n(space to reveal)")
        progress.update(
            f"Card {self.index + 1}/{len(self.cards)} | "
            f"reviewed: {self.session_reviewed} | correct: {self.session_correct}"
        )

    def action_reveal(self) -> None:
        if self.current_card() is not None:
            self.revealed = True
            self._refresh_view()

    def action_grade(self, quality: int) -> None:
        card = self.current_card()
        if card is None or not self.revealed:
            return

        state = ScheduleState(
            ef=card["ef"], repetitions=card["repetitions"], interval_days=card["interval_days"]
        )
        new_state = grade(state, quality)
        persist_grade(self.conn, card["id"], quality, new_state)

        self.session_reviewed += 1
        if quality >= 3:
            self.session_correct += 1

        self.index += 1
        self.revealed = False
        self._refresh_view()


def fetch_due_cards(conn, subject: str | None = None) -> list[dict]:
    """Fetch cards whose due_at_utc has passed, optionally filtered by subject."""
    now = datetime.now(timezone.utc).isoformat()
    if subject:
        rows = conn.execute(
            "SELECT * FROM cards WHERE due_at_utc <= ? AND subject = ? ORDER BY due_at_utc",
            (now, subject),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM cards WHERE due_at_utc <= ? ORDER BY due_at_utc", (now,)
        ).fetchall()
    return [dict(r) for r in rows]


def persist_grade(conn, card_id: int, quality: int, new_state: ScheduleState) -> None:
    """Persist a review grade: insert review row, update card's schedule state."""
    now = datetime.now(timezone.utc)
    due_at = now.replace(microsecond=0) + timedelta(days=new_state.interval_days)

    conn.execute(
        "INSERT INTO reviews (card_id, reviewed_at_utc, quality, ef_after, "
        "interval_days_after, repetitions_after) VALUES (?, ?, ?, ?, ?, ?)",
        (card_id, now.isoformat(), quality, new_state.ef, new_state.interval_days,
         new_state.repetitions),
    )
    conn.execute(
        "UPDATE cards SET ef = ?, repetitions = ?, interval_days = ?, due_at_utc = ? "
        "WHERE id = ?",
        (new_state.ef, new_state.repetitions, new_state.interval_days, due_at.isoformat(),
         card_id),
    )
    conn.commit()
