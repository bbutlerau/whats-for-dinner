"""Reading Paprika's export format and its recipe JSON.

A ``.paprikarecipes`` file is a zip archive containing one ``.paprikarecipe``
member per recipe, and each of those is a gzip-compressed JSON object. Both the
file export and the sync API hand over the same JSON shape, so both paths share
``recipe_from_json`` below and there's only one place where Paprika's field names
appear.

Pure functions only — no network, no database — so this is all directly testable.
"""

from __future__ import annotations

import gzip
import io
import json
import re
import zipfile
from dataclasses import dataclass, field

# "1 hr 20 min", "45 mins", "1 hour 5 minutes" — Paprika stores times as free
# text typed by whoever entered the recipe, so this stays forgiving.
_HOURS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\b", re.IGNORECASE)
_MINUTES_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:m|min|mins|minute|minutes)\b", re.IGNORECASE)


@dataclass
class PaprikaMeal:
    """The only parts of a Paprika recipe this app keeps."""

    uid: str
    name: str
    ingredient_lines: list[str] = field(default_factory=list)
    prep_minutes: int | None = None


def parse_duration(text: str | None) -> int | None:
    """Turn a Paprika time string into minutes, or None if it says nothing useful."""
    if not text:
        return None

    total = 0.0
    found = False

    for match in _HOURS_RE.finditer(text):
        total += float(match.group(1)) * 60
        found = True
    for match in _MINUTES_RE.finditer(text):
        total += float(match.group(1))
        found = True

    if not found:
        # A bare number is the common case for someone who typed just "30".
        bare = re.fullmatch(r"\s*(\d+)\s*", text)
        if bare:
            return int(bare.group(1))
        return None

    minutes = int(round(total))
    return minutes or None


def split_ingredients(blob: str | None) -> list[str]:
    """Split Paprika's ingredients field into individual lines.

    Paprika stores them as one newline-separated string, and users commonly
    include blank lines and section headers like "For the sauce:". Headers end in
    a colon and carry no ingredient, so they're dropped.
    """
    if not blob:
        return []

    lines: list[str] = []
    for raw in blob.splitlines():
        line = raw.strip().lstrip("-•*").strip()
        if not line:
            continue
        if line.endswith(":"):
            continue
        lines.append(line)
    return lines


def recipe_from_json(data: dict) -> PaprikaMeal | None:
    """Extract a meal from one Paprika recipe object.

    Returns None for anything unusable — an unnamed recipe, or one Paprika has
    flagged as deleted in the sync feed. Recipes with no ingredients are still
    kept, since a name and a prep time on the calendar is already useful and the
    ingredients can be filled in by hand.
    """
    if data.get("deleted"):
        return None

    name = (data.get("name") or "").strip()
    if not name:
        return None

    # Prep and cook time are separate fields; what matters on the calendar is the
    # total commitment, so they're added together.
    prep = parse_duration(data.get("prep_time"))
    cook = parse_duration(data.get("cook_time"))
    total = (prep or 0) + (cook or 0)

    return PaprikaMeal(
        uid=(data.get("uid") or "").strip(),
        name=name,
        ingredient_lines=split_ingredients(data.get("ingredients")),
        prep_minutes=total or None,
    )


def decode_recipe_member(blob: bytes) -> dict:
    """Decompress one ``.paprikarecipe`` member into its JSON object.

    Older exports are occasionally stored uncompressed, so a gzip failure falls
    back to reading the bytes as plain JSON rather than rejecting the file.
    """
    try:
        raw = gzip.decompress(blob)
    except (OSError, EOFError):
        raw = blob
    return json.loads(raw.decode("utf-8"))


def meals_from_export(file_bytes: bytes) -> list[PaprikaMeal]:
    """Read every recipe out of a ``.paprikarecipes`` archive.

    A single corrupt member shouldn't cost you the whole import, so unreadable
    entries are skipped quietly and everything else comes through.
    """
    meals: list[PaprikaMeal] = []

    with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
        for member in archive.namelist():
            if member.endswith("/"):
                continue
            try:
                data = decode_recipe_member(archive.read(member))
            except (OSError, ValueError, UnicodeDecodeError):
                continue

            # A single-recipe .paprikarecipe file zipped up on its own is
            # occasionally a bare list rather than an object.
            records = data if isinstance(data, list) else [data]
            for record in records:
                if not isinstance(record, dict):
                    continue
                meal = recipe_from_json(record)
                if meal:
                    meals.append(meal)

    return meals
