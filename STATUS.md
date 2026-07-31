# Where this project is up to

Last updated 31 July 2026, at v0.2.0. This is a handoff note for picking the
project back up later — what's built, what's been verified, and what's
deliberately still open. `CLAUDE.md` holds the working agreement and the domain
rules, `CHANGELOG.md` holds the release history, and this file holds the state.

## Status in one line

The app is built, tested, linted and published. The repository is public at
github.com/bbutlerau/whats-for-dinner, CI runs the suite and pushes a container
image to GHCR on every green build, and the server runs that image rather than
building from source. It has been used from Brad's iPhone over Tailscale with
real data.

## What's built

The whole thing is a server-rendered FastAPI app with Jinja2 templates, SQLite via
SQLModel, and vanilla JS only in the two places it's genuinely needed (the
ingredient row builder and the pantry menus). There is no JS build step and no
login — Tailscale is the security perimeter.

**Calendar** (`/`) is the main screen. It shows a week of dinners, each meal name
colour-coded: green when everything's in stock, red when a non-staple ingredient is
missing, amber when only staples are missing, grey for an empty night. The logic
lives in `app/planner/status.py` and the week arithmetic in `app/planner/week.py`.
`build_week` does the whole week in two queries rather than one per day.

**Meals** (`/meals`) is manual entry and editing. The form uses the `+ Add
ingredient` repeating-row builder Brad asked for rather than a textarea, so it's
usable with a thumb. Meals carry a name, optional prep/cook minutes, and an ordered
list of ingredient lines.

**Pantry** (`/pantry`) is the have/don't-have state that drives everything else.
Items are grouped by aisle with emoji, each has a tick, and the `⋯` menu offers
"treat as a staple" and the merge ("same as…"). Merged items get their own section
at the bottom and can be unmerged.

The screen is scoped to a date range, defaulting to today through a week ahead and
editable at the top, showing only the items the meals planned in that range need.
Filtering never deletes: stock, staple flags and merges survive off screen. The
merge picker floats likely matches into a Suggested group, and merging offers
"Always treat it this way" (on by default), which saves a name-level rule so a
later import of that name arrives already merged.

**Shopping** (`/shopping`) consolidates the week's missing ingredients by aisle,
ticks off as you shop (which feeds straight back into pantry stock), keeps staples
in their own low-key section, and offers the Listonic export as a copy-paste text
block.

**Import** (`/import`) takes a Paprika `.paprikarecipes` file or pulls via the
unofficial sync API. It keeps only the meal name, ingredient lines and prep/cook
time; directions, notes, photos and nutrition are discarded on the way in.

## The parts most likely to bite

These are the bits where a subtle bug gives wrong answers silently rather than
crashing, and they're where the test coverage is concentrated.

`app/ingredients/normalise.py` turns an ingredient line into a pantry identity.
Form qualifiers are part of that identity, so `fresh basil` and `dried basil` are
two separate rows with independent stock. A bare `basil` stays bare — it does *not*
get silently matched to either, because guessing wrong corrupts the calendar
colours, which is the one thing this app exists to get right. The merge feature is
the explicit fix for that. Note that `PREP_WORDS` deliberately excludes "ground"
and "smoked": ground cumin is not cumin seeds and ground beef is not beef.

`app/ingredients/aisles.py` classifies into ten aisles. `_match_keyword` runs four
tiers in order — whole-name exact, multi-word keyword, head noun (last word), then
any single-word keyword longest-first — with a `difflib` fuzzy fallback for typos.
The tiering exists because naive longest-first matching put `orange juice` in
produce, since "orange" is longer than "juice". Don't collapse the tiers back down.

`app/shopping/list.py` uses `fractions.Fraction` so a third plus two thirds is
exactly one. Mismatched units are listed side by side ("2 cup + 400 g") rather than
converted, on the grounds that an untidy honest answer beats a confidently wrong
number. Ranges like "2-3 tbsp" survive as text.

`app/ingredients/store.py` handles alias resolution. Chains are collapsed on write
so they're only ever one hop deep, and the setter refuses to create a cycle. It
also holds merge suggestions and saved substitutions.

`app/ingredients/synonyms.py` is a hand-written table of same-ingredient pairs. It
exists because string similarity genuinely cannot do this: `cilantro`/`coriander`
scores 0.59 and `zucchini`/`courgette` scores 0.12, while `carrot`/`parrot` scores
0.83, so no single cutoff finds the real pairs and rejects the nonsense. The fuzzy
arm is pinned at 0.9 and only catches misspellings. Add pairs to the table by hand
rather than loosening the cutoff.

## Verification

130 tests pass (`pytest`), ruff is clean. Beyond unit tests, the following were
checked end to end over HTTP: red → tick off → green, amber for a staple-only gap,
garlic consolidating to `5 clove` from a 2 and a 3, a merge turning a meal green,
the alias cycle guard holding, and — by grepping the raw SQLite bytes — that
Paprika directions and photo blobs are genuinely never stored.

Not yet exercised: the Paprika **sync API path has never run against real
credentials**. Only the unconfigured state has been tested. It needs
`PAPRIKA_EMAIL` and `PAPRIKA_PASSWORD` in `.env`. The file-export path works.

Also untested in anger: Listonic's clipboard copy needs HTTPS in some browsers, so
over plain Tailscale HTTP the copy button may not work on the phone and the text
has to be selected manually.

## Recent fix

The pantry `⋯` menu used to break the row: the open `<details>` laid its contents
out as flex siblings of the item name, so "Stop treating as a staple" printed on
top of the item. It's now a `.menupanel` wrapper positioned absolutely as a
popover, out of the layout flow, with menu behaviour (one open at a time, dismiss
on outside tap or Escape) and a rule flipping the panel upward for the last two
rows so it doesn't open off-screen.

## Open items, in rough priority order

1. **Use it for a real week** and see what the merge flow feels like on a phone.
   Brad's live data already showed `Cheese` / `Cheddar or tasty cheese` and
   `Butter` / `Unsalted butter` needing merging, which is the parser behaving
   correctly but is also the flow most likely to feel slow in practice. The
   suggestion feature was built for exactly this; whether it actually helps is
   the open question.
2. **No screen lists the saved substitution rules.** A rule saved by mistake can
   currently only be undone by finding the item it came from and unmerging it.
   Noted deliberately rather than built — worth doing if a wrong rule ever bites,
   probably as a section on the pantry screen alongside "Merged items".
3. **Items outside the pantry's date range are unreachable.** Because the pantry
   is scoped with no all-items toggle (a deliberate choice for a simpler screen),
   an ingredient belonging to a meal that has never been planned can't be merged
   or flagged as a staple from the UI. Widening the dates is the only way to it.
   If that gets annoying, the fix is a toggle or a search box rather than undoing
   the scoping.
4. **Try the Paprika sync path** with real credentials, or decide the file export
   is enough and leave sync as-is.

## Deliberately not built

Multiple users with separate plans, which is why there's no login today — if it
lands it needs a real auth story rather than a name field. And a genuine Listonic
API integration, because no public API exists; if one ever appears,
`app/shopping/listonic.py` is the only module that should need to change.

## Running it

```
uv run uvicorn app.main:app --reload --port 7007   # dev, localhost
uv run uvicorn app.main:app --host 0.0.0.0 --port 7007   # over Tailscale
uv run pytest && uv run ruff check .              # before calling anything done

docker compose pull && docker compose up -d       # on the server: deploy
```

The port is 7007, not 8000, which is taken by an MCP server on Brad's machine.
The footer of every page shows the running version, which is the quickest way to
confirm a pull actually landed.

Data lives in `./data/mealplanner.db` locally and in the named volume under
Compose. Both are gitignored.
