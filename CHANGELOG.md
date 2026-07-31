# Changelog

Notable changes, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions are
[semantic](https://semver.org/) in spirit — while this sits below 1.0, the minor
number moves for features and the patch number for fixes, and anything that
would make you re-enter data gets called out explicitly.

Each released version has a matching `v*` git tag, which is what publishes the
container image to `ghcr.io/bbutlerau/whats-for-dinner`.

## [Unreleased]

Nothing yet.

## [0.2.0] — 2026-07-31

The first tagged release, and the first that deploys as a published image rather
than a build on the server.

### Added

- **Merge suggestions in the pantry.** The "same as…" picker floats likely
  matches to the top under a Suggested group. They come from three sources: the
  same base name in a different form (`basil` → `dried basil`), a hand-written
  synonym table in `app/ingredients/synonyms.py`, and a strict fuzzy match for
  misspellings.
- **Saved substitutions.** Merging offers "Always treat it this way", ticked by
  default, which records a name-level rule so a later import introducing that
  name arrives already merged. Unticking keeps the merge a one-off, for lines
  like `basil or parsley` where the answer is a choice each time. Unmerging
  withdraws the rule.
- **A date range on the pantry**, defaulting to today through a week ahead. The
  screen now lists only the items the meals planned in that range call for.
  Nothing is deleted by narrowing it — stock, staple flags and merges survive
  for items off screen.
- **Published container images.** Every push to `main` runs the test suite and,
  if it passes, publishes to GHCR; `v*` tags additionally publish semver tags.
  The server pulls rather than builds.
- **A version in the page footer**, so which build is live is answerable from
  the phone.

### Changed

- **The default port is now 7007**, not 8000, which collides with too much else
  on a home server. Existing Compose users need the new `docker-compose.yml`.
- The Docker image installs from `uv.lock` via `uv sync --frozen` instead of a
  hand-maintained dependency list, so it reproduces the dependency set the tests
  ran against.
- `uv.lock` is tracked rather than ignored, for the same reason.

### Notes

The fuzzy-match cutoff sits at 0.9 and does not, on its own, find real synonyms:
`cilantro`/`coriander` scores 0.59 and `zucchini`/`courgette` scores 0.12, while
`carrot`/`parrot` scores 0.83. No single cutoff both finds the first two and
rejects the third, which is why the synonym table is written by hand.

## [0.1.0] — 2026-07-30

Initial version, developed before the repository existed and committed in one
go.

### Added

- Weekly dinner calendar with green/amber/red/grey status per night, driven by
  whether each meal's non-staple ingredients are in the pantry.
- Pantry with per-item stock, staple flags, aisle grouping, and explicit
  "same as…" merges for ingredients the parser deliberately refuses to guess at.
- Ingredient parsing that treats a form qualifier as part of an item's identity,
  so `fresh basil` and `dried basil` are separate things to own.
- Shopping list consolidating a week's missing ingredients by aisle, with exact
  fraction arithmetic and a copy-to-clipboard Listonic export.
- Paprika import from a `.paprikarecipes` file export or the unofficial sync
  API, keeping only meal name, ingredient lines and prep time.
- Docker Compose deployment with the database on a named volume.

[Unreleased]: https://github.com/bbutlerau/whats-for-dinner/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/bbutlerau/whats-for-dinner/releases/tag/v0.2.0
[0.1.0]: https://github.com/bbutlerau/whats-for-dinner/releases/tag/v0.1.0
