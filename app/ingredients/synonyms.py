"""Ingredients that are the same thing under two names.

This exists because string similarity cannot find these. "Cilantro" and
"coriander" score 0.59 against each other, and "zucchini" and "courgette" score
0.12 — below any cutoff you could set without also proposing that a carrot is a
parrot, which scores 0.83. The only honest way to know these are the same plant
is to be told, so they're listed by hand.

Most of the list is the Australian/American split, which matters here because
Paprika recipes are so often written for a US kitchen while the shopping happens
in an Australian supermarket.

Nothing in this file merges anything on its own. It only decides what the pantry
*offers* as a likely merge — the user still confirms every one, and the domain
rule that an unqualified ingredient never silently becomes a qualified one is
untouched. Add a pair here whenever you find yourself making the same merge
twice; this is meant to be edited.
"""

from __future__ import annotations

# Each row is a set of names that all mean the same ingredient. Order within a
# row carries no meaning — the pantry suggests whichever one you already have.
SYNONYM_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"coriander", "cilantro"}),
    frozenset({"zucchini", "courgette"}),
    frozenset({"eggplant", "aubergine"}),
    frozenset({"capsicum", "bell pepper", "sweet pepper"}),
    frozenset({"rocket", "arugula"}),
    frozenset({"prawn", "shrimp"}),
    frozenset({"spring onion", "scallion", "green onion"}),
    frozenset({"chickpea", "garbanzo bean"}),
    frozenset({"coriander seed", "dhania"}),
    frozenset({"mince", "ground beef", "beef mince"}),
    frozenset({"tomato sauce", "ketchup"}),
    frozenset({"icing sugar", "powdered sugar", "confectioners sugar"}),
    frozenset({"caster sugar", "superfine sugar"}),
    frozenset({"bicarb soda", "baking soda", "bicarbonate of soda"}),
    frozenset({"cornflour", "cornstarch"}),
    frozenset({"plain flour", "all purpose flour"}),
    frozenset({"self raising flour", "self rising flour"}),
    frozenset({"desiccated coconut", "shredded coconut"}),
    frozenset({"sultana", "golden raisin"}),
    frozenset({"snow pea", "mangetout"}),
    frozenset({"swede", "rutabaga"}),
    frozenset({"silverbeet", "swiss chard", "chard"}),
    frozenset({"pumpkin", "squash"}),
    frozenset({"stock", "broth"}),
    frozenset({"single cream", "light cream"}),
    frozenset({"thickened cream", "heavy cream", "whipping cream"}),
)

# Flattened once at import: name -> every other name meaning the same thing.
_BY_NAME: dict[str, frozenset[str]] = {}
for _group in SYNONYM_GROUPS:
    for _name in _group:
        _BY_NAME[_name] = _group - {_name}


def synonyms_for(name: str) -> frozenset[str]:
    """Other names for ``name``, or an empty set if it isn't in the table."""
    return _BY_NAME.get(name.strip().lower(), frozenset())


def are_synonyms(left: str, right: str) -> bool:
    """Whether two base names are listed as the same ingredient."""
    return right.strip().lower() in synonyms_for(left)
