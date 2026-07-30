"""Tests for shopping-list consolidation and the Listonic export."""

from datetime import date

from sqlmodel import Session, select

from app.models import PantryItem, PlanEntry
from app.shopping import listonic
from app.shopping.list import build_list

MONDAY = date(2026, 8, 3)
TUESDAY = date(2026, 8, 4)
WEEK = [MONDAY, TUESDAY]


def _plan(session: Session, day: date, meal) -> None:
    session.add(PlanEntry(day=day, meal_id=meal.id))
    session.commit()


def _entries(shopping_list) -> dict[str, str]:
    """Flatten to {display name: amount} for easy assertions."""
    return {
        entry.display_name: entry.amount_text
        for group in shopping_list.needed
        for entry in group.entries
    }


def test_ingredients_appear_grouped_by_aisle(session, make_meal):
    meal = make_meal("Test stir fry", ["500g chicken thigh", "1 onion"])
    _plan(session, MONDAY, meal)

    result = build_list(session, WEEK)
    by_aisle = {
        group.aisle.slug: [e.display_name for e in group.entries] for group in result.needed
    }
    assert by_aisle["produce"] == ["Onion"]
    assert by_aisle["meat"] == ["Chicken thigh"]
    # The emoji is what makes the list scannable in a shop.
    assert next(g.aisle.emoji for g in result.needed if g.aisle.slug == "produce")


def test_in_stock_items_are_excluded(session, make_meal):
    meal = make_meal("Test stir fry", ["500g chicken thigh", "1 onion"])
    _plan(session, MONDAY, meal)

    onion = session.exec(select(PantryItem).where(PantryItem.key == "onion")).one()
    onion.in_stock = True
    session.add(onion)
    session.commit()

    assert "Onion" not in _entries(build_list(session, WEEK))


def test_same_ingredient_across_two_meals_is_one_line(session, make_meal):
    first = make_meal("Test stir fry", ["1 onion"])
    second = make_meal("Test curry", ["2 onions"])
    _plan(session, MONDAY, first)
    _plan(session, TUESDAY, second)

    result = build_list(session, WEEK)
    entries = _entries(result)
    assert list(entries) == ["Onion"]
    # Same unit (none) and both numeric, so they add up.
    assert entries["Onion"] == "3"

    entry = result.needed[0].entries[0]
    assert set(entry.meals) == {"Test stir fry", "Test curry"}


def test_matching_units_are_summed(session, make_meal):
    first = make_meal("Test bake", ["1/2 cup milk"])
    second = make_meal("Test sauce", ["1/2 cup milk"])
    _plan(session, MONDAY, first)
    _plan(session, TUESDAY, second)

    assert _entries(build_list(session, WEEK))["Milk"] == "1 cup"


def test_mismatched_units_are_listed_side_by_side(session, make_meal):
    """Better an untidy "2 cup + 400 g" than a confidently wrong single number.

    Rice rather than flour here on purpose: flour is auto-flagged as a staple and
    would land in the staples section instead of an aisle.
    """
    first = make_meal("Test bowl", ["2 cups rice"])
    second = make_meal("Test pilaf", ["400g rice"])
    _plan(session, MONDAY, first)
    _plan(session, TUESDAY, second)

    amount = _entries(build_list(session, WEEK))["Rice"]
    assert "2 cup" in amount and "400 g" in amount


def test_ranges_survive_as_text(session, make_meal):
    meal = make_meal("Test salad", ["2-3 tbsp olive oil"])
    _plan(session, MONDAY, meal)
    # Olive oil is a staple, so it lands in the staples section.
    result = build_list(session, WEEK)
    assert result.staples[0].amount_text == "2-3 tbsp"


def test_quantityless_ingredient_says_as_needed(session, make_meal):
    meal = make_meal("Test greens", ["baby spinach"])
    _plan(session, MONDAY, meal)
    assert _entries(build_list(session, WEEK))["Baby spinach"] == "as needed"


def test_staples_are_kept_out_of_the_aisles(session, make_meal):
    meal = make_meal("Test roast", ["1 onion", "1 tsp salt", "2 tbsp olive oil"])
    _plan(session, MONDAY, meal)

    result = build_list(session, WEEK)
    assert _entries(result) == {"Onion": "1"}
    assert {e.display_name for e in result.staples} == {"Salt", "Olive oil"}


def test_meal_cooked_twice_is_not_double_counted(session, make_meal):
    meal = make_meal("Test stir fry", ["1 onion"])
    _plan(session, MONDAY, meal)
    _plan(session, TUESDAY, meal)

    assert _entries(build_list(session, WEEK)) == {"Onion": "1"}


def test_empty_week_is_empty(session):
    assert build_list(session, WEEK).is_empty


class TestListonicExport:
    def test_one_item_per_line_with_amounts(self, session, make_meal):
        meal = make_meal("Test stir fry", ["500g chicken thigh", "1 onion"])
        _plan(session, MONDAY, meal)

        text = listonic.as_text(build_list(session, WEEK))
        lines = text.splitlines()
        assert "Onion 1" in lines
        assert "Chicken thigh 500 g" in lines
        # No emoji: Listonic categorises items itself, and a leading emoji would
        # become part of the item name.
        assert not any(line.startswith(("🥬", "🥩")) for line in lines)

    def test_as_needed_is_not_exported_as_a_quantity(self, session, make_meal):
        meal = make_meal("Test greens", ["baby spinach"])
        _plan(session, MONDAY, meal)
        assert listonic.as_text(build_list(session, WEEK)) == "Baby spinach"

    def test_staples_excluded_by_default(self, session, make_meal):
        meal = make_meal("Test roast", ["1 onion", "1 tsp salt"])
        _plan(session, MONDAY, meal)

        shopping_list = build_list(session, WEEK)
        assert "Salt" not in listonic.as_text(shopping_list)
        assert "Salt" in listonic.as_text(shopping_list, include_staples=True)
