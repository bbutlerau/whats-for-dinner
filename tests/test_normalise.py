"""Tests for the ingredient parser.

The fresh/dried separation gets the most attention here because it's the rule most
likely to be broken by a well-meaning future change to the word lists.
"""

import pytest

from app.ingredients.normalise import parse_line


@pytest.mark.parametrize(
    ("raw", "quantity", "unit", "key"),
    [
        ("2 cloves garlic", "2", "clove", "garlic"),
        ("500g chicken thigh", "500", "g", "chicken thigh"),
        ("500 g chicken thigh", "500", "g", "chicken thigh"),
        ("1 1/2 cups plain flour", "1 1/2", "cup", "plain flour"),
        ("1/2 cup milk", "1/2", "cup", "milk"),
        ("½ cup milk", "1/2", "cup", "milk"),
        ("2-3 tbsp olive oil", "2-3", "tbsp", "olive oil"),
        ("1.5 kg pork shoulder", "1.5", "kg", "pork shoulder"),
        ("salt", None, None, "salt"),
    ],
)
def test_quantity_and_unit_extraction(raw, quantity, unit, key):
    parsed = parse_line(raw)
    assert parsed.quantity == quantity
    assert parsed.unit == unit
    assert parsed.key == key


class TestForms:
    """The load-bearing rule: fresh, dried, frozen and tinned stay distinct."""

    def test_fresh_and_dried_are_different_items(self):
        assert parse_line("1 tbsp fresh basil").key == "fresh basil"
        assert parse_line("1 tsp dried basil").key == "dried basil"
        assert parse_line("1 tbsp fresh basil").key != parse_line("1 tsp dried basil").key

    def test_unqualified_stays_unqualified(self):
        # Crucially it does NOT become "fresh basil" or "dried basil" — guessing
        # here is what would make the calendar colours lie.
        parsed = parse_line("basil")
        assert parsed.form == ""
        assert parsed.key == "basil"

    def test_form_after_a_comma_is_recognised(self):
        assert parse_line("2 tsp oregano, dried").key == "dried oregano"

    def test_inline_form_beats_trailing_form(self):
        assert parse_line("1 tbsp fresh parsley, dried if you must").key == "fresh parsley"

    def test_frozen_is_its_own_thing(self):
        assert parse_line("200g frozen peas").key == "frozen peas"
        assert parse_line("200g peas").key == "peas"

    @pytest.mark.parametrize(
        "raw",
        ["400g tin of tomatoes", "400g can of tomatoes", "1 tin chopped tomatoes",
         "2 x 400g tins chopped tomatoes", "400g tinned tomatoes"],
    )
    def test_tinned_variants_agree(self, raw):
        assert parse_line(raw).key == "tinned tomato"

    def test_dry_is_treated_as_dried(self):
        assert parse_line("1 cup dry lentils").key == "dried lentils"


class TestIdentityStripping:
    def test_prep_words_dropped(self):
        assert parse_line("1 finely chopped onion").key == "onion"
        assert parse_line("2 onions, roughly diced").key == "onion"
        assert parse_line("1 large onion").key == "onion"

    def test_plural_and_singular_agree(self):
        assert parse_line("3 tomatoes").key == parse_line("1 tomato").key == "tomato"
        assert parse_line("2 potatoes").key == "potato"

    def test_inherently_plural_words_left_alone(self):
        assert parse_line("1 cup peas").key == "peas"
        assert parse_line("100g oats").key == "oats"

    def test_ground_is_not_stripped(self):
        # "ground cumin" and "cumin seeds" are different things to own, and
        # stripping "ground" from mince would be worse still.
        assert parse_line("1 tsp ground cumin").key == "ground cumin"
        assert parse_line("500g ground beef").key == "ground beef"

    def test_freshly_is_prep_but_fresh_is_a_form(self):
        assert parse_line("freshly ground black pepper").key == "ground black pepper"
        assert parse_line("fresh coriander").key == "fresh coriander"

    def test_brackets_become_notes(self):
        parsed = parse_line("2 tbsp soy sauce (or tamari)")
        assert parsed.key == "soy sauce"
        assert "tamari" in parsed.note

    def test_raw_text_is_preserved_verbatim(self):
        parsed = parse_line("2 cloves garlic, finely crushed")
        assert parsed.raw_text == "2 cloves garlic, finely crushed"

    def test_display_name_is_capitalised(self):
        assert parse_line("1 tsp dried oregano").display_name == "Dried oregano"


def test_same_ingredient_different_wording_matches():
    """The whole point: two meals writing garlic differently share one pantry item."""
    assert parse_line("2 cloves garlic, crushed").key == parse_line("1 tsp garlic").key


def test_empty_line_produces_empty_key():
    # Guards the caller's `if not item.key: continue` check, which is what stops
    # blank form rows creating junk pantry entries.
    assert parse_line("   ").key == ""
