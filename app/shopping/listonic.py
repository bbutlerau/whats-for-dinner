"""Getting the shopping list into Listonic.

Listonic has no public API. The developer site at dev.listonic.com is their
consultancy arm selling a shopping-cart API to retail clients, not a way to write
items into your own personal list, and there's no OAuth or token flow to hook
into. So the export here is honest about that: it renders the list as plain text,
one item per line, which Listonic's "add items" box accepts as a single paste.

Everything Listonic-shaped is confined to this module. If an API ever appears,
this is the only file that should need to change — the shopping list itself knows
nothing about how it gets exported.
"""

from __future__ import annotations

from app.shopping.list import ShoppingList


def as_text(shopping_list: ShoppingList, include_staples: bool = False) -> str:
    """Render the list as newline-separated items for pasting into Listonic.

    Amounts are kept inline ("Chicken thigh 500 g") because Listonic parses a
    trailing quantity out of a pasted line into its own amount field. Aisle
    emoji are left off deliberately: Listonic assigns its own categories, and a
    leading emoji just ends up as part of the item name.
    """
    lines: list[str] = []

    for group in shopping_list.needed:
        for entry in group.entries:
            lines.append(_format_entry(entry.display_name, entry.amount_text))

    if include_staples:
        for entry in shopping_list.staples:
            lines.append(_format_entry(entry.display_name, entry.amount_text))

    return "\n".join(lines)


def _format_entry(name: str, amount: str) -> str:
    """One item line. "as needed" is dropped — it isn't a quantity Listonic can use."""
    if not amount or amount == "as needed":
        return name
    return f"{name} {amount}"
