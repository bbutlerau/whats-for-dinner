"""Writing imported Paprika meals into the database.

Shared by both the file-export and sync paths so there is exactly one place where
import rules live. The important rule: a manually created meal is never touched.
If you typed it, it's yours, and a re-import can't overwrite it.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, select

from app.ingredients.store import resolve_line
from app.models import SOURCE_MANUAL, SOURCE_PAPRIKA, Meal, MealIngredient
from app.paprika.parse import PaprikaMeal


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    skipped_manual: int = 0

    @property
    def summary(self) -> str:
        parts = []
        if self.created:
            parts.append(f"{self.created} added")
        if self.updated:
            parts.append(f"{self.updated} updated")
        if self.skipped_manual:
            parts.append(f"{self.skipped_manual} skipped (you'd edited them by hand)")
        return ", ".join(parts) if parts else "nothing to import"


def _replace_ingredients(session: Session, meal: Meal, lines: list[str]) -> None:
    """Swap a meal's ingredient lines for a fresh set.

    Ingredient lines are cheap and derived, so replacing them wholesale is
    simpler and less error-prone than diffing — and it means a corrected recipe
    in Paprika actually takes effect. The pantry items they point at are shared
    and long-lived, so nothing about stock state is lost in the process.
    """
    for existing in list(meal.ingredients):
        session.delete(existing)
    meal.ingredients.clear()
    session.flush()

    for position, raw in enumerate(lines):
        parsed, item = resolve_line(session, raw)
        if not item.key:
            continue
        session.add(
            MealIngredient(
                meal_id=meal.id,
                raw_text=parsed.raw_text,
                quantity=parsed.quantity,
                unit=parsed.unit,
                pantry_item_id=item.id,
                position=position,
            )
        )


def import_meals(session: Session, meals: list[PaprikaMeal]) -> ImportResult:
    """Import or refresh a batch of Paprika meals."""
    result = ImportResult()

    for incoming in meals:
        existing: Meal | None = None

        if incoming.uid:
            existing = session.exec(
                select(Meal).where(Meal.paprika_uid == incoming.uid)
            ).first()

        # Fall back to matching on name, which catches recipes imported before
        # from a file export that didn't carry a uid.
        if existing is None:
            existing = session.exec(select(Meal).where(Meal.name == incoming.name)).first()

        if existing is not None and existing.source == SOURCE_MANUAL:
            # Hands off. This is the guarantee that typing a meal in by hand is
            # safe even if Paprika has something by the same name.
            result.skipped_manual += 1
            continue

        if existing is None:
            meal = Meal(
                name=incoming.name,
                prep_minutes=incoming.prep_minutes,
                source=SOURCE_PAPRIKA,
                paprika_uid=incoming.uid or None,
            )
            session.add(meal)
            session.flush()
            result.created += 1
        else:
            meal = existing
            meal.name = incoming.name
            meal.prep_minutes = incoming.prep_minutes
            meal.paprika_uid = incoming.uid or meal.paprika_uid
            session.add(meal)
            session.flush()
            result.updated += 1

        _replace_ingredients(session, meal, incoming.ingredient_lines)

    session.commit()
    return result
