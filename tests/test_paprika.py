"""Tests for the Paprika import.

The fixtures here are invented recipes in Paprika's file format, not anything from
a real collection.
"""

import gzip
import io
import json
import zipfile

import pytest
from sqlmodel import select

from app.models import SOURCE_MANUAL, SOURCE_PAPRIKA, Meal
from app.paprika.importer import import_meals
from app.paprika.parse import (
    meals_from_export,
    parse_duration,
    recipe_from_json,
    split_ingredients,
)


def _recipe(**overrides) -> dict:
    recipe = {
        "uid": "test-uid-1",
        "name": "Test Tray Bake",
        "ingredients": "500g chicken thigh\n1 onion\n1 tsp dried oregano",
        "directions": "Put it in the oven. This should be discarded.",
        "notes": "Also discarded.",
        "photo_data": "shouldnotbestored",
        "prep_time": "10 min",
        "cook_time": "35 min",
    }
    recipe.update(overrides)
    return recipe


def _export(recipes: list[dict]) -> bytes:
    """Build a .paprikarecipes archive in memory: zip of gzipped JSON."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for index, recipe in enumerate(recipes):
            archive.writestr(
                f"recipe-{index}.paprikarecipe",
                gzip.compress(json.dumps(recipe).encode("utf-8")),
            )
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("text", "minutes"),
    [
        ("10 min", 10),
        ("45 mins", 45),
        ("1 hr", 60),
        ("1 hr 20 min", 80),
        ("2 hours 5 minutes", 125),
        ("30", 30),
        ("", None),
        (None, None),
        ("overnight", None),
    ],
)
def test_parse_duration(text, minutes):
    assert parse_duration(text) == minutes


def test_prep_and_cook_time_are_added_together():
    meal = recipe_from_json(_recipe())
    assert meal.prep_minutes == 45


def test_section_headers_and_blanks_dropped():
    lines = split_ingredients("For the sauce:\n\n2 tbsp soy sauce\n- 1 tsp honey\n")
    assert lines == ["2 tbsp soy sauce", "1 tsp honey"]


def test_only_the_three_fields_are_kept():
    """Directions, notes and photos must not survive the parse."""
    meal = recipe_from_json(_recipe())
    assert meal.name == "Test Tray Bake"
    assert len(meal.ingredient_lines) == 3
    assert not hasattr(meal, "directions")
    assert "oven" not in repr(meal)
    assert "shouldnotbestored" not in repr(meal)


def test_deleted_and_unnamed_recipes_are_skipped():
    assert recipe_from_json(_recipe(deleted=True)) is None
    assert recipe_from_json(_recipe(name="  ")) is None


def test_meals_from_export_reads_the_archive():
    meals = meals_from_export(_export([_recipe(), _recipe(uid="u2", name="Test Soup")]))
    assert {m.name for m in meals} == {"Test Tray Bake", "Test Soup"}


def test_a_corrupt_member_does_not_lose_the_rest():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("good.paprikarecipe", gzip.compress(json.dumps(_recipe()).encode()))
        archive.writestr("bad.paprikarecipe", b"not gzip, not json")
    meals = meals_from_export(buffer.getvalue())
    assert [m.name for m in meals] == ["Test Tray Bake"]


class TestImport:
    def test_import_creates_meals_with_parsed_ingredients(self, session):
        result = import_meals(session, meals_from_export(_export([_recipe()])))
        assert result.created == 1

        meal = session.exec(select(Meal)).one()
        assert meal.source == SOURCE_PAPRIKA
        assert meal.prep_minutes == 45
        # Ingredients went through the same normaliser as manual entry, so the
        # dried oregano is stored as its own pantry identity.
        keys = {line.raw_text for line in meal.ingredients}
        assert "1 tsp dried oregano" in keys

    def test_reimport_updates_rather_than_duplicates(self, session):
        import_meals(session, meals_from_export(_export([_recipe()])))
        result = import_meals(
            session, meals_from_export(_export([_recipe(name="Test Tray Bake v2")]))
        )
        assert result.updated == 1
        assert len(session.exec(select(Meal)).all()) == 1
        assert session.exec(select(Meal)).one().name == "Test Tray Bake v2"

    def test_manual_meals_are_never_overwritten(self, session, make_meal):
        """If you typed it, it's yours."""
        make_meal("Test Tray Bake", ["1 onion"])
        result = import_meals(session, meals_from_export(_export([_recipe()])))

        assert result.skipped_manual == 1
        assert result.created == 0
        meal = session.exec(select(Meal)).one()
        assert meal.source == SOURCE_MANUAL
        assert [line.raw_text for line in meal.ingredients] == ["1 onion"]
