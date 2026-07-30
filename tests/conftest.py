"""Shared test fixtures.

Each test gets its own in-memory database, so tests can't leak state into one
another and nothing ever touches the real data/ directory.
"""

from __future__ import annotations

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.ingredients.store import resolve_line
from app.models import SOURCE_MANUAL, Meal, MealIngredient


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        # StaticPool keeps the one in-memory database alive across connections;
        # without it each connection would get its own empty database.
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="make_meal")
def make_meal_fixture(session: Session):
    """Build a meal from raw ingredient lines, the same way the form route does.

    Fixture data is invented rather than taken from a real collection, per the
    project's rule about test data not resembling anything personal.
    """

    def _make(name: str, lines: list[str], prep_minutes: int | None = 20) -> Meal:
        meal = Meal(name=name, prep_minutes=prep_minutes, source=SOURCE_MANUAL)
        session.add(meal)
        session.flush()

        for position, raw in enumerate(lines):
            parsed, item = resolve_line(session, raw)
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
        session.commit()
        session.refresh(meal)
        return meal

    return _make
