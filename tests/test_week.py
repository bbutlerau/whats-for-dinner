"""Tests for week arithmetic — the bit that goes subtly wrong at boundaries."""

from datetime import date

from app.planner.week import describe_week, shift_weeks, week_days, week_start


def test_week_starts_on_monday():
    # 2026-08-05 is a Wednesday.
    assert week_start(date(2026, 8, 5)) == date(2026, 8, 3)
    # A Monday is already the start of its own week.
    assert week_start(date(2026, 8, 3)) == date(2026, 8, 3)
    # A Sunday belongs to the week that began the previous Monday.
    assert week_start(date(2026, 8, 9)) == date(2026, 8, 3)


def test_week_days_returns_seven_consecutive_dates():
    days = week_days(date(2026, 8, 3))
    assert len(days) == 7
    assert days[0] == date(2026, 8, 3)
    assert days[-1] == date(2026, 8, 9)


def test_shifting_across_a_month_boundary():
    assert shift_weeks(date(2026, 8, 31), 1) == date(2026, 9, 7)
    assert shift_weeks(date(2026, 9, 7), -1) == date(2026, 8, 31)


def test_shifting_across_a_year_boundary():
    assert shift_weeks(date(2026, 12, 28), 1) == date(2027, 1, 4)


class TestDescribeWeek:
    def test_within_one_month(self):
        assert describe_week(date(2026, 8, 3)) == "3 – 9 Aug 2026"

    def test_spanning_two_months(self):
        assert describe_week(date(2026, 8, 31)) == "31 Aug – 6 Sep 2026"

    def test_spanning_two_years(self):
        assert describe_week(date(2026, 12, 28)) == "28 Dec 2026 – 3 Jan 2027"
