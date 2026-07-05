from pathlib import Path

from ib_tutor.stats import get_db, record_attempt, render_stats, subject_stats, weak_topics


def test_record_and_aggregate_subject_stats(tmp_path: Path) -> None:
    conn = get_db(tmp_path / "attempts.sqlite")
    record_attempt(conn, "physics", "phyA", "1", marks_gained=3, marks_available=4)
    record_attempt(conn, "physics", "phyB", "2", marks_gained=1, marks_available=4)
    record_attempt(conn, "mathaa", "aa5", "3", marks_gained=2, marks_available=2)

    stats = subject_stats(conn, "physics")
    assert stats.questions_attempted == 2
    assert stats.marks_gained == 4
    assert stats.marks_available == 8


def test_subject_stats_empty_subject_returns_zeros(tmp_path: Path) -> None:
    conn = get_db(tmp_path / "attempts.sqlite")
    stats = subject_stats(conn, "physics")
    assert stats.questions_attempted == 0
    assert stats.marks_gained == 0
    assert stats.marks_available == 0


def test_weak_topics_ranks_ascending_by_percentage(tmp_path: Path) -> None:
    conn = get_db(tmp_path / "attempts.sqlite")
    record_attempt(conn, "physics", "phyA", "1", marks_gained=4, marks_available=4)  # 100%
    record_attempt(conn, "physics", "phyB", "2", marks_gained=1, marks_available=4)  # 25%
    record_attempt(conn, "physics", "phyC", "3", marks_gained=2, marks_available=4)  # 50%

    ranked = weak_topics(conn, "physics")
    assert [t.topic for t in ranked] == ["phyB", "phyC", "phyA"]


def test_weak_topics_respects_limit(tmp_path: Path) -> None:
    conn = get_db(tmp_path / "attempts.sqlite")
    for i, topic in enumerate(["phyA", "phyB", "phyC"]):
        record_attempt(conn, "physics", topic, str(i), marks_gained=1, marks_available=4)
    assert len(weak_topics(conn, "physics", limit=2)) == 2


def test_render_stats_includes_marks_and_weak_topics(tmp_path: Path) -> None:
    conn = get_db(tmp_path / "attempts.sqlite")
    record_attempt(conn, "physics", "phyA", "1", marks_gained=1, marks_available=4)
    stats = subject_stats(conn, "physics")
    weak = weak_topics(conn, "physics")
    table = render_stats(stats, weak)
    assert table.title == "physics — stats"
    assert table.row_count == 3  # questions-attempted + marks + one weak-topic row
