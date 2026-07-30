"""Tests for the calendar colour logic.

These matter more than they look: the colours are the only thing the app really
promises, and a wrong one is invisible until you're missing an onion at 6pm.
"""

from datetime import date

from sqlmodel import Session, select

from app.ingredients.store import set_alias
from app.models import PantryItem, PlanEntry
from app.planner.status import AMBER, GREEN, GREY, RED, build_week, status_for_meal


def _item(session: Session, key: str) -> PantryItem:
    return session.exec(select(PantryItem).where(PantryItem.key == key)).one()


def _stock(session: Session, *keys: str) -> None:
    for key in keys:
        item = _item(session, key)
        item.in_stock = True
        session.add(item)
    session.commit()


def test_missing_everything_is_red(session, make_meal):
    meal = make_meal("Test stir fry", ["500g chicken thigh", "1 onion"])
    status = status_for_meal(session, meal)
    assert status.status == RED
    assert set(status.missing) == {"chicken thigh", "onion"}


def test_all_in_stock_is_green(session, make_meal):
    meal = make_meal("Test stir fry", ["500g chicken thigh", "1 onion"])
    _stock(session, "chicken thigh", "onion")
    assert status_for_meal(session, meal).status == GREEN


def test_only_staples_missing_is_amber(session, make_meal):
    """Salt shouldn't make a night look like a shopping trip."""
    meal = make_meal("Test roast", ["1 onion", "1 tsp salt"])
    _stock(session, "onion")

    salt = _item(session, "salt")
    assert salt.is_staple, "salt should be auto-flagged as a staple"

    status = status_for_meal(session, meal)
    assert status.status == AMBER
    assert status.missing == []
    assert status.missing_staples == ["salt"]


def test_real_ingredient_outranks_a_staple(session, make_meal):
    meal = make_meal("Test roast", ["1 onion", "1 tsp salt"])
    status = status_for_meal(session, meal)
    assert status.status == RED
    assert status.missing == ["onion"]
    assert status.missing_staples == ["salt"]


def test_fresh_and_dried_are_tracked_separately(session, make_meal):
    """Having dried basil does not mean you have fresh basil."""
    meal = make_meal("Test pasta", ["1 bunch fresh basil"])
    make_meal("Test soup", ["1 tsp dried basil"])
    _stock(session, "dried basil")

    status = status_for_meal(session, meal)
    assert status.status == RED
    assert status.missing == ["fresh basil"]


def test_alias_merge_shares_stock(session, make_meal):
    """Merging bare "basil" into "dried basil" makes the bare one count as stocked."""
    meal = make_meal("Test soup", ["1 tsp basil"])
    make_meal("Test stew", ["1 tsp dried basil"])

    bare, dried = _item(session, "basil"), _item(session, "dried basil")
    dried.in_stock = True
    session.add(dried)
    set_alias(session, bare, dried)
    session.commit()

    assert status_for_meal(session, meal).status == GREEN


def test_summary_lists_what_is_missing(session, make_meal):
    meal = make_meal("Test curry", ["1 onion", "2 tomatoes", "1 tsp ground cumin", "500g lamb"])
    summary = status_for_meal(session, meal).summary
    assert summary.startswith("Need ")
    # Long lists are truncated so the calendar cell stays readable.
    assert "+1 more" in summary


class TestWeek:
    def test_unplanned_nights_are_grey(self, session):
        days = [date(2026, 8, 3), date(2026, 8, 4)]
        nights = build_week(session, days)
        assert [n.status.status for n in nights] == [GREY, GREY]
        assert all(not n.is_planned for n in nights)

    def test_planned_night_carries_its_meal_and_colour(self, session, make_meal):
        meal = make_meal("Test pasta", ["1 onion"])
        day = date(2026, 8, 3)
        session.add(PlanEntry(day=day, meal_id=meal.id))
        session.commit()

        nights = build_week(session, [day, date(2026, 8, 4)])
        assert nights[0].meal.name == "Test pasta"
        assert nights[0].status.status == RED
        assert nights[1].status.status == GREY
