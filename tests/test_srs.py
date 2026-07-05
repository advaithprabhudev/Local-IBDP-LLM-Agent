import pytest

from ibstudy.srs import EF_FLOOR, EF_INITIAL, ScheduleState, grade


def new_state() -> ScheduleState:
    return ScheduleState(ef=EF_INITIAL, repetitions=0, interval_days=0)


def test_quality_below_range_raises():
    with pytest.raises(ValueError):
        grade(new_state(), -1)


def test_quality_above_range_raises():
    with pytest.raises(ValueError):
        grade(new_state(), 6)


def test_q4_streak_intervals_1_6_15_ef_stays_2_5():
    state = new_state()
    state = grade(state, 4)
    assert state.interval_days == 1
    assert state.ef == pytest.approx(2.5)
    state = grade(state, 4)
    assert state.interval_days == 6
    assert state.ef == pytest.approx(2.5)
    state = grade(state, 4)
    assert state.interval_days == 15
    assert state.ef == pytest.approx(2.5)


def test_second_review_correct_sets_interval_6():
    state = ScheduleState(ef=2.5, repetitions=1, interval_days=1)
    state = grade(state, 5)
    assert state.repetitions == 2
    assert state.interval_days == 6


def test_third_plus_review_uses_round_prev_times_ef():
    state = ScheduleState(ef=2.0, repetitions=2, interval_days=6)
    state = grade(state, 3)
    assert state.repetitions == 3
    assert state.interval_days == round(6 * state.ef)


def test_lapse_resets_repetitions_but_updates_ef():
    state = ScheduleState(ef=2.5, repetitions=4, interval_days=30)
    state = grade(state, 1)
    assert state.repetitions == 0
    assert state.interval_days == 1
    assert state.ef < 2.5


def test_ef_floor_is_never_breached():
    state = ScheduleState(ef=EF_FLOOR, repetitions=0, interval_days=0)
    state = grade(state, 0)
    assert state.ef == pytest.approx(EF_FLOOR)
