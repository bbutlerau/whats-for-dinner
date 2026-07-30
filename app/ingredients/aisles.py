"""Which part of the shop an ingredient comes from, Listonic-style.

Aisles exist purely so the shopping list groups sensibly and each line gets an
emoji you can scan at a glance. The list of aisles is intentionally short — a
supermarket has thirty, but a shopping list only needs enough grouping to stop
you walking back and forth.

Matching happens in three passes, cheapest and most certain first:

1. an exact hit on the ingredient's own keyword list,
2. a substring hit, so "chicken thigh" finds "chicken",
3. a fuzzy hit via difflib, which catches typos and near-misses like
   "corriander" or "yoghurt" vs "yogurt".

Anything still unmatched lands in "other" rather than being forced somewhere
wrong. The keyword lists are meant to be topped up by hand over time; that's a
deliberate trade of a little upkeep for behaviour that never surprises you.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches


@dataclass(frozen=True)
class Aisle:
    slug: str
    label: str
    emoji: str
    # Where this aisle appears on the shopping list. Roughly the order you'd
    # walk a supermarket: fresh things first, freezer last so they stay cold.
    order: int


AISLES: dict[str, Aisle] = {
    "produce": Aisle("produce", "Fruit & veg", "🥬", 10),
    "meat": Aisle("meat", "Meat & seafood", "🥩", 20),
    "dairy": Aisle("dairy", "Dairy & eggs", "🥛", 30),
    "bakery": Aisle("bakery", "Bakery", "🍞", 40),
    "pantry": Aisle("pantry", "Pantry", "🥫", 50),
    "spices": Aisle("spices", "Herbs & spices", "🌿", 60),
    "drinks": Aisle("drinks", "Drinks", "🧃", 70),
    "household": Aisle("household", "Household", "🧽", 80),
    "frozen": Aisle("frozen", "Frozen", "🧊", 90),
    "other": Aisle("other", "Other", "🛒", 100),
}

OTHER = AISLES["other"]

# Keywords per aisle. These are matched against the *base name*, so the form
# qualifier is stripped before lookup — "frozen peas" checks "peas", then gets
# routed to the freezer by the form rule in classify().
KEYWORDS: dict[str, tuple[str, ...]] = {
    "produce": (
        "apple", "avocado", "banana", "basil", "bean sprout", "beetroot",
        "berry", "blueberry", "bok choy", "broccoli", "cabbage", "capsicum",
        "carrot", "cauliflower", "celery", "cherry", "chilli", "coriander",
        "corn", "cucumber", "eggplant", "fennel", "garlic", "ginger", "grape",
        "green bean", "kale", "leek", "lemon", "lettuce", "lime", "mandarin",
        "mango", "melon", "mint", "mushroom", "nectarine", "onion", "orange",
        "parsley", "parsnip", "pea", "peach", "pear", "potato", "pumpkin",
        "radish", "raspberry", "rocket", "rosemary", "salad", "shallot",
        "silverbeet", "spinach", "spring onion", "sprout", "strawberry",
        "sweet potato", "thyme", "tomato", "watermelon", "zucchini",
    ),
    "meat": (
        "anchovy", "bacon", "beef", "chicken", "chorizo", "duck", "fish",
        "ham", "kransky", "lamb", "mince", "mussel", "pancetta", "pork",
        "prawn", "salami", "salmon", "sardine", "sausage", "scallop",
        "seafood", "snapper", "squid", "steak", "tuna", "turkey", "veal",
    ),
    "dairy": (
        "butter", "cheddar", "cheese", "cream", "creme fraiche", "custard",
        "egg", "feta", "fetta", "ghee", "haloumi", "halloumi", "milk",
        "mascarpone", "mozzarella", "parmesan", "ricotta", "sour cream",
        "yoghurt", "yogurt",
    ),
    "bakery": (
        "bagel", "baguette", "bread", "breadcrumb", "brioche", "bun",
        "croissant", "crumpet", "flatbread", "focaccia", "muffin", "naan",
        "pita", "roll", "sourdough", "tortilla", "wrap",
    ),
    "pantry": (
        "baking powder", "baking soda", "bicarb", "cannellini", "chickpea",
        "cocoa", "coconut cream", "coconut milk", "cornflour", "couscous",
        "flour", "honey", "jam", "kidney bean", "lentil", "maple syrup",
        "mayonnaise", "mustard", "noodle", "nut", "oat", "oil", "olive",
        "pasta", "peanut butter", "polenta", "quinoa", "rice", "sauce",
        "sesame oil", "soy sauce", "stock", "sugar", "sultana", "tahini",
        "tomato paste", "tuna", "vinegar", "wine", "worcestershire", "yeast",
    ),
    "spices": (
        "allspice", "bay leaf", "cardamom", "cayenne", "chilli flake",
        "chilli powder", "cinnamon", "clove", "cumin", "curry powder",
        "fennel seed", "five spice", "garam masala", "herb", "nutmeg",
        "oregano", "paprika", "pepper", "peppercorn", "salt", "sesame seed",
        "spice", "star anise", "sumac", "tarragon", "turmeric", "vanilla",
    ),
    "drinks": (
        "beer", "cider", "coffee", "cordial", "juice", "lemonade",
        "soda water", "sparkling water", "tea", "tonic", "water",
    ),
    "household": (
        "alfoil", "baking paper", "bin bag", "cling wrap", "detergent",
        "dishwasher tablet", "foil", "napkin", "paper towel", "skewer",
        "sponge", "toothpick", "wrap",
    ),
    "frozen": (
        "ice cream", "frozen berry", "frozen pea", "ice", "pastry",
        "puff pastry", "filo",
    ),
}

# Flattened once at import: keyword -> aisle slug. Longer keywords are checked
# before shorter ones so "sweet potato" beats "potato" and "coconut milk" beats
# "milk", which is the difference between a sensible list and a silly one.
_KEYWORD_TO_AISLE: dict[str, str] = {}
for _slug, _words in KEYWORDS.items():
    for _word in _words:
        # First aisle to claim a keyword keeps it; "tuna" appears twice above
        # (fresh in meat, tinned in pantry) and meat is declared first, so the
        # tinned case is handled by the form rule in classify() instead.
        _KEYWORD_TO_AISLE.setdefault(_word, _slug)

_KEYWORDS_BY_LENGTH: tuple[str, ...] = tuple(
    sorted(_KEYWORD_TO_AISLE, key=len, reverse=True)
)

# Multi-word keywords are checked ahead of single words because they're strictly
# more specific: "coconut milk" is a pantry good rather than dairy, and "sweet
# potato" is not merely a potato.
_MULTIWORD_KEYWORDS: tuple[str, ...] = tuple(k for k in _KEYWORDS_BY_LENGTH if " " in k)


def classify(base_name: str, form: str = "") -> str:
    """Return the aisle slug for an ingredient.

    ``form`` is taken into account because it can move an item to a different
    part of the shop entirely: frozen peas are in the freezer even though peas
    are produce, and tinned tomatoes are in the pantry even though tomatoes
    aren't. This is the same reason the form is part of the pantry identity.
    """
    name = " ".join(base_name.lower().split())
    if not name:
        return "other"

    # The form can override the aisle outright.
    if form == "frozen":
        return "frozen"
    if form == "tinned":
        return "pantry"
    if form == "dried":
        # Dried herbs stay with the spices; dried pasta, beans and fruit are
        # pantry goods. Falling through to keyword matching gets both right,
        # except for produce, which dried definitively isn't.
        slug = _match_keyword(name)
        if slug in (None, "produce"):
            return "pantry" if slug is None else "spices"
        return slug

    return _match_keyword(name) or _fuzzy_match(name) or "other"


def _match_keyword(name: str) -> str | None:
    """Match a name against the keyword lists, most specific signal first.

    The ordering is what makes this behave sensibly on compound names:

    1. the whole name, if it's a keyword outright;
    2. a multi-word keyword appearing in it, since those are the specific cases
       that exist precisely to override a single word ("coconut milk", "sweet
       potato", "tomato paste");
    3. the last word, which in English is the head noun — this is what puts
       "orange juice" in the drinks aisle instead of following "orange" into the
       fruit and veg;
    4. any single-word keyword appearing anywhere, longest first, which catches
       modifiers like "chicken thigh".
    """
    if name in _KEYWORD_TO_AISLE:
        return _KEYWORD_TO_AISLE[name]

    for keyword in _MULTIWORD_KEYWORDS:
        if keyword in name:
            return _KEYWORD_TO_AISLE[keyword]

    words = name.split()
    if len(words) > 1 and words[-1] in _KEYWORD_TO_AISLE:
        return _KEYWORD_TO_AISLE[words[-1]]

    for keyword in _KEYWORDS_BY_LENGTH:
        if keyword in name:
            return _KEYWORD_TO_AISLE[keyword]
    return None


def _fuzzy_match(name: str) -> str | None:
    """Last resort: catch typos and spelling variants.

    The cutoff is high on purpose. A confident wrong aisle is more annoying than
    an honest "other", because you only find out when you're standing in the
    wrong part of the shop.
    """
    # Compare the last word too — it's usually the noun, so "roma tomatoes"
    # still finds "tomato" even when the whole phrase is too different.
    candidates = [name]
    words = name.split()
    if len(words) > 1:
        candidates.append(words[-1])

    for candidate in candidates:
        matches = get_close_matches(candidate, _KEYWORDS_BY_LENGTH, n=1, cutoff=0.85)
        if matches:
            return _KEYWORD_TO_AISLE[matches[0]]
    return None


def aisle_for(slug: str) -> Aisle:
    """Look up aisle metadata, falling back to "Other" for unknown slugs."""
    return AISLES.get(slug, OTHER)


def sorted_aisles(slugs: set[str]) -> list[Aisle]:
    """Aisles in shopping-walk order, for rendering the list."""
    return sorted((aisle_for(s) for s in slugs), key=lambda a: a.order)
