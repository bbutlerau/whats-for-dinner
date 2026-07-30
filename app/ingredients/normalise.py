"""Parse a freeform ingredient line into a stable pantry identity.

This is the most failure-prone part of the app, so it's a pure function with no
database access and heavy test coverage. Everything else depends on it agreeing
with itself: if the same real-world ingredient parses to two different keys, the
calendar colours start lying.

The governing rule is that a *form* qualifier — fresh, dried, frozen, tinned —
is part of an ingredient's identity and is never normalised away. Dried basil is
not fresh basil, and frozen peas are not fresh peas. An ingredient with no form
stated keeps no form: it becomes its own pantry item rather than being guessed
into one of the others, because a wrong guess here is invisible until it gives
the wrong answer. The pantry's alias feature is how the user merges those by
hand, once, permanently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- Forms -----------------------------------------------------------------
# Words that pin down which version of an ingredient is meant, mapped to the
# canonical form we store. Everything on the left is removed from the name once
# it has been recognised, so "dried oregano" and "oregano, dried" agree.
FORM_WORDS: dict[str, str] = {
    "fresh": "fresh",
    "raw": "fresh",
    "dried": "dried",
    "dry": "dried",
    "dehydrated": "dried",
    "frozen": "frozen",
    "tinned": "tinned",
    "canned": "tinned",
    "tin": "tinned",
    "tins": "tinned",
    "can": "tinned",
    "cans": "tinned",
}

FORMS = ("fresh", "dried", "frozen", "tinned")

# --- Units -----------------------------------------------------------------
# Only consumed immediately after a quantity, which is what keeps "2 cloves
# garlic" (unit) apart from "1 tsp cloves" (the spice).
UNIT_WORDS: dict[str, str] = {
    "g": "g", "gram": "g", "grams": "g", "gr": "g",
    "kg": "kg", "kilo": "kg", "kilos": "kg", "kilogram": "kg", "kilograms": "kg",
    "mg": "mg",
    "ml": "ml", "millilitre": "ml", "millilitres": "ml", "milliliter": "ml", "milliliters": "ml",
    "l": "l", "litre": "l", "litres": "l", "liter": "l", "liters": "l",
    "tsp": "tsp", "teaspoon": "tsp", "teaspoons": "tsp",
    "tbsp": "tbsp", "tbs": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp",
    "cup": "cup", "cups": "cup",
    "oz": "oz", "ounce": "oz", "ounces": "oz",
    "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
    "clove": "clove", "cloves": "clove",
    "bunch": "bunch", "bunches": "bunch",
    "sprig": "sprig", "sprigs": "sprig",
    "stalk": "stalk", "stalks": "stalk",
    "stick": "stick", "sticks": "stick",
    "slice": "slice", "slices": "slice",
    "pinch": "pinch", "pinches": "pinch",
    "dash": "dash", "dashes": "dash",
    "handful": "handful", "handfuls": "handful",
    "packet": "packet", "packets": "packet", "pkt": "packet", "pack": "packet", "packs": "packet",
    "punnet": "punnet", "punnets": "punnet",
    "jar": "jar", "jars": "jar",
    "bottle": "bottle", "bottles": "bottle",
    "sheet": "sheet", "sheets": "sheet",
    "head": "head", "heads": "head",
    "rasher": "rasher", "rashers": "rasher",
    "fillet": "fillet", "fillets": "fillet",
    "piece": "piece", "pieces": "piece",
    "knob": "knob",
    "sachet": "sachet", "sachets": "sachet",
}

# --- Words dropped from the identity ---------------------------------------
# Preparation instructions describe what you do to an ingredient, not which
# ingredient it is, so "finely chopped onion" and "onion" should match.
#
# Note what is deliberately absent: "ground" and "smoked" stay, because ground
# cumin and cumin seeds are genuinely different things to have in the cupboard,
# and stripping "ground" from "ground beef" would turn mince into steak.
PREP_WORDS = frozenset({
    "chopped", "sliced", "diced", "minced", "crushed", "grated", "shredded",
    "peeled", "sifted", "melted", "softened", "beaten", "cooked", "drained",
    "rinsed", "halved", "quartered", "cubed", "trimmed", "deseeded", "seeded",
    "boneless", "skinless", "thinly", "finely", "roughly", "coarsely",
    "freshly", "lightly", "well", "washed", "torn", "pitted", "juiced",
    "zested", "divided", "optional", "approx",
})

# Size and grade adjectives that don't change what you'd buy.
FILLER_WORDS = frozenset({
    "of", "a", "an", "the", "some", "large", "small", "medium", "big",
    "extra", "virgin", "good", "quality", "your", "favourite", "favorite",
    "plus", "more", "about", "around",
})

# Unicode fraction glyphs, since recipe text is full of them.
VULGAR_FRACTIONS = {
    "¼": "1/4", "½": "1/2", "¾": "3/4", "⅓": "1/3", "⅔": "2/3",
    "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8", "⅕": "1/5", "⅙": "1/6",
}

# Inherently plural foods, left alone by the naive singulariser below because
# "1 Pea" and "1 Oat" read like a joke.
ALWAYS_PLURAL = frozenset({
    "peas", "beans", "chickpeas", "lentils", "oats", "noodles", "chives",
    "greens", "sprouts", "chips", "crisps", "breadcrumbs", "olives", "capers",
    "anchovies", "sardines", "prawns", "grapes", "berries", "raisins",
    "sultanas", "cornflakes", "hummus", "couscous", "asparagus", "molasses",
    "watercress", "brussels", "nachos", "sprinkles", "flakes", "seeds", "nuts",
    "leaves", "herbs", "spices",
})

IRREGULAR_SINGULARS = {
    "tomatoes": "tomato", "potatoes": "potato", "avocadoes": "avocado",
    "mangoes": "mango", "loaves": "loaf", "knives": "knife",
    "cherries": "cherry", "strawberries": "strawberry",
    "blueberries": "blueberry", "raspberries": "raspberry",
    "chillies": "chilli", "chilies": "chilli", "chiles": "chilli",
}

# A quantity: digits with optional decimal or fraction, optional mixed number,
# optional range. Anchored to the start of the line.
_QUANTITY_RE = re.compile(
    r"""^\s*
    (?P<qty>
        \d+\s+\d+/\d+          # 1 1/2
      | \d+/\d+                # 1/2
      | \d+(?:[.,]\d+)?        # 2  or  1.5
        (?:\s*(?:-|–|to)\s*\d+(?:[.,]\d+)?)?   # optional range: 2-3
    )
    \s*""",
    re.VERBOSE,
)

# A bare measurement stuck to a number anywhere in the text, e.g. the "400g" in
# "2 x 400g tins tomatoes". Removed from the name so it can't pollute the key.
_EMBEDDED_MEASURE_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:g|kg|mg|ml|l|oz|lb)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class ParsedIngredient:
    """The result of parsing one ingredient line.

    ``key`` is the identity used to find or create a pantry item and is the only
    field that must stay stable over time; the rest is for display.
    """

    raw_text: str
    quantity: str | None
    unit: str | None
    form: str  # "" when the line didn't say
    base_name: str
    note: str  # the bit after the comma or in brackets, kept only for reference

    @property
    def key(self) -> str:
        """Normalised pantry identity, form included: e.g. "dried basil"."""
        return f"{self.form} {self.base_name}".strip()

    @property
    def display_name(self) -> str:
        """Human-facing label for the pantry and shopping list."""
        return self.key[:1].upper() + self.key[1:] if self.key else ""


def _expand_fractions(text: str) -> str:
    for glyph, ascii_form in VULGAR_FRACTIONS.items():
        text = text.replace(glyph, f" {ascii_form} ")
    return text


def _singularise(word: str) -> str:
    """Naive singulariser, good enough for grocery nouns.

    Anything it gets wrong produces a separate pantry item that the user can
    merge with an alias, which is a far better failure mode than silently
    merging two things that differ.
    """
    if word in ALWAYS_PLURAL:
        return word
    if word in IRREGULAR_SINGULARS:
        return IRREGULAR_SINGULARS[word]
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("oes") and len(word) > 4:
        return word[:-2]
    if word.endswith("ses") or word.endswith("shes") or word.endswith("ches"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def parse_line(raw: str) -> ParsedIngredient:
    """Parse one ingredient line such as "2 cloves garlic, finely crushed"."""
    raw_text = " ".join(raw.split())
    working = _expand_fractions(raw_text.lower())

    # Bracketed asides are notes, never identity. Pull them out first so their
    # contents can't be mistaken for a quantity or a form.
    notes: list[str] = []
    def _capture_bracket(match: re.Match[str]) -> str:
        notes.append(match.group(1).strip())
        return " "

    working = re.sub(r"\(([^)]*)\)", _capture_bracket, working)

    # Everything after the first comma is normally a preparation note — but it
    # can also carry the form, as in "basil, dried". So the tail is scanned for
    # form words before being set aside.
    trailing_form = ""
    if "," in working:
        head, _, tail = working.partition(",")
        for word in re.findall(r"[a-z]+", tail):
            if word in FORM_WORDS:
                trailing_form = FORM_WORDS[word]
                break
        notes.append(tail.strip())
        working = head

    # Quantity, then a unit only if it sits immediately after that quantity.
    quantity: str | None = None
    unit: str | None = None
    match = _QUANTITY_RE.match(working)
    if match:
        quantity = " ".join(match.group("qty").replace(",", ".").split())
        working = working[match.end():]

        # "1 x 400g tin" — drop the multiplication marker so the unit check can
        # see what follows it.
        working = re.sub(r"^(?:x|×)\s*", "", working)

        tokens = working.split()
        if tokens and tokens[0].strip(".") in UNIT_WORDS:
            unit = UNIT_WORDS[tokens[0].strip(".")]
            working = " ".join(tokens[1:])
        else:
            # A unit fused to its number, as in "400g flour".
            fused = re.match(r"^([a-z]+)\b", working)
            if fused and fused.group(1) in UNIT_WORDS and quantity:
                unit = UNIT_WORDS[fused.group(1)]
                working = working[fused.end():]

    # A measurement fused to the quantity we already took, e.g. the "400g" in
    # "2 x 400g tins tomatoes", is redundant once the quantity is known.
    working = _EMBEDDED_MEASURE_RE.sub(" ", working)

    # "tin of tomatoes" / "can of beans" state the form in prose.
    working = re.sub(r"\b(tins?|cans?)\s+of\b", " tinned ", working)

    # Now reduce what's left to the identity: recognise the form, drop
    # preparation and filler words, and singularise.
    form = trailing_form
    kept: list[str] = []
    for token in re.findall(r"[a-z0-9'\-]+", working):
        if token in FORM_WORDS:
            # An inline form always beats one salvaged from after the comma,
            # so this overwrites trailing_form rather than deferring to it.
            form = FORM_WORDS[token]
            continue
        if token in PREP_WORDS or token in FILLER_WORDS:
            continue
        if token.isdigit():
            continue
        kept.append(token)

    if kept:
        kept[-1] = _singularise(kept[-1])

    base_name = " ".join(kept).strip(" -")

    return ParsedIngredient(
        raw_text=raw_text,
        quantity=quantity,
        unit=unit,
        form=form,
        base_name=base_name,
        note="; ".join(n for n in notes if n),
    )
