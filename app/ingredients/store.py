"""Turning parsed ingredient lines into rows in the pantry table.

Separate from normalise.py on purpose: that module is pure text handling and
easy to test, this one is the thin layer that talks to the database.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from sqlmodel import Session, select

from app.ingredients import aisles, synonyms
from app.ingredients.normalise import ParsedIngredient, parse_line
from app.models import PantryItem, SubstitutionRule

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

    # A saved substitution applies the moment the item comes into existence, so
    # an import that introduces "cilantro" lands already merged into coriander
    # rather than showing up as a separate thing to buy.
    _apply_substitution_rule(session, item)
    return item


def _apply_substitution_rule(session: Session, item: PantryItem) -> None:
    """Merge a newly created item if a saved rule says where it belongs."""
    rule = session.exec(
        select(SubstitutionRule).where(SubstitutionRule.source_key == item.key)
    ).first()
    if rule is None:
        return

    target = session.exec(select(PantryItem).where(PantryItem.key == rule.target_key)).first()
    if target is None:
        # The rule outlived its target. Leave the item alone rather than
        # inventing a row: the rule will take effect if the target returns.
        return

    set_alias(session, item, target)
    session.flush()


def remember_substitution(session: Session, item: PantryItem, target: PantryItem) -> None:
    """Save "this name always means that item" for future imports.

    Re-pointing an existing rule rather than adding a second one keeps
    source_key unique, so a corrected decision replaces the earlier one instead
    of leaving two rules to race.
    """
    existing = session.exec(
        select(SubstitutionRule).where(SubstitutionRule.source_key == item.key)
    ).first()
    if existing:
        existing.target_key = target.key
        session.add(existing)
        return
    session.add(SubstitutionRule(source_key=item.key, target_key=target.key))


def forget_substitution(session: Session, item: PantryItem) -> None:
    """Drop any saved rule for this item, used when a merge is undone."""
    existing = session.exec(
        select(SubstitutionRule).where(SubstitutionRule.source_key == item.key)
    ).first()
    if existing:
        session.delete(existing)


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


# How close two names must look before the pantry will offer them as a possible
# merge. Deliberately high: "carrot" and "parrot" score 0.83, so anything looser
# starts proposing nonsense. At this cutoff the fuzzy arm only catches genuine
# misspellings ("corriander"), and real synonyms come from the hand-written
# table in synonyms.py instead, because no similarity score can find those.
SUGGESTION_CUTOFF = 0.9


def suggest_merge_targets(
    session: Session, item: PantryItem, candidates: list[PantryItem], limit: int = 3
) -> list[PantryItem]:
    """Pantry items that ``item`` might be the same thing as, best first.

    Two signals, because the two cases look nothing alike. A bare "basil" and
    "dried basil" are not a close string match at all — one contains the other,
    which is the form-qualifier case the app deliberately refuses to guess on
    import. "Cilantro" and "coriander" aren't similar either, but a genuine
    synonym typed slightly differently ("corriander") is, and that's what
    difflib catches.

    Suggestions only ever reorder the picker. Nothing here merges anything: the
    domain rule that an unqualified ingredient never silently matches a
    qualified one still holds, and the user confirms every merge by hand.
    """
    scored: list[tuple[float, str, PantryItem]] = []

    for other in candidates:
        if other.id == item.id or other.alias_of_id is not None:
            continue

        score = 0.0

        # Same base name, different form — "basil" against "dried basil". The
        # strongest signal there is, and the one the merge feature exists for.
        if other.base_name and other.base_name == item.base_name:
            score = 1.0
        elif synonyms.are_synonyms(item.base_name, other.base_name):
            # A known synonym is as certain as an exact match; it just needed
            # telling. Ranked a shade below so that when both are present, the
            # form variant of the very same word comes first.
            score = 0.99
        elif _shares_a_word(item.base_name, other.base_name):
            score = 0.95
        else:
            ratio = SequenceMatcher(None, item.base_name, other.base_name).ratio()
            if ratio >= SUGGESTION_CUTOFF:
                score = ratio

        if score:
            # display_name is the tiebreaker purely so the order is stable
            # between requests rather than wandering with row order.
            scored.append((score, other.display_name, other))

    scored.sort(key=lambda row: (-row[0], row[1]))
    return [other for _, _, other in scored[:limit]]


def _shares_a_word(left: str, right: str) -> bool:
    """Whether one name's words wholly contain the other's.

    Word-level rather than substring so that "corn" doesn't claim to match
    "cornflour", which is a different thing to own.
    """
    if not left or not right:
        return False
    left_words = set(left.split())
    right_words = set(right.split())
    return left_words <= right_words or right_words <= left_words
