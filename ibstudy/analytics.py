"""Per-subject progress analytics. Pure functions operating on plain card/review rows, no I/O."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

MATURE_INTERVAL_DAYS = 21
YOUNG_MIN_REPETITIONS = 1


@dataclass(frozen=True)
class CardRow:
    subject: str
    ef: float
    repetitions: int
    interval_days: int
    due_at_utc: str


@dataclass(frozen=True)
class ReviewRow:
    subject: str
    reviewed_at_utc: str
    quality: int


@dataclass(frozen=True)
class SubjectStats:
    subject: str
    total: int
    mature: int
    young: int
    new: int
    retention_7d: float | None
    retention_30d: float | None
    avg_ef: float | None
    reviews_per_day: float
    due_forecast: list[int]  # length 14, count due on each of the next 14 days


def _card_maturity(card: CardRow) -> str:
    if card.repetitions == 0:
        return "new"
    if card.interval_days >= MATURE_INTERVAL_DAYS:
        return "mature"
    return "young"


def _retention(reviews: list[ReviewRow], now: datetime, window_days: int) -> float | None:
    cutoff = now - timedelta(days=window_days)
    windowed = [r for r in reviews if datetime.fromisoformat(r.reviewed_at_utc) >= cutoff]
    if not windowed:
        return None
    correct = sum(1 for r in windowed if r.quality >= 3)
    return correct / len(windowed)


def _reviews_per_day(reviews: list[ReviewRow], now: datetime, window_days: int = 30) -> float:
    cutoff = now - timedelta(days=window_days)
    windowed = [r for r in reviews if datetime.fromisoformat(r.reviewed_at_utc) >= cutoff]
    if not windowed:
        return 0.0
    return len(windowed) / window_days


def _due_forecast(cards: list[CardRow], now: datetime, days: int = 14) -> list[int]:
    counts = [0] * days
    for card in cards:
        due = datetime.fromisoformat(card.due_at_utc)
        delta_days = (due.date() - now.date()).days
        if 0 <= delta_days < days:
            counts[delta_days] += 1
    return counts


def compute_subject_stats(
    subject: str,
    cards: list[CardRow],
    reviews: list[ReviewRow],
    now: datetime | None = None,
) -> SubjectStats:
    """Compute all per-subject metrics from that subject's cards and reviews."""
    now = now or datetime.now(timezone.utc)

    total = len(cards)
    mature = sum(1 for c in cards if _card_maturity(c) == "mature")
    young = sum(1 for c in cards if _card_maturity(c) == "young")
    new = sum(1 for c in cards if _card_maturity(c) == "new")

    avg_ef = sum(c.ef for c in cards) / total if total else None

    return SubjectStats(
        subject=subject,
        total=total,
        mature=mature,
        young=young,
        new=new,
        retention_7d=_retention(reviews, now, 7),
        retention_30d=_retention(reviews, now, 30),
        avg_ef=avg_ef,
        reviews_per_day=_reviews_per_day(reviews, now),
        due_forecast=_due_forecast(cards, now),
    )
