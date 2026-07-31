"""Week arithmetic.

Small enough to inline, but it's the kind of thing that goes subtly wrong at
month boundaries, so it lives in one tested place.
"""

from __future__ import annotations

from datetime import date, timedelta

# Weeks start on Monday, matching how meal planning actually gets done — you sit
# down on the weekend and plan the week ahead.
WEEK_START = 0  # Monday, per date.weekday()


def week_start(day: date) -> date:
    """The Monday of the week containing ``day``."""
    return day - timedelta(days=(day.weekday() - WEEK_START) % 7)


def week_days(start: date) -> list[date]:
    """Seven consecutive dates beginning at ``start``."""
    return [start + timedelta(days=offset) for offset in range(7)]


def days_in_range(start: date, end: date) -> list[date]:
    """Every date from ``start`` to ``end``, inclusive of both ends.

    Unlike week_days this isn't anchored to a Monday — the pantry screen works
    off a rolling range like "today to a week from today", which is how you
    actually think about what you need to buy. A backwards range (end before
    start) yields nothing rather than raising: the date inputs are free text as
    far as the browser is concerned, and an empty pantry is a clearer answer
    than a stack trace.
    """
    if end < start:
        return []
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def shift_weeks(start: date, weeks: int) -> date:
    """Move a week start forwards or backwards."""
    return start + timedelta(weeks=weeks)


def describe_week(start: date) -> str:
    """A short human label like "3 – 9 Aug" for the header."""
    end = start + timedelta(days=6)
    if start.month == end.month:
        return f"{start.day} – {end.day} {start:%b %Y}"
    if start.year == end.year:
        return f"{start.day} {start:%b} – {end.day} {end:%b %Y}"
    return f"{start.day} {start:%b %Y} – {end.day} {end:%b %Y}"
