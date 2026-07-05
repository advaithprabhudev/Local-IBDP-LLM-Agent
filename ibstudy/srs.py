"""Canonical SM-2 spaced-repetition scheduler. Pure functions, no I/O."""

from dataclasses import dataclass

EF_FLOOR = 1.3
EF_INITIAL = 2.5


@dataclass(frozen=True)
class ScheduleState:
    ef: float
    repetitions: int
    interval_days: int


def grade(state: ScheduleState, quality: int) -> ScheduleState:
    """Apply one SM-2 review grade (0-5) to a card's schedule state."""
    if not 0 <= quality <= 5:
        raise ValueError(f"quality must be 0-5, got {quality}")

    new_ef = state.ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    new_ef = max(EF_FLOOR, new_ef)

    if quality < 3:
        return ScheduleState(ef=new_ef, repetitions=0, interval_days=1)

    repetitions = state.repetitions + 1
    if repetitions == 1:
        interval_days = 1
    elif repetitions == 2:
        interval_days = 6
    else:
        interval_days = round(state.interval_days * new_ef)

    return ScheduleState(ef=new_ef, repetitions=repetitions, interval_days=interval_days)
