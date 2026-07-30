"""Tests for aisle classification."""

import pytest

from app.ingredients.aisles import classify, sorted_aisles


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("onion", "produce"),
        ("chicken thigh", "meat"),
        ("cheddar", "dairy"),
        ("sourdough", "bakery"),
        ("basmati rice", "pantry"),
        ("ground cumin", "spices"),
        ("orange juice", "drinks"),
        ("baking paper", "household"),
        ("ice cream", "frozen"),
    ],
)
def test_basic_classification(name, expected):
    assert classify(name) == expected


def test_longer_keyword_wins():
    """"sweet potato" must not be filed by the "potato" in it."""
    assert classify("sweet potato") == "produce"
    # And coconut milk is a pantry good, not dairy.
    assert classify("coconut milk") == "pantry"


class TestFormOverridesAisle:
    """The form can move an ingredient to a different part of the shop entirely."""

    def test_frozen_goes_to_the_freezer(self):
        assert classify("pea", "frozen") == "frozen"
        assert classify("pea") == "produce"

    def test_tinned_goes_to_the_pantry(self):
        assert classify("tomato", "tinned") == "pantry"
        assert classify("tomato") == "produce"

    def test_dried_herbs_go_to_spices(self):
        assert classify("oregano", "dried") == "spices"
        assert classify("basil", "dried") == "spices"

    def test_dried_pantry_goods_stay_in_the_pantry(self):
        assert classify("lentils", "dried") == "pantry"


def test_fuzzy_match_catches_misspellings():
    assert classify("corriander") == "produce"
    assert classify("yoghurt") == "dairy"


def test_fuzzy_match_uses_the_last_word():
    assert classify("roma tomatoes") == "produce"


def test_unknown_falls_back_to_other():
    """An honest "other" beats a confident wrong aisle."""
    assert classify("xyzzy powder") == "other"
    assert classify("") == "other"


def test_aisles_sort_in_shopping_walk_order():
    order = [a.slug for a in sorted_aisles({"frozen", "produce", "dairy", "other"})]
    assert order == ["produce", "dairy", "frozen", "other"]
