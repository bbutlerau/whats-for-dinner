"""Consolidating a week's meals into one shopping list.

The list is pantry-level: it contains what you don't currently have, grouped by
aisle, one line per ingredient no matter how many meals wanted it. Quantities
are combined where they can be combined honestly — same unit, both numeric — and
otherwise listed side by side, because "2 cups + 400 g" is more useful than a
confidently wrong single number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction

from sqlmodel import Session

from app.ingredients import aisles
from app.ingredients.store import effective_item
from app.models import Meal, PantryItem
from app.planner.status import planned_meals


@dataclass
class ShoppingEntry:
    """One line on the shopping list."""

    pantry_item_id: int
    display_name: str
    aisle: str
    is_staple: bool
    amounts: list[str] = field(default_factory=list)
    meals: list[str] = field(default_factory=list)

    @property
    def amount_text(self) -> str:
        return " + ".join(self.amounts)

    @property
    def meal_text(self) -> str:
        return ", ".join(self.meals)


@dataclass
class AisleGroup:
    aisle: aisles.Aisle
    entries: list[ShoppingEntry] = field(default_factory=list)


@dataclass
class ShoppingList:
    """A week's list, split into the things you need and the staples to check."""

    needed: list[AisleGroup] = field(default_factory=list)
    staples: list[ShoppingEntry] = field(default_factory=list)

    @property
    def total_items(self) -> int:
        return sum(len(group.entries) for group in self.needed)

    @property
    def is_empty(self) -> bool:
        return self.total_items == 0 and not self.staples


def _to_number(text: str) -> Fraction | None:
    """Parse "1 1/2", "0.5" or "2" into an exact number, or give up.

    Fraction rather than float so that a third of a cup plus two thirds comes to
    one cup instead of 0.9999999. Ranges like "2-3" deliberately return None:
    they can't be added up meaningfully, so they stay as text.
    """
    text = text.strip()
    if not text:
        return None
    try:
        if " " in text:  # mixed number, e.g. "1 1/2"
            whole, _, frac = text.partition(" ")
            return Fraction(whole) + Fraction(frac)
        return Fraction(text)
    except (ValueError, ZeroDivisionError):
        return None


def _format_number(value: Fraction) -> str:
    """Render a quantity the way a person would write it on a list."""
    if value.denominator == 1:
        return str(value.numerator)
    # Halves and quarters read better as fractions; anything odder as a decimal.
    if value.denominator in (2, 3, 4):
        return str(value)
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def _combine_amounts(raw: list[tuple[str | None, str | None]]) -> list[str]:
    """Merge (quantity, unit) pairs into as few readable amounts as possible.

    Same-unit numeric amounts are summed. Anything that can't be added — a range,
    a missing quantity, a different unit — survives as its own entry rather than
    being dropped, since a shopping list that quietly loses an amount is worse
    than a slightly untidy one.
    """
    totals: dict[str, Fraction] = {}
    literals: list[str] = []
    bare_count = 0

    for quantity, unit in raw:
        unit_key = unit or ""
        number = _to_number(quantity) if quantity else None

        if quantity is None:
            bare_count += 1
            continue
        if number is None:
            literals.append(" ".join(part for part in (quantity, unit) if part))
            continue
        totals[unit_key] = totals.get(unit_key, Fraction(0)) + number

    amounts: list[str] = []
    for unit_key, total in totals.items():
        rendered = _format_number(total)
        amounts.append(f"{rendered} {unit_key}".strip())
    amounts.extend(literals)

    # Ingredients written without any quantity ("salt", "olive oil") contribute
    # nothing to add up. If that's all there was, say so plainly.
    if not amounts and bare_count:
        amounts.append("as needed")
    return amounts


def build_list(session: Session, days: list[date]) -> ShoppingList:
    """Build the shopping list for the meals planned across ``days``."""
    meals: list[Meal] = planned_meals(session, days)

    # Keyed by the *resolved* pantry item, so an alias-merged ingredient shows up
    # once under the name it was merged into.
    entries: dict[int, ShoppingEntry] = {}
    raw_amounts: dict[int, list[tuple[str | None, str | None]]] = {}

    for meal in meals:
        for line in meal.ingredients:
            item = session.get(PantryItem, line.pantry_item_id)
            if item is None:
                continue
            resolved = effective_item(session, item)
            if resolved.in_stock:
                # Already have it — nothing to buy.
                continue

            entry = entries.get(resolved.id)
            if entry is None:
                entry = ShoppingEntry(
                    pantry_item_id=resolved.id,
                    display_name=resolved.display_name,
                    aisle=resolved.aisle or aisles.classify(resolved.base_name, resolved.form),
                    is_staple=item.is_staple or resolved.is_staple,
                )
                entries[resolved.id] = entry
                raw_amounts[resolved.id] = []

            raw_amounts[resolved.id].append((line.quantity, line.unit))
            if meal.name not in entry.meals:
                entry.meals.append(meal.name)

    for item_id, entry in entries.items():
        entry.amounts = _combine_amounts(raw_amounts[item_id])

    # Staples sit in their own quiet section rather than padding out the aisles.
    staples = sorted(
        (e for e in entries.values() if e.is_staple), key=lambda e: e.display_name
    )

    grouped: dict[str, AisleGroup] = {}
    for entry in entries.values():
        if entry.is_staple:
            continue
        group = grouped.setdefault(entry.aisle, AisleGroup(aisle=aisles.aisle_for(entry.aisle)))
        group.entries.append(entry)

    for group in grouped.values():
        group.entries.sort(key=lambda e: e.display_name)

    needed = sorted(grouped.values(), key=lambda g: g.aisle.order)
    return ShoppingList(needed=needed, staples=staples)
