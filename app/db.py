"""Database engine, schema creation and the per-request session dependency."""

from collections.abc import Iterator
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

# The models import looks unused, but SQLModel only knows about tables that have
# been imported by the time create_all runs, so this side effect is required.
from app import models  # noqa: F401
from app.config import get_settings


def _make_engine():
    settings = get_settings()
    url = settings.database_url

    # For a file-backed SQLite database, make sure the directory exists before
    # SQLite tries to open it — otherwise the first run fails with an unhelpful
    # "unable to open database file".
    #
    # Stripping the "sqlite:///" prefix handles both forms in one go: a relative
    # URL leaves "data/app.db", and the four-slash absolute form leaves
    # "/data/app.db".
    if url.startswith("sqlite:///") and ":memory:" not in url:
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)

    return create_engine(
        url,
        # FastAPI serves requests from a thread pool, and SQLite objects are
        # otherwise pinned to their creating thread.
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
    )


engine = _make_engine()


def init_db() -> None:
    """Create any missing tables.

    Deliberately not a migration system. The schema is small and this is a
    personal app; if a column ever needs changing, that's the moment to add
    Alembic rather than pretend create_all was ever going to handle it.
    """
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session that closes when the request ends."""
    with Session(engine) as session:
        yield session
