"""Tests for the pantry screen's date range.

The range decides which items the screen shows at all, so a wrong default or a
silently-dropped query parameter would quietly hide things you needed to buy.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.main import PANTRY_RANGE_DAYS, _parse_range


class TestParseRange:
    def test_defaults_to_today_through_a_week_ahead(self):
        start, end = _parse_range(None, None)
        assert start == date.today()
        assert end == date.today() + timedelta(days=PANTRY_RANGE_DAYS)

    def test_explicit_range_is_respected(self):
        assert _parse_range("2026-08-03", "2026-08-09") == (date(2026, 8, 3), date(2026, 8, 9))

    def test_a_missing_end_is_filled_in_from_the_start(self):
        start, end = _parse_range("2026-08-03", None)
        assert start == date(2026, 8, 3)
        assert end == date(2026, 8, 3) + timedelta(days=PANTRY_RANGE_DAYS)

    def test_a_missing_start_defaults_to_today(self):
        start, end = _parse_range(None, "2099-01-01")
        assert start == date.today()
        assert end == date(2099, 1, 1)

    def test_a_backwards_range_is_swapped_rather_than_left_empty(self):
        assert _parse_range("2026-08-09", "2026-08-03") == (date(2026, 8, 3), date(2026, 8, 9))

    def test_unparseable_dates_fall_back_instead_of_erroring(self):
        # A hand-mangled URL should show the pantry, not a stack trace.
        start, end = _parse_range("not-a-date", "also-not-a-date")
        assert start == date.today()
        assert end == date.today() + timedelta(days=PANTRY_RANGE_DAYS)

    def test_empty_strings_are_treated_as_absent(self):
        # The hidden form fields submit "" when no range was ever chosen.
        assert _parse_range("", "") == _parse_range(None, None)
