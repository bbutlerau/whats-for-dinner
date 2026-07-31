"""FastAPI application: routes, templates, and the small amount of glue between.

Everything here is deliberately thin. The interesting logic lives in
app/ingredients, app/planner and app/shopping, which are all testable without a
web server; these handlers just move data between forms and templates.

There's no authentication. That's a considered choice for a personal app reached
over Tailscale, where the network is the perimeter — but it does mean this must
never be exposed directly to the internet.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app import __version__
from app.config import get_settings
from app.db import get_session, init_db
from app.ingredients import aisles
from app.ingredients.store import (
    forget_substitution,
    remember_substitution,
    resolve_line,
    set_alias,
    suggest_merge_targets,
)
from app.models import SOURCE_MANUAL, Meal, MealIngredient, PantryItem, PlanEntry
from app.paprika import sync as paprika_sync
from app.paprika.importer import import_meals
from app.paprika.parse import meals_from_export
from app.planner import week as week_util
from app.planner.status import build_week, pantry_item_ids_for_days, status_for_meal
from app.shopping import listonic
from app.shopping.list import build_list

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Meal Planner", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Made available to every template so the aisle emoji can be rendered anywhere.
templates.env.globals["aisle_for"] = aisles.aisle_for
# Every page footer shows the running version, so "did the pull actually land?"
# is answerable from the phone rather than by SSHing into the server.
templates.env.globals["version"] = __version__


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/healthz", response_class=PlainTextResponse)
def healthz() -> str:
    """Used by the Docker healthcheck."""
    return "ok"


def _parse_start(value: str | None) -> date:
    """Resolve the ?start= query parameter to the Monday of a week.

    Anything unparseable falls back to this week rather than erroring — a
    hand-mangled URL should show you the calendar, not a stack trace.
    """
    if value:
        try:
            return week_util.week_start(datetime.strptime(value, "%Y-%m-%d").date())
        except ValueError:
            pass
    return week_util.week_start(date.today())


def _parse_day(value: str | None) -> date | None:
    """One ?start=/?end= date, or None if absent or unparseable."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


# How far ahead the pantry looks when you haven't said otherwise. Seven days
# from today rather than the calendar's Monday-anchored week: on a Thursday you
# care about the next week of dinners, not the three nights left in this one.
PANTRY_RANGE_DAYS = 7


def _parse_range(start: str | None, end: str | None) -> tuple[date, date]:
    """Resolve the pantry's date range, filling in whichever end is missing.

    Like _parse_start, bad input falls back to the default rather than erroring.
    A range given backwards is swapped instead of rejected, which is what
    someone fumbling two date pickers on a phone actually meant.
    """
    today = date.today()
    range_start = _parse_day(start) or today
    range_end = _parse_day(end) or range_start + timedelta(days=PANTRY_RANGE_DAYS)
    if range_end < range_start:
        range_start, range_end = range_end, range_start
    return range_start, range_end


# --- Calendar --------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def calendar(
    request: Request,
    start: str | None = None,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """The week grid. This is the app's front door and main screen."""
    week_start = _parse_start(start)
    days = week_util.week_days(week_start)
    nights = build_week(session, days)

    # Sorted by name because the meal picker is a plain select and alphabetical
    # is the only ordering that stays predictable as the collection grows.
    meals = session.exec(select(Meal).order_by(Meal.name)).all()

    return templates.TemplateResponse(
        request,
        "calendar.html",
        {
            "nights": nights,
            "meals": meals,
            "week_start": week_start,
            "week_label": week_util.describe_week(week_start),
            "prev_week": week_util.shift_weeks(week_start, -1),
            "next_week": week_util.shift_weeks(week_start, 1),
            "today": date.today(),
        },
    )


@app.post("/plan/{day}")
def set_night(
    day: str,
    meal_id: int = Form(...),
    start: str = Form(""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """Assign a meal to a night, replacing whatever was there."""
    try:
        target = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid date") from exc

    if session.get(Meal, meal_id) is None:
        raise HTTPException(status_code=404, detail="Meal not found")

    existing = session.exec(select(PlanEntry).where(PlanEntry.day == target)).first()
    if existing:
        existing.meal_id = meal_id
        session.add(existing)
    else:
        session.add(PlanEntry(day=target, meal_id=meal_id))
    session.commit()

    return RedirectResponse(f"/?start={start or target.isoformat()}", status_code=303)


@app.post("/plan/{day}/clear")
def clear_night(
    day: str,
    start: str = Form(""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """Empty a night. The row is deleted so an unplanned night is truly absent."""
    try:
        target = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid date") from exc

    existing = session.exec(select(PlanEntry).where(PlanEntry.day == target)).first()
    if existing:
        session.delete(existing)
        session.commit()

    return RedirectResponse(f"/?start={start or target.isoformat()}", status_code=303)


# --- Meals -----------------------------------------------------------------

@app.get("/meals", response_class=HTMLResponse)
def meal_list(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    meals = session.exec(select(Meal).order_by(Meal.name)).all()
    statuses = {meal.id: status_for_meal(session, meal) for meal in meals}
    return templates.TemplateResponse(
        request, "meals.html", {"meals": meals, "statuses": statuses}
    )


@app.get("/meals/new", response_class=HTMLResponse)
def new_meal_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "meal_form.html", {"meal": None, "ingredients": [], "heading": "Add a meal"}
    )


@app.get("/meals/{meal_id}/edit", response_class=HTMLResponse)
def edit_meal_form(
    meal_id: int, request: Request, session: Session = Depends(get_session)
) -> HTMLResponse:
    meal = session.get(Meal, meal_id)
    if meal is None:
        raise HTTPException(status_code=404, detail="Meal not found")
    return templates.TemplateResponse(
        request,
        "meal_form.html",
        {
            "meal": meal,
            "ingredients": [line.raw_text for line in meal.ingredients],
            "heading": f"Edit {meal.name}",
        },
    )


def _save_ingredients(session: Session, meal: Meal, raw_lines: list[str]) -> None:
    """Replace a meal's ingredient lines from submitted form rows.

    Blank rows are dropped rather than validated against, because the "+ add
    ingredient" button makes it easy to leave a stray empty row behind and
    refusing to save over that would be needlessly annoying.
    """
    for existing in list(meal.ingredients):
        session.delete(existing)
    meal.ingredients.clear()
    session.flush()

    position = 0
    for raw in raw_lines:
        text = raw.strip()
        if not text:
            continue
        parsed, item = resolve_line(session, text)
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
        position += 1


@app.post("/meals")
def create_meal(
    name: str = Form(...),
    prep_minutes: str = Form(""),
    ingredient: list[str] = Form(default=[]),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """Save a hand-entered meal.

    ``ingredient`` arrives as a repeated form field, one per row added with the
    "+ add ingredient" button, which is why it's a list.
    """
    meal_name = name.strip()
    if not meal_name:
        raise HTTPException(status_code=400, detail="A meal needs a name")

    meal = Meal(
        name=meal_name,
        prep_minutes=_parse_minutes(prep_minutes),
        source=SOURCE_MANUAL,
    )
    session.add(meal)
    session.flush()

    _save_ingredients(session, meal, ingredient)
    session.commit()
    return RedirectResponse("/meals", status_code=303)


@app.post("/meals/{meal_id}")
def update_meal(
    meal_id: int,
    name: str = Form(...),
    prep_minutes: str = Form(""),
    ingredient: list[str] = Form(default=[]),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    meal = session.get(Meal, meal_id)
    if meal is None:
        raise HTTPException(status_code=404, detail="Meal not found")

    meal.name = name.strip() or meal.name
    meal.prep_minutes = _parse_minutes(prep_minutes)
    # Editing a Paprika-imported meal makes it yours, which protects your changes
    # from being flattened by the next import.
    meal.source = SOURCE_MANUAL
    session.add(meal)
    session.flush()

    _save_ingredients(session, meal, ingredient)
    session.commit()
    return RedirectResponse("/meals", status_code=303)


@app.post("/meals/{meal_id}/delete")
def delete_meal(meal_id: int, session: Session = Depends(get_session)) -> RedirectResponse:
    """Delete a meal, and any calendar nights that referenced it."""
    meal = session.get(Meal, meal_id)
    if meal is None:
        raise HTTPException(status_code=404, detail="Meal not found")

    # Plan entries are cleared explicitly: leaving them behind would point the
    # calendar at a meal that no longer exists.
    for entry in session.exec(select(PlanEntry).where(PlanEntry.meal_id == meal_id)).all():
        session.delete(entry)

    session.delete(meal)
    session.commit()
    return RedirectResponse("/meals", status_code=303)


def _parse_minutes(value: str) -> int | None:
    """Read the prep-time field, tolerating blanks and stray text."""
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return None
    minutes = int(digits)
    return minutes or None


# --- Pantry ----------------------------------------------------------------

@app.get("/pantry", response_class=HTMLResponse)
def pantry(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """The running list of what we've got, for the meals actually coming up.

    Scoped to a date range rather than showing every item ever imported: the
    pantry is a shopping aid, and a hundred rows from meals you aren't cooking
    this week drown out the dozen that matter. The range defaults to today
    through a week from today and is editable at the top of the screen.

    Nothing is deleted by filtering — stock, staple flags and merges all survive
    for hidden items and reappear when a meal that needs them is planned.

    Grouped by aisle so it reads like a cupboard rather than an alphabetised
    database dump.
    """
    range_start, range_end = _parse_range(start, end)
    days = week_util.days_in_range(range_start, range_end)
    wanted_ids = pantry_item_ids_for_days(session, days)

    items = session.exec(select(PantryItem).order_by(PantryItem.display_name)).all()

    groups: dict[str, list[PantryItem]] = {}
    for item in items:
        if item.alias_of_id is not None:
            # Merged items are shown under their target, not as separate rows.
            continue
        if item.id not in wanted_ids:
            # Not needed by anything planned in the range.
            continue
        groups.setdefault(item.aisle or "other", []).append(item)

    ordered = [
        (aisles.aisle_for(slug), group)
        for slug, group in sorted(groups.items(), key=lambda kv: aisles.aisle_for(kv[0]).order)
    ]

    # Only merges that affect something on screen. An alias pointing at an item
    # this range doesn't need is just noise here.
    aliases = [
        item for item in items if item.alias_of_id is not None and item.alias_of_id in wanted_ids
    ]
    alias_targets = {item.id: item for item in items}

    # Deliberately every item, not just the visible ones: you merge a stray
    # ingredient into its proper home regardless of whether that home happens
    # to be on this week's menu.
    mergeable = [i for i in items if i.alias_of_id is None]

    return templates.TemplateResponse(
        request,
        "pantry.html",
        {
            "groups": ordered,
            "aliases": aliases,
            "alias_targets": alias_targets,
            "all_items": mergeable,
            # Per visible item: the handful of things it might be the same as,
            # so the picker can float them above the full alphabetical list.
            "suggestions": {
                item.id: suggest_merge_targets(session, item, mergeable)
                for group in groups.values()
                for item in group
            },
            "range_start": range_start,
            "range_end": range_end,
        },
    )


def _pantry_redirect(start: str, end: str) -> str:
    """Back to the pantry, keeping whatever date range the user was looking at.

    Without this every tick would bounce the screen back to the default range,
    which is maddening halfway through checking a cupboard.
    """
    if not (start or end):
        return "/pantry"
    return f"/pantry?start={quote(start)}&end={quote(end)}"


@app.post("/pantry/{item_id}/toggle")
def toggle_stock(
    item_id: int,
    start: str = Form(""),
    end: str = Form(""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    item = session.get(PantryItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Pantry item not found")
    item.in_stock = not item.in_stock
    session.add(item)
    session.commit()
    return RedirectResponse(_pantry_redirect(start, end), status_code=303)


@app.post("/pantry/{item_id}/staple")
def toggle_staple(
    item_id: int,
    start: str = Form(""),
    end: str = Form(""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    item = session.get(PantryItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Pantry item not found")
    item.is_staple = not item.is_staple
    session.add(item)
    session.commit()
    return RedirectResponse(_pantry_redirect(start, end), status_code=303)


@app.post("/pantry/{item_id}/alias")
def merge_item(
    item_id: int,
    target_id: str = Form(""),
    remember: str = Form(""),
    start: str = Form(""),
    end: str = Form(""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """Merge one pantry item into another, or unmerge it.

    This is how an unqualified "basil" gets tied to "dried basil" — a decision the
    parser refuses to make on your behalf, made once here and remembered.

    ``remember`` decides whether the decision also becomes a standing rule for
    items that don't exist yet. Ticked (the default) suits a real synonym like
    cilantro and coriander. Unticked suits a line like "basil or parsley", where
    the answer is a choice you want to make again next time rather than have
    silently applied to every future import.
    """
    item = session.get(PantryItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Pantry item not found")

    target = session.get(PantryItem, int(target_id)) if target_id.strip() else None
    set_alias(session, item, target)

    if target is None:
        # Unmerging withdraws the standing order too, otherwise the next import
        # would silently reinstate the merge the user just undid.
        forget_substitution(session, item)
    elif remember:
        remember_substitution(session, item, target)

    session.commit()
    return RedirectResponse(_pantry_redirect(start, end), status_code=303)


# --- Shopping list ---------------------------------------------------------

@app.get("/shopping", response_class=HTMLResponse)
def shopping(
    request: Request,
    start: str | None = None,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    week_start = _parse_start(start)
    days = week_util.week_days(week_start)
    shopping_list = build_list(session, days)

    return templates.TemplateResponse(
        request,
        "shopping.html",
        {
            "list": shopping_list,
            "week_start": week_start,
            "week_label": week_util.describe_week(week_start),
            "listonic_text": listonic.as_text(shopping_list),
        },
    )


@app.post("/shopping/{item_id}/bought")
def mark_bought(
    item_id: int,
    start: str = Form(""),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """Tick something off: it's now in the pantry.

    This is the feedback loop that keeps the pantry current without a separate
    chore — shopping updates it as a side effect, and the calendar colours follow
    immediately.
    """
    item = session.get(PantryItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Pantry item not found")
    item.in_stock = True
    session.add(item)
    session.commit()
    return RedirectResponse(f"/shopping?start={start}", status_code=303)


# --- Paprika import -------------------------------------------------------

@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request) -> HTMLResponse:
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "import.html",
        {"sync_available": settings.paprika_sync_available, "message": None},
    )


@app.post("/import/file", response_class=HTMLResponse)
async def import_file(
    request: Request,
    export: UploadFile,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Import a .paprikarecipes export."""
    settings = get_settings()
    contents = await export.read()

    try:
        meals = meals_from_export(contents)
    except Exception:
        # Deliberately broad: a wrong file is the most likely thing to happen
        # here, and the useful response is a clear message rather than a 500.
        message = (
            "That file couldn't be read as a Paprika export. In Paprika, use "
            "Recipes → select all → Share → Export, which produces a "
            ".paprikarecipes file."
        )
        return templates.TemplateResponse(
            request,
            "import.html",
            {"sync_available": settings.paprika_sync_available, "message": message},
        )

    result = import_meals(session, meals)
    return templates.TemplateResponse(
        request,
        "import.html",
        {
            "sync_available": settings.paprika_sync_available,
            "message": f"Imported from file: {result.summary}.",
        },
    )


@app.post("/import/sync", response_class=HTMLResponse)
def import_sync(
    request: Request,
    limit: str = Form("50"),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Import via Paprika's unofficial sync API."""
    settings = get_settings()
    try:
        count = int(limit) if limit.strip().isdigit() else 50
        meals = paprika_sync.fetch_meals(limit=count or None)
        result = import_meals(session, meals)
        message = f"Imported from Paprika sync: {result.summary}."
    except paprika_sync.PaprikaSyncError as exc:
        # These messages are written to be user-facing and contain no credentials.
        message = str(exc)
    except Exception:
        message = (
            "Paprika sync failed unexpectedly. It's an unofficial API, so this "
            "does happen — a file export will still work."
        )

    return templates.TemplateResponse(
        request,
        "import.html",
        {"sync_available": settings.paprika_sync_available, "message": message},
    )
