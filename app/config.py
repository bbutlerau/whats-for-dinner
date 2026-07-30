"""Application settings, read from the environment (and .env when present).

Everything configurable lives here so that no module has to reach for os.environ
directly. The Paprika credentials in particular are read through this one place,
which makes it easy to reason about where they can leak to: nowhere else.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./data/mealplanner.db"

    # Optional Paprika sync credentials. Blank means the feature is off, which is
    # the default: the app is fully usable with manual entry and file import only.
    paprika_email: str = ""
    paprika_password: str = ""

    dev_reload: bool = False

    @property
    def paprika_sync_available(self) -> bool:
        """True only when both halves of the credential are present.

        Checked before showing the sync button, so a half-filled .env quietly
        disables the feature rather than producing a confusing auth failure.
        """
        return bool(self.paprika_email and self.paprika_password)


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is parsed once per process, not per request."""
    return Settings()
