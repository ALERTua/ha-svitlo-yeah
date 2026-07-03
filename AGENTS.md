# AGENTS.md

Guidance for AI coding agents working in this repository. Keep changes minimal,
verify against the actual code, and follow the boundaries below.

## Project overview

Svitlo Yeah (Світло Є) is a [Home Assistant](https://www.home-assistant.io/)
custom integration (HACS) that tracks electricity-outage schedules from Ukrainian
energy providers. It exposes outage calendars, an `Electricity` status sensor,
"next outage / next connectivity" timestamp sensors, a force-refresh button, and
a `svitlo_yeah_data_changed` event. It supports many regions/providers (DTEK,
Yasno, E-Svitlo, and community JSON feeds) with per-group configuration, all set
up through the Home Assistant UI. See `README.md` for the full region list and
entity reference.

This is a HACS integration, **not** a standalone Python library — the API classes
require a running Home Assistant instance (`hass`).

## Repository layout

- `custom_components/svitlo_yeah/` — the integration package (domain: `svitlo_yeah`).
  - `api/` — provider clients that fetch and parse raw outage data
    (`yasno.py`, `e_svitlo.py`, `dtek/`), plus `common_tools.py`.
  - `coordinator/` — `DataUpdateCoordinator` subclasses per provider that own
    fetch/refresh scheduling and expose events to the entities.
  - `entity.py`, `sensor.py`, `calendar.py`, `button.py` — HA entity platforms.
  - `config_flow.py` — UI setup/options flow.
  - `models/`, `const.py`, `manifest.json`, `translations/`.
- `tests/` — pytest suite (`pytest-asyncio`, `freezegun`).
- `script/update_version.py` — bumps the version (see gotcha below).
- `justfile` — canonical task runner. `.ruff.toml`, `.pre-commit-config.yaml`,
  `pyproject.toml` — tooling config.

## Dev environment & commands

The project uses **[uv](https://docs.astral.sh/uv/)**. Run everything through
`uv run` so the project virtualenv is used. Do **not** `cd` into subdirectories
before running commands — run them from the repo root.

Prefer the `just` recipes (from `justfile`):

- `just install` → `uv sync --dev` — install deps.
- `just test` → `uv run pytest` — run the test suite (e2e tests excluded by default).
- `just test_e2e` → `uv run pytest -m e2e` — run e2e tests (real network access).
- `just lint` → `uv run ruff format .` then `uv run ruff check --fix`.
- `just pre` → `uv run pre-commit run --all-files` — run all pre-commit hooks.
- `just version X.Y.Z` → runs `script/update_version.py` then `uv lock`.

Run any ad-hoc Python via `uv run python ...`.

Pre-commit hooks include ruff + ruff-format, `uv-lock`, `validate-pyproject`,
`todo-md`, standard whitespace/EOF fixers, and **pytest** (the full test suite
runs as a local hook). Before finishing a change, ensure `just pre` passes.

## Code style & conventions

- **Python 3.14+ only.** `requires-python = ">=3.14.2"` (tracking Home Assistant
  core), and ruff `target-version = "py314"`. You may freely use the newest idioms.
- **No `from __future__ import annotations`.** Annotations are deferred by default
  on 3.14; the import is redundant and must not be added.
- **Modern typing:** use PEP 604 unions (`str | None`) and PEP 585 builtins
  (`list[...]`, `dict[...]`) — not `Optional`, `Union`, `List`, `Dict`.
- **`TYPE_CHECKING` guards:** import types used only in annotations under
  `if TYPE_CHECKING:` (see `api/dtek/json.py`). Deferred annotations make this safe.
- **Ruff with `select = ALL`** and `max-complexity = 25`. A small ignore set lives
  in `.ruff.toml` (e.g. `ANN401`, formatter-conflict rules). Tests relax some
  rules (`ANN*`, `S101`, `SLF001`, `PLR2004`, `E501`, `DTZ001`). Prefer a
  narrowly-scoped `# noqa: RULE` with reason over broadening the global ignores.
- **Timezone-aware datetimes everywhere.** This is an invariant: HA's
  `calendar.async_get_events` passes tz-aware datetimes, so
  `coordinator.get_events_between` and `api.get_events` datetimes are tz-aware
  too. Never introduce naive datetimes in production paths; parse to aware
  (usually via `homeassistant.util.dt`), and treat provider-local times as
  Europe/Kyiv. `DTZ*` ruff rules enforce this.
- **`# fmt: skip  # remove in 2027` on multi-line `except (...)` tuples**: these
  exist in `api/common_tools.py` and `api/e_svitlo.py` to stop the formatter from
  reflowing the exception tuple onto one line. Keep the comment intact when you
  touch those lines; the marker signals it can be revisited in 2027.

## Testing

- Run with `just test` (`uv run pytest`). e2e tests are marked `e2e` and excluded
  by default (`-m 'not e2e'`); run them explicitly with `just test_e2e`.
- **Tests work around the code, not the reverse.** Do **not** compromise or add
  logic to production code merely to satisfy tests. When the test/non-production
  environment differs, absorb that difference inside the test code.
- Async tests use `asyncio_mode = "auto"` with a session-scoped loop; time is
  controlled with `freezegun`.

## Domain knowledge

### Providers & data sources

Outage data comes from several providers, each with its own `api/` client and
`coordinator/`: Yasno, E-Svitlo, and DTEK. DTEK and several oblasts are served by
**JSON feeds** (community GitHub raw files) via `api/dtek/json.py`. All HTTP uses
`aiohttp` through HA's `async_get_clientsession(hass)` — there is no bespoke HTTP
stack. See `README.md` for the authoritative region → provider → source table.

### DTEK JSON freshness

`api/dtek/json.py` fetches JSON with a `fact` (and optional `preset`) structure and
checks an `update` timestamp against `DTEK_FRESH_DATA_DAYS`. `fetch_data` returns a
`FetchResult` enum — `FRESH`, `STALE`, or `UNAVAILABLE`. Stale data is only adopted
during setup with explicit user consent (`allow_stale_data=True`); it is **never**
served at runtime. The `update` field uses `DD.MM.YYYY HH:MM` (or `HH:MM DD.MM.YYYY`).

### Hour-status grid (DTEK schedule encoding)

Per-day schedules are a map of hour-index → status string (parsed in
`api/dtek/base.py`). Status values:

- `"yes"` — no outage (ends any open outage).
- `"no"` — full-hour outage (continues an existing outage).
- `"second"` — outage in the **second** half hour (`hh:30`–`hh+1:00`); typically the
  **start** of a range.
- `"first"` — outage in the **first** half hour (`hh:00`–`hh:30`); typically the
  **end** of a range, and always closes at `hh:30`.
- Maybe/possible-outage variants also exist: `"maybe"`, `"msecond"`, `"mfirst"`
  (and `"?"`), handled alongside their definite counterparts.

`"first"`/`"second"` appear at range boundaries; `"no"`/`"maybe"` fill the interior.
Example: `13:"second", 14:"no", 15:"no", 16:"no", 17:"first"` → a single outage
range `12:30`–`16:30`. Consult `base.py` for the exact merging logic and the
`Scheduled` (may happen) vs `Planned` (will happen) distinction.

## Agent workflow & boundaries

- **Raise open questions before implementing.** If requirements are ambiguous or a
  change risks the invariants above, ask first.
- **Use a markdown checklist for multi-step work.** For any multi-stage
  implementation, write a checklist, tick items off as you complete them, and
  return the updated list.
- **Never touch git history or the index.** You are **not** allowed to run
  `git add`, `git commit`, `git rm`, or anything that stages or commits. Producing
  a diff or a commit message does not imply permission to commit.
- **Version-sync gotcha:** the version lives in **both** `pyproject.toml`
  (`version = "..."`) and `custom_components/svitlo_yeah/manifest.json`
  (`"version"`). They must match. Use `just version X.Y.Z`
  (`script/update_version.py` + `uv lock`) rather than editing either by hand.
