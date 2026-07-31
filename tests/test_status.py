"""Tests for the calendar colour logic.

These matter more than they look: the colours are the only thing the app really
promises, and a wrong one is invisible until you're missing an onion at 6pm.
"""

from datetime import date

from sqlmodel import Session, select

from app.ingredients.store import resolve_line, set_alias
from app.models import PantryItem, PlanEntry
from app.planner.status import (
    AMBER,
    GREEN,
    GREY,
    RED,
    build_week,
    pantry_item_ids_for_days,
    status_for_meal,
)


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


class TestPantryItemIdsForDays:
    """The pantry screen shows only what the planned meals in a range need."""

    def test_only_items_from_meals_planned_in_the_range(self, session, make_meal):
        planned = make_meal("Test noodle bowl", ["2 spring onions", "1 tbsp miso paste"])
        make_meal("Test unplanned bake", ["300 g invented cheese"])
        session.add(PlanEntry(day=date(2026, 8, 3), meal_id=planned.id))
        session.commit()

        ids = pantry_item_ids_for_days(session, [date(2026, 8, 3)])
        names = {session.get(PantryItem, i).display_name.lower() for i in ids}

        assert any("spring onion" in n for n in names)
        assert any("miso" in n for n in names)
        # The unplanned meal's ingredient exists in the pantry table but is not
        # part of this range, so it must not come back.
        assert not any("cheese" in n for n in names)

    def test_a_day_outside_the_range_is_excluded(self, session, make_meal):
        meal = make_meal("Test soup", ["1 carrot"])
        session.add(PlanEntry(day=date(2026, 8, 10), meal_id=meal.id))
        session.commit()

        assert pantry_item_ids_for_days(session, [date(2026, 8, 3)]) == set()
        assert pantry_item_ids_for_days(session, [date(2026, 8, 10)]) != set()

    def test_empty_range_returns_nothing(self, session, make_meal):
        meal = make_meal("Test soup", ["1 carrot"])
        session.add(PlanEntry(day=date(2026, 8, 3), meal_id=meal.id))
        session.commit()

        assert pantry_item_ids_for_days(session, []) == set()

    def test_the_same_meal_twice_in_a_range_is_not_double_counted(self, session, make_meal):
        meal = make_meal("Test soup", ["1 carrot"])
        session.add(PlanEntry(day=date(2026, 8, 3), meal_id=meal.id))
        session.add(PlanEntry(day=date(2026, 8, 4), meal_id=meal.id))
        session.commit()

        ids = pantry_item_ids_for_days(session, [date(2026, 8, 3), date(2026, 8, 4)])
        assert len(ids) == 1

    def test_a_merged_ingredient_resolves_to_its_target(self, session, make_meal):
        """A merged item must surface as the item that actually holds the stock.

        Otherwise merging basil into dried basil would make the row disappear
        from the pantry for a week that genuinely needs it.
        """
        meal = make_meal("Test herb salad", ["1 tsp invented herb"])
        session.add(PlanEntry(day=date(2026, 8, 3), meal_id=meal.id))
        session.commit()

        bare = session.exec(
            select(PantryItem).where(PantryItem.display_name.contains("invented herb"))
        ).first()
        # Built through resolve_line so it gets a proper key and aisle, the same
        # way a real ingredient line would create it.
        _, target = resolve_line(session, "1 tsp dried invented herb")
        session.commit()
        set_alias(session, bare, target)
        session.commit()

        ids = pantry_item_ids_for_days(session, [date(2026, 8, 3)])
        assert ids == {target.id}
