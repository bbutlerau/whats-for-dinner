# CLAUDE.md — Project Memory & Working Agreement

Put this file at the repo root. Claude Code (CLI and VS Code) reads it automatically at the start of every session in this project.

## Learning mode
For this project Brad chose **"Claude writes it"** — implement features fully, but explain the reasoning behind non-obvious decisions and comment the code as you go. Don't silently dump code, and don't drop into pair-programming or leave deliberate gaps for him to fill unless he asks. This choice is per-project and may change; if he signals he wants to write a piece himself, follow that for the piece in question and note it here.

## What this project is
- App: **Meal Planner** — a weekly dinner calendar that shows what's for dinner each night and whether the ingredients are on hand, plus a pantry-level shopping list that exports to Listonic.
- Platform/OS target: Ubuntu LTS home server via Docker Compose, reachable over Tailscale. Used mostly from an iPhone browser, so the UI is phone-first.
- Language & stack: Python 3.12, FastAPI, SQLite (SQLModel), Jinja2 templates with HTMX. No JavaScript build step.
- Interface type: local web UI, no login (Tailscale is the security perimeter).

## Domain rules that are easy to get wrong
- **Ingredient form matters.** `fresh basil`, `dried basil`, `frozen peas` and `tinned tomatoes` are distinct pantry items with independent in-stock state. The form qualifier is part of a pantry item's identity — never normalise it away.
- **An unqualified ingredient stays unqualified.** `basil` on its own does not silently match `dried basil`. Brad merges them explicitly via the pantry's alias feature. Guessing here corrupts the calendar colours, which is the one thing the app exists to get right.
- **Staples never drive the colour code.** Items flagged as staples are excluded from the missing check and surface in their own low-key section.
- **Paprika is a thin source, not the owner.** Import keeps only meal name, ingredient lines and prep/cook time. Directions, notes, photos and nutrition are discarded on the way in and must not be stored. Manually created meals are equal citizens and a re-import must never overwrite them.
- The aisle map and the ingredient alias list are meant to be hand-corrected over time. Prefer "predictable and editable" over "clever and occasionally wrong".

## Workflow
Follow explore → plan → code → verify for anything beyond a trivial one-file script.
- Use plan mode before touching files on anything non-trivial (Shift+Tab in the CLI; the VS Code extension has an equivalent plan/auto-accept toggle in its permissions menu). Wait for my go-ahead before switching out of it.
- For multi-file features, list the files you intend to touch before editing them.
- Don't leave stubs, TODOs, or placeholder functions in code you present as finished. Implement fully, or say plainly what's incomplete and why.

## Effort
Leave effort at its default for most of this project. Drop to `/effort low` or `/effort medium` for renames, formatting, and repetitive edits. Reach for `/effort high` or `/effort xhigh` for architecture decisions, tricky bugs, and anything security-related.

## Verification
Do your own verification as part of finishing a task rather than waiting to be told to check your work — and you don't need to narrate every check you ran. Just tell me plainly if something didn't work, or if you're unsure.

This project is going to be maintained, so it carries a real test suite. Ingredient parsing, aisle matching, meal status colours and shopping-list consolidation are the parts where a subtle bug is invisible until it gives wrong answers — keep those covered with `pytest` and run the suite before calling a change done.

## Code review
When reviewing code, report every issue you notice, including minor or stylistic ones — don't self-filter down to "only high severity." Tag each issue's severity so I can triage quickly myself.

## Security — this repo is public on GitHub
- Never write API keys, tokens, passwords, or personal file paths into tracked files. Use environment variables or a gitignored config file, and keep a matching `.env.example` with placeholder values only.
- `.gitignore` must cover: `.env`, `*.key`, `secrets/`, local virtual environments / `node_modules`, and any local database or cache files.
- Treat `.env` and anything under `secrets/` as off-limits to read, print, or log, even in passing.
- The Paprika credentials are a real account password. They live only in `.env`, are read once at request time, and must never be logged, echoed into a template, or included in an error message.
- Confirm with me before: `git push`, adding a dependency from an unfamiliar source, or any command that deletes files or changes system-level settings.
- Sample or test data must not resemble real personal information. Test fixtures use invented meals, not the real recipe collection.

## Style & output
- Write documentation and comments in plain prose — full sentences, not everything forced into bullet lists.
- Match whatever code style already exists in the repo; ask before introducing a new formatting convention.
- Keep generated docs and reports proportional to what's needed. Cover the substance; skip padding, boilerplate summaries, or redundant recaps.

## Environment notes
- Primary dev machine: MacBook Pro M4 Pro, macOS (Apple Silicon).
- Also runs on: Ubuntu LTS home server via Docker Compose, accessed over Tailscale.
- Target language runtime version: Python 3.12.
- Package manager: `uv`.

## Stretch goals, deliberately not built yet
- Multiple users with separate plans and shopping lists. This is why there's no login today; if it lands, it needs a real auth story rather than a name field.
- A genuine Listonic API integration. None is publicly available, so the export goes through a copy-to-clipboard text block behind `app/shopping/listonic.py`. If an API ever appears, that module is the only thing that should need to change.
