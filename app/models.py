"""Database models.

The shape here follows one rule: a *pantry item* is the unit of "do we have it?",
and a *meal ingredient* is just a line of text that points at one. That split is
what lets "2 cloves garlic, crushed" in one meal and "1 tsp garlic" in another
share a single in-stock flag, while keeping the original wording for the shopping
list and for editing.
"""

from datetime import UTC, date, datetime

from sqlmodel import Field, Relationship, SQLModel

# Where a meal came from. Manual meals are equal citizens: a Paprika re-import is
# never allowed to touch them, which is why the source is stored rather than
# inferred from whether paprika_uid happens to be set.
SOURCE_MANUAL = "manual"
SOURCE_PAPRIKA = "paprika"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PantryItem(SQLModel, table=True):
    """One thing you either have or don't have.

    ``key`` is the normalised identity produced by app.ingredients.normalise and
    includes the form qualifier, so "fresh basil" and "dried basil" are two rows
    with independent stock. That separation is deliberate and load-bearing.
    """

    id: int | None = Field(default=None, primary_key=True)

    # Normalised, unique, and never shown to the user — e.g. "dried basil".
    key: str = Field(index=True, unique=True)

    # What the user sees, e.g. "Dried basil".
    display_name: str

    # The identity split into its parts, kept so the pantry UI can group and
    # sort sensibly ("basil" with form "dried") without re-parsing the key.
    base_name: str = ""
    form: str = ""  # "", "fresh", "dried", "frozen", "tinned"

    aisle: str = "other"

    in_stock: bool = Field(default=False, index=True)

    # Staples are excluded from the missing-ingredient check that drives the
    # calendar colours. Salt shouldn't make Tuesday look like a problem.
    is_staple: bool = Field(default=False, index=True)

    # Set when the user merges this item into another ("treat 'basil' as
    # 'dried basil'"). Stock is then read from the target instead of this row.
    # The app collapses chains on write, so this is only ever one hop deep.
    alias_of_id: int | None = Field(default=None, foreign_key="pantryitem.id", index=True)

    created_at: datetime = Field(default_factory=_utcnow)


class SubstitutionRule(SQLModel, table=True):
    """A remembered "this name always means that item" decision.

    An alias on a PantryItem merges one existing row into another. This is the
    standing order that outlives it: when a future import creates a brand new
    item whose key is ``source_key``, merge it into ``target_key`` without
    asking again. That's right for a genuine synonym — cilantro is coriander,
    always — which is why saving the rule is the default when merging.

    It is emphatically not right for a line like "basil or parsley", where the
    answer is a cook's choice that changes with the meal. Those merges are made
    without saving a rule, which is what the checkbox on the merge form is for.

    Keys rather than ids on purpose: a rule has to apply to rows that don't
    exist yet, and it should survive a target being deleted and recreated by a
    later import.
    """

    id: int | None = Field(default=None, primary_key=True)

    source_key: str = Field(index=True, unique=True)
    target_key: str = Field(index=True)

    created_at: datetime = Field(default_factory=_utcnow)


class Meal(SQLModel, table=True):
    """A dinner you can put on the calendar."""

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)

    # Total hands-on time in minutes. Optional because plenty of meals don't
    # have a meaningful number and a made-up one is worse than a blank.
    prep_minutes: int | None = None

    source: str = Field(default=SOURCE_MANUAL, index=True)

    # Paprika's own identifier, used to update rather than duplicate a recipe on
    # re-import. Null for manual meals.
    paprika_uid: str | None = Field(default=None, index=True, unique=True)

    created_at: datetime = Field(default_factory=_utcnow)

    ingredients: list["MealIngredient"] = Relationship(
        back_populates="meal",
        # Deleting a meal should take its ingredient lines with it. Without this
        # SQLModel leaves orphan rows behind that quietly pollute later queries.
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "order_by": "MealIngredient.position",
        },
    )


class MealIngredient(SQLModel, table=True):
    """One ingredient line belonging to one meal.

    The original text is kept verbatim. Quantity and unit are pulled out for the
    shopping list, and everything is resolved to a pantry item for the stock
    check, but the raw line stays authoritative for display and editing.
    """

    id: int | None = Field(default=None, primary_key=True)
    meal_id: int = Field(foreign_key="meal.id", index=True)

    raw_text: str
    quantity: str | None = None  # kept as text: "1 1/2" and "2-3" both matter
    unit: str | None = None

    pantry_item_id: int = Field(foreign_key="pantryitem.id", index=True)

    # Preserves the order the ingredients were entered in.
    position: int = 0

    meal: Meal | None = Relationship(back_populates="ingredients")


class PlanEntry(SQLModel, table=True):
    """What's for dinner on a given date.

    One row per date, enforced by the unique index, because this app plans a
    single dinner per night. Clearing a night deletes the row rather than
    storing a null meal, so an empty calendar is genuinely empty.
    """

    id: int | None = Field(default=None, primary_key=True)
    day: date = Field(index=True, unique=True)
    meal_id: int = Field(foreign_key="meal.id", index=True)
