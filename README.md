# Meal Planner

A weekly dinner calendar for one household. It answers two questions at a glance:
**what's for dinner each night**, and **have we got everything for it**. Meals that
are ready to cook are green, meals missing something are red with the missing
items listed, and the shopping list that comes out the other end pastes straight
into Listonic.

## A disclaimer worth reading first

This is a personal app I built for myself, and it was written by Claude rather
than typed out by hand. It is not a product and should not be considered stable —
there's no support, no upgrade path, and the data model may change under you. That
said, I use it every week for my own dinners, so I have every intention of keeping
it working. Fork it, borrow from it, or run it yourself if it's useful, but do
that with your eyes open.

It is deliberately not a recipe app. There's no method, no photos, no ratings —
[Paprika](https://www.paprikaapp.com/) already does that well, and this pulls just
the meal name, ingredients and prep time from it.

## Screens

- **Week** — seven nights, one meal each, colour-coded by whether the ingredients
  are in the pantry. Pick a meal per night from a dropdown; that's the whole
  interaction.
- **Meals** — everything you can put on the calendar, whether typed in by hand or
  imported.
- **Pantry** — a running list of what you've got, ticked by hand and topped up
  automatically as you shop.
- **Shopping** — the week's missing ingredients, grouped by aisle with an emoji
  per section, with a one-tap copy for Listonic.

## How the colours work

| Colour | Meaning |
| --- | --- |
| 🟢 Green | Every non-staple ingredient is in the pantry |
| 🟠 Amber | The real ingredients are covered, but a staple is unaccounted for |
| 🔴 Red | Something you'd have to buy is missing — it's listed under the meal |
| ⚪ Grey | Nothing planned |

Staples (salt, oil, flour and friends) are held apart on purpose. If they counted,
every night would be amber forever and the colour would stop meaning anything.
Anything can be flagged or unflagged as a staple from the pantry screen.

## Fresh is not dried

`fresh basil`, `dried basil`, `frozen peas` and `tinned tomatoes` are tracked as
separate pantry items with independent stock, because they are separate things to
own. Having dried basil in the cupboard doesn't turn a recipe calling for fresh
basil green.

An ingredient written without a form — just `basil` — stays its own item rather
than being guessed into one of the others. A wrong guess there is invisible until
it gives the wrong answer, so instead the pantry offers a one-tap **"same as…"**
merge. You tie `basil` to `dried basil` once and it's remembered permanently. The
same mechanism cleans up anything else the parser splits when it shouldn't have.

## Running it

### Locally

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"
uv run uvicorn app.main:app --reload --port 7007
```

Then open <http://localhost:7007>. The port is 7007 rather than uvicorn's usual
8000 because 8000 is often already taken on a home server.

### On a server, with Docker

```bash
docker compose up -d --build
```

The SQLite database lives in a named volume, so it survives rebuilds. Reach it
over Tailscale at `http://<machine-name>:7007`.

There is **no login**. That's a deliberate choice for a personal app where
Tailscale is the security perimeter — but it means this must not be exposed
directly to the internet. Put a reverse proxy with authentication in front of it
first if you ever need to.

### Tests

```bash
uv run pytest
```

The suite concentrates on the four places a subtle bug would be invisible:
ingredient parsing, aisle matching, the colour logic, and shopping-list
consolidation.

## Getting meals in

### By hand

**Meals → + Add meal.** Type a name, a prep time, and ingredients one row at a
time with **+ Add ingredient** (pressing Enter adds the next row, which is faster
when typing out a whole recipe). Write ingredients how you'd say them — `2 cloves
garlic`, `400g tin of tomatoes`, `1 tsp dried oregano`. Saved meals are available
to pick every week after.

### From Paprika

Two routes, both under **Import from Paprika**:

**File export** — the reliable one. In Paprika: Recipes → select all → Share →
Export, which gives you a `.paprikarecipes` file to upload. Fully supported by
Paprika, no credentials needed. The trade-off is that you re-export when your
recipes change.

**Sync API** — optional and unofficial. Paprika publishes no public API; this uses
the private endpoint the Paprika apps themselves use, authenticated with your real
account email and password from `.env`. It can break without notice, and that
would be entirely fair. It's read-only — nothing here ever writes back to Paprika.
Leave `PAPRIKA_EMAIL` and `PAPRIKA_PASSWORD` blank and the option simply doesn't
appear.

Either way, only the name, ingredients and prep time are kept. Everything else is
discarded as it comes in. A Paprika import will never overwrite a meal you edited
or created by hand.

## About Listonic

Listonic has no public API. Their developer site sells a shopping-cart API to
retail clients; there's no way to write items into your own personal list. So the
export renders the list as plain text, one item per line, and Listonic's add-items
box accepts that as a single paste.

All of that is confined to `app/shopping/listonic.py`. If an API ever appears,
that's the only file that needs to change.

## Configuration

Copy `.env.example` to `.env` and edit. Every setting is optional except in the
Paprika sync case:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Where SQLite keeps its file. Docker sets this itself. |
| `PAPRIKA_EMAIL` / `PAPRIKA_PASSWORD` | Enables the unofficial sync import. Blank disables it. |
| `DEV_RELOAD` | Auto-reload for local development. |

`.env`, the database, and any `.paprikarecipes` export are all gitignored. Your
recipes and your Paprika password stay on your own machine.

## Layout

```text
app/
  main.py            FastAPI routes — thin, just forms in and templates out
  models.py          Meal, MealIngredient, PantryItem, PlanEntry
  ingredients/
    normalise.py     freeform text → a stable pantry identity (the tricky bit)
    aisles.py        emoji aisle map with fuzzy matching
    store.py         pantry lookup, staples, alias merges
  planner/
    status.py        the colour logic
    week.py          week arithmetic
  shopping/
    list.py          consolidation across a week's meals
    listonic.py      the only Listonic-shaped code in the project
  paprika/
    parse.py         export format + recipe JSON, pure functions
    sync.py          the unofficial API, quarantined in one file
    importer.py      import rules, shared by both routes
```

## Not built yet

Multiple users with separate plans and lists — which is the reason there's no
login today rather than a half-built one. A real Listonic integration, if the
platform ever offers one.

## Licence

MIT. See [LICENSE](LICENSE).
