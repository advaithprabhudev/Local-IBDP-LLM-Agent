from datetime import datetime, timedelta, timezone

from ibstudy.analytics import CardRow, ReviewRow, compute_subject_stats

NOW = datetime(2026, 7, 3, tzinfo=timezone.utc)


def iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def due_iso(days_ahead: int) -> str:
    return (NOW + timedelta(days=days_ahead)).isoformat()


def test_empty_subject_has_no_cards_and_null_metrics():
    stats = compute_subject_stats("Economics HL", [], [], now=NOW)
    assert stats.total == 0
    assert stats.mature == 0
    assert stats.young == 0
    assert stats.new == 0
    assert stats.avg_ef is None
    assert stats.retention_7d is None
    assert stats.retention_30d is None
    assert stats.reviews_per_day == 0.0
    assert stats.due_forecast == [0] * 14


def test_card_maturity_buckets_new_young_mature():
    cards = [
        CardRow(subject="X", ef=2.5, repetitions=0, interval_days=0, due_at_utc=due_iso(0)),
        CardRow(subject="X", ef=2.5, repetitions=2, interval_days=6, due_at_utc=due_iso(1)),
        CardRow(subject="X", ef=2.5, repetitions=4, interval_days=21, due_at_utc=due_iso(2)),
    ]
    stats = compute_subject_stats("X", cards, [], now=NOW)
    assert stats.new == 1
    assert stats.young == 1
    assert stats.mature == 1
    assert stats.total == 3
    assert stats.avg_ef == 2.5


def test_retention_windows_include_only_recent_reviews_and_split_correct_incorrect():
    reviews = [
        ReviewRow(subject="X", reviewed_at_utc=iso(1), quality=4),  # correct, in both windows
        ReviewRow(subject="X", reviewed_at_utc=iso(2), quality=1),  # incorrect, in both windows
        ReviewRow(subject="X", reviewed_at_utc=iso(20), quality=5),  # correct, only in 30d window
        ReviewRow(subject="X", reviewed_at_utc=iso(90), quality=5),  # outside both windows
    ]
    stats = compute_subject_stats("X", [], reviews, now=NOW)
    assert stats.retention_7d == 0.5
    assert stats.retention_30d == 2 / 3
    assert stats.reviews_per_day == 3 / 30


def test_due_forecast_only_counts_next_14_days_and_ignores_past_or_far_future():
    cards = [
        CardRow(subject="X", ef=2.5, repetitions=1, interval_days=1, due_at_utc=due_iso(0)),
        CardRow(subject="X", ef=2.5, repetitions=1, interval_days=1, due_at_utc=due_iso(13)),
        CardRow(subject="X", ef=2.5, repetitions=1, interval_days=1, due_at_utc=due_iso(14)),
        CardRow(subject="X", ef=2.5, repetitions=1, interval_days=1, due_at_utc=due_iso(-1)),
    ]
    stats = compute_subject_stats("X", cards, [], now=NOW)
    assert stats.due_forecast[0] == 1
    assert stats.due_forecast[13] == 1
    assert sum(stats.due_forecast) == 2
