"""Working out the colour of a night on the calendar.

The whole app exists to answer one question at a glance: what's for dinner, and
have we got everything for it. That answer is a single status per night:

    green   every non-staple ingredient is in the pantry
    amber   the real ingredients are covered, but a staple is unaccounted for
    red     something you'd actually have to buy is missing
    grey    nothing planned

Staples are held apart deliberately. If salt and olive oil counted, every night
would be amber forever and the colour would stop meaning anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlmodel import Session, select

from app.ingredients.store import effective_item
from app.models import Meal, MealIngredient, PantryItem, PlanEntry

GREEN = "green"
AMBER = "amber"
RED = "red"
GREY = "grey"

STATUS_LABELS = {
    GREEN: "Ready to cook",
    AMBER: "Check staples",
    RED: "Missing ingredients",
    GREY: "Nothing planned",
}


@dataclass
class MealStatus:
    """The stock verdict for one meal."""

    status: str
    missing: list[str] = field(default_factory=list)          # non-staples, drives red
    missing_staples: list[str] = field(default_factory=list)   # drives amber

    @property
    def label(self) -> str:
        return STATUS_LABELS[self.status]

    @property
    def summary(self) -> str:
        """Short line shown under the meal name on the calendar."""
        if self.status == RED:
            shown = ", ".join(self.missing[:3])
            extra = len(self.missing) - 3
            return f"Need {shown}" + (f" +{extra} more" if extra > 0 else "")
        if self.status == AMBER:
            return "Check " + ", ".join(self.missing_staples[:3])
        if self.status == GREEN:
            return "Got everything"
        return ""


@dataclass
class Night:
    """One cell of the week grid."""

    day: date
    meal: Meal | None
    status: MealStatus

    @property
    def is_planned(self) -> bool:
        return self.meal is not None


def status_for_meal(session: Session, meal: Meal) -> MealStatus:
    """Check a meal's ingredients against the pantry."""
    missing: list[str] = []
    missing_staples: list[str] = []

    for line in meal.ingredients:
        item = session.get(PantryItem, line.pantry_item_id)
        if item is None:
            # Shouldn't happen — the foreign key prevents it — but a missing row
            # should never crash the calendar.
            continue
        resolved = effective_item(session, item)
        if resolved.in_stock:
            continue
        # The staple flag is read from the item as written, not the alias target,
        # since that's the row the user ticked.
        if item.is_staple or resolved.is_staple:
            missing_staples.append(resolved.display_name.lower())
        else:
            missing.append(resolved.display_name.lower())

    if missing:
        status = RED
    elif missing_staples:
        status = AMBER
    else:
        status = GREEN

    return MealStatus(status=status, missing=missing, missing_staples=missing_staples)


def build_week(session: Session, days: list[date]) -> list[Night]:
    """Assemble the calendar cells for a list of dates.

    Plan entries and meals are fetched in two queries rather than one per day,
    because a seven-times-repeated query is a habit worth not forming even when
    the data is this small.
    """
    entries = session.exec(select(PlanEntry).where(PlanEntry.day.in_(days))).all()
    by_day = {entry.day: entry for entry in entries}

    meal_ids = {entry.meal_id for entry in entries}
    meals: dict[int, Meal] = {}
    if meal_ids:
        for meal in session.exec(select(Meal).where(Meal.id.in_(meal_ids))).all():
            meals[meal.id] = meal

    nights: list[Night] = []
    for day in days:
        entry = by_day.get(day)
        meal = meals.get(entry.meal_id) if entry else None
        if meal is None:
            nights.append(Night(day=day, meal=None, status=MealStatus(status=GREY)))
        else:
            nights.append(Night(day=day, meal=meal, status=status_for_meal(session, meal)))
    return nights


def planned_meals(session: Session, days: list[date]) -> list[Meal]:
    """Every distinct meal planned across the given dates.

    Distinct matters: cooking the same thing twice in a week shouldn't put its
    ingredients on the shopping list twice.
    """
    entries = session.exec(select(PlanEntry).where(PlanEntry.day.in_(days))).all()
    meal_ids = {entry.meal_id for entry in entries}
    if not meal_ids:
        return []
    return list(session.exec(select(Meal).where(Meal.id.in_(meal_ids))).all())


def ingredient_lines_for(session: Session, meals: list[Meal]) -> list[MealIngredient]:
    """Flatten the ingredient lines of several meals into one list."""
    lines: list[MealIngredient] = []
    for meal in meals:
        lines.extend(meal.ingredients)
    return lines


def pantry_item_ids_for_days(session: Session, days: list[date]) -> set[int]:
    """The pantry items the meals planned across ``days`` actually need.

    Aliases are resolved on the way out, so an ingredient merged into another
    item contributes its target's id. Without that, merging `basil` into
    `dried basil` would make the row vanish from a filtered pantry even though
    that is exactly the item the week depends on.
    """
    ids: set[int] = set()
    for line in ingredient_lines_for(session, planned_meals(session, days)):
        item = session.get(PantryItem, line.pantry_item_id)
        if item is None:
            continue
        resolved = effective_item(session, item)
        if resolved.id is not None:
            ids.add(resolved.id)
    return ids
