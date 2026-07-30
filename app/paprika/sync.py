"""The unofficial Paprika cloud-sync adapter.

Read this before relying on it. Paprika publishes no API. These endpoints are the
private ones the Paprika apps themselves use, discovered by inspecting their
traffic, and they authenticate with your actual account email and password over
HTTP basic auth. That means:

* it can break at any time, without notice, and that would be entirely fair;
* it sends your real Paprika password to Paprika's servers, which is where it was
  going anyway, but it does mean the credential has to exist in your .env;
* it is read-only here. Nothing in this app writes back to Paprika, so the worst
  a failure can do is fail to import.

Every Paprika-specific network detail is contained in this one module on purpose.
When it does break, this is the only file to fix — and the file-export path in
parse.py keeps working regardless, which is why that one is the default.
"""

from __future__ import annotations

import httpx

from app.config import get_settings
from app.paprika.parse import PaprikaMeal, recipe_from_json

BASE_URL = "https://www.paprikaapp.com/api/v1/sync"

# Generous, because the recipe list is fetched one recipe at a time and a home
# server on a domestic connection is not in a hurry.
TIMEOUT = httpx.Timeout(30.0)


class PaprikaSyncError(RuntimeError):
    """Raised when the sync endpoint can't be used.

    The message is written to be shown to the user, so it must never contain the
    credentials or the raw response body — either could leak the password into a
    log or a rendered page.
    """


def _client() -> httpx.Client:
    settings = get_settings()
    if not settings.paprika_sync_available:
        raise PaprikaSyncError(
            "Paprika sync isn't configured. Add PAPRIKA_EMAIL and PAPRIKA_PASSWORD "
            "to your .env file, or import a .paprikarecipes export instead."
        )
    return httpx.Client(
        base_url=BASE_URL,
        auth=(settings.paprika_email, settings.paprika_password),
        timeout=TIMEOUT,
        headers={"User-Agent": "mealplanner/0.1 (personal use)"},
        follow_redirects=True,
    )


def _result(response: httpx.Response) -> object:
    """Unwrap Paprika's ``{"result": ...}`` envelope with useful errors.

    Note that the response body is never included in the raised message: it can
    echo request details, and this text ends up in front of the user.
    """
    if response.status_code in (401, 403):
        raise PaprikaSyncError(
            "Paprika rejected those credentials. Check PAPRIKA_EMAIL and "
            "PAPRIKA_PASSWORD in your .env file."
        )
    if response.status_code >= 400:
        raise PaprikaSyncError(
            f"Paprika's sync endpoint returned HTTP {response.status_code}. "
            "This is an unofficial API and may have changed — try a file export instead."
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise PaprikaSyncError(
            "Paprika returned something that wasn't JSON. The unofficial sync API "
            "has probably changed."
        ) from exc

    if not isinstance(payload, dict) or "result" not in payload:
        raise PaprikaSyncError(
            "Paprika's response didn't have the expected shape. The unofficial "
            "sync API has probably changed."
        )
    return payload["result"]


def fetch_meals(limit: int | None = None) -> list[PaprikaMeal]:
    """Fetch recipes from Paprika's cloud and reduce them to meals.

    Paprika's sync works in two steps: a cheap index listing every recipe's uid
    and content hash, then one request per recipe. There's no bulk endpoint, so a
    large collection means a lot of small requests — hence ``limit``, which the
    UI uses to keep the first import from taking minutes.
    """
    meals: list[PaprikaMeal] = []

    with _client() as client:
        index = _result(client.get("/recipes/"))
        if not isinstance(index, list):
            raise PaprikaSyncError("Paprika's recipe index wasn't a list.")

        uids = [entry.get("uid") for entry in index if isinstance(entry, dict) and entry.get("uid")]
        if limit is not None:
            uids = uids[:limit]

        for uid in uids:
            try:
                record = _result(client.get(f"/recipe/{uid}/"))
            except PaprikaSyncError:
                # One bad recipe shouldn't abandon the whole import. Skip it and
                # carry on; the user can always fill that one in by hand.
                continue
            if not isinstance(record, dict):
                continue
            meal = recipe_from_json(record)
            if meal:
                meals.append(meal)

    return meals
