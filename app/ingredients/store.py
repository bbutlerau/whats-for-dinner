"""Turning parsed ingredient lines into rows in the pantry table.

Separate from normalise.py on purpose: that module is pure text handling and
easy to test, this one is the thin layer that talks to the database.
"""

from __future__ import annotations

from sqlmodel import Session, select

from app.ingredients import aisles
from app.ingredients.normalise import ParsedIngredient, parse_line
from app.models import PantryItem

# Things almost nobody wants driving the calendar colours. A new pantry item
# matching one of these starts life flagged as a staple; the user can always
# untick that, and the flag is never reapplied afterwards.
STAPLE_KEYWORDS = frozenset({
    "salt", "pepper", "peppercorn", "olive oil", "oil", "vegetable oil",
    "sugar", "flour", "water", "butter", "baking powder", "bicarb",
    "baking soda", "cornflour", "vinegar", "stock", "stock cube",
})


def _looks_like_staple(base_name: str) -> bool:
    name = base_name.lower()
    return any(keyword in name for keyword in STAPLE_KEYWORDS)


def resolve_pantry_item(session: Session, parsed: ParsedIngredient) -> PantryItem:
    """Find the pantry item for a parsed line, creating it if it's new.

    The lookup is by normalised key, so every meal that mentions garlic ends up
    pointing at the same row and shares its in-stock flag.
    """
    key = parsed.key
    existing = session.exec(select(PantryItem).where(PantryItem.key == key)).first()
    if existing:
        return existing

    item = PantryItem(
        key=key,
        display_name=parsed.display_name,
        base_name=parsed.base_name,
        form=parsed.form,
        aisle=aisles.classify(parsed.base_name, parsed.form),
        # New items start out as "don't have". Assuming otherwise would show a
        # green meal you can't actually cook, which is the exact failure this
        # app is meant to prevent.
        in_stock=False,
        is_staple=_looks_like_staple(parsed.base_name),
    )
    session.add(item)
    # Flushed rather than committed so the caller controls the transaction, but
    # the new row still gets its primary key for the foreign key below.
    session.flush()
    return item


def resolve_line(session: Session, raw: str) -> tuple[ParsedIngredient, PantryItem]:
    """Parse a raw ingredient line and attach it to a pantry item."""
    parsed = parse_line(raw)
    return parsed, resolve_pantry_item(session, parsed)


def effective_item(session: Session, item: PantryItem) -> PantryItem:
    """Follow an alias to the item that actually holds the stock flag.

    Aliases are collapsed on write so this is only ever one hop, but the guard
    against a self-reference is cheap and saves a puzzling infinite loop if a
    row is ever edited by hand.
    """
    if item.alias_of_id is None or item.alias_of_id == item.id:
        return item
    target = session.get(PantryItem, item.alias_of_id)
    return target or item


def is_in_stock(session: Session, item: PantryItem) -> bool:
    """Whether we have this ingredient, respecting alias merges."""
    return effective_item(session, item).in_stock


def set_alias(session: Session, item: PantryItem, target: PantryItem | None) -> None:
    """Merge ``item`` into ``target`` (or clear the merge when target is None).

    Two things are worth being careful about here. Aliasing an item to itself
    would make the stock lookup meaningless, and aliasing to something that is
    itself an alias would build a chain — so the target is resolved first and
    any existing aliases pointing at ``item`` are re-pointed at the new target.
    """
    if target is None:
        item.alias_of_id = None
        session.add(item)
        return

    final = effective_item(session, target)
    if final.id == item.id:
        # Would create a cycle; treat as a no-op rather than corrupting the data.
        return

    item.alias_of_id = final.id
    session.add(item)

    # Anything that pointed at item now points at final, keeping every chain
    # exactly one hop long.
    for follower in session.exec(
        select(PantryItem).where(PantryItem.alias_of_id == item.id)
    ).all():
        follower.alias_of_id = final.id
        session.add(follower)
