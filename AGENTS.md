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
- `tests/` — pytest suite (`pytest-asyncio`, `freezegun`, `pytest-homeassistant-custom-component`).
  - `tests/e2e/` — e2e tests with real network access (see "Testing").
- `conftest.py` — loads the Home Assistant test plugin, also on Windows (see "Testing").
- `script/update_version.py` — bumps the version (see gotcha below).
- `justfile` — canonical task runner. `.ruff.toml`, `.pre-commit-config.yaml`,
  `pyproject.toml` — tooling config.
- `.mcp.json`, `.claude/ha_test_mcp_headers.py` — the `ha-test` MCP server for a local test Home Assistant (see "Local test Home Assistant").

## Dev environment & commands

The project uses **[uv](https://docs.astral.sh/uv/)**. Run everything through
`uv run` so the project virtualenv is used. Do **not** `cd` into subdirectories
before running commands — run them from the repo root.

Use the `just` recipes. The `justfile` shows what each recipe runs.

- `just install`: after a clone, and after a change of the dependencies.
- `just upgrade`: when you upgrade all dependencies.
- `just lint`: after each code change.
- `just test`: after each change.
- `just test_e2e`: after a change of the code that reads a real source, and before a release. It needs network access.
- `just cov`: when you add or change tests, to see the lines of each module that no test runs.
- `just pre`: before you finish a change.
- `just pre-update`: when you update the versions of the pre-commit hooks.
- `just version X.Y.Z`: when you change the version.

Run any ad-hoc Python via `uv run python ...`.

The pre-commit hooks also run the full test suite, so each commit runs it. They also run the `ty` type checker on the files of `[tool.ty.src]` in `pyproject.toml`, which is `custom_components` only, because the tests use mocks and wrong values on purpose. Fix a type error instead of adding a `ty:ignore` comment.

## Local test Home Assistant (optional)

The `ha-test` server in `.mcp.json` connects an agent to the [Model Context Protocol Server](https://www.home-assistant.io/integrations/mcp_server/) integration of a local Home Assistant at `http://127.0.0.1:8123/api/mcp`. You need it only to see the integration work in a real Home Assistant. The test suite does not use it.

To set it up:

1. Link `custom_components/svitlo_yeah` into the `custom_components` folder of the local Home Assistant configuration.
2. In the local Home Assistant, add the Model Context Protocol Server integration.
3. In the local Home Assistant, open your user profile, open the Security tab, and create a long-lived access token.
4. Put the token into the `.env` file in the repository root, on its own line: `HA_TEST_TOKEN=<token>`. Git ignores `.env`.
5. Start a new Claude Code session in the repository, and approve the `ha-test` server when Claude Code asks.

Do not put the token into `.mcp.json` or into an environment variable. The `headersHelper` of `ha-test` runs `.claude/ha_test_mcp_headers.py`, and this script reads `HA_TEST_TOKEN` from `.env`. Claude Code removes each variable with `TOKEN` in its name from the environment of the helper, so an environment variable does not get to the script. If `.env` has no token, the script stops with an error and `ha-test` does not connect.

OAuth does not work with this server yet. Home Assistant core checks PKCE, but the released frontend does not forward `code_challenge` to the login flow (home-assistant/frontend#54389). When a frontend release with that change is on the server, `ha-test` can use OAuth instead of the token. To do that, set `"oauth": {"clientId": "http://localhost:8765/", "callbackPort": 8765}` in `.mcp.json` and remove `headersHelper`. Home Assistant compares the redirect URI of the default Claude Code client together with its port, so the default client fails with `Invalid redirect URI`.

The MCP server gives only the Assist tools of Home Assistant, for example `GetLiveContext`, `HassTurnOn` and `HassTurnOff`. It sees only the entities that you expose to Assist. It cannot add, reconfigure or remove a config entry, and it cannot restart Home Assistant. For these actions, use the Home Assistant REST API with the same token in the `Authorization: Bearer` header. For example, `POST /api/config/config_entries/flow` starts a config flow. Read the token from `.env` inside the script, and never put the token on a command line or into output.

Home Assistant loads a code change only after a restart. If the local Home Assistant runs `python -m homeassistant` without a loop that starts it again, the `homeassistant.restart` service stops the server. In that case, ask the user to restart Home Assistant.

### UI checks with Playwright MCP (optional)

The Home Assistant frontend is built from Lit web components with open shadow roots. A browser tool that reads only the light DOM finds an empty page there. The [Playwright MCP](https://github.com/microsoft/playwright-mcp) server gives an accessibility snapshot that includes the shadow DOM, with a `ref` for each element. Thus an agent can walk a check scenario step by step, for example a config flow or a Reconfigure, and click and type by `ref`, without a script and without screenshots.

To set it up:

1. Add a stdio MCP server to your MCP client that runs `npx -y @playwright/mcp@latest --browser firefox --headless --user-data-dir <profile folder> --output-dir <output folder>`. Give both folders a place outside the repository where the server can write. Some MCP hubs start a server in a folder without write access, and then each call fails with `EPERM`.
2. If a call fails with `Browser "firefox" is not installed`, run `npx -y @playwright/mcp@latest install-browser firefox`. A new release of the package can need a new browser build.
3. Sign in to the local Home Assistant once. Start the same server without `--headless`, open `http://127.0.0.1:8123` in its window, and sign in yourself. The profile folder keeps the sign-in for the headless server. Do not let an agent type the password.

Keep `--headless` for the checks. A browser with a window draws no frames while the window is minimized or covered, and then each click waits until it times out. Two browsers cannot use one profile folder at the same time, so close the headless browser before you start the one with a window.

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

- A test with the `e2e` marker runs only with `just test_e2e`, not with `just test`.
- Put each test that needs real network access into `tests/e2e/`. `tests/e2e/conftest.py` adds the `e2e` marker to each test in that folder, so a test there needs no marker of its own.
- The tests run with [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component). It gives the fixtures of the Home Assistant core tests, for example `hass` and `aioclient_mock`. For a test that runs the config flow or sets up the integration, use the `hass` fixture.
- The plugin blocks sockets and DNS in each test. `tests/e2e/conftest.py` gives the tests in that folder the real network back.
- Home Assistant does not run on Windows, and the plugin does not load there on its own. The root `conftest.py` makes it load. Its docstring tells why `addopts` in `pyproject.toml` has `-p no:homeassistant`, and a comment in `pyproject.toml` tells why each test gets a new event loop. Read both before you change these settings.
- **Tests work around the code, not the reverse.** Do **not** compromise or add
  logic to production code merely to satisfy tests. When the test/non-production
  environment differs, absorb that difference inside the test code.
- Async tests use `asyncio_mode = "auto"` with a new event loop for each test; time is
  controlled with `freezegun`.

## Domain knowledge

### Providers & data sources

Outage data comes from several providers, each with its own `api/` client and
`coordinator/`: Yasno, E-Svitlo, and DTEK. DTEK and several oblasts are served by
**JSON feeds** (community GitHub raw files) via `api/dtek/json.py`. All HTTP uses
`aiohttp` through HA's `async_get_clientsession(hass)` — there is no bespoke HTTP
stack. See `README.md` for the authoritative region → provider → source table.

### Old states until new data

The entities must not become unavailable without need. Until a coordinator gets new data, the entities keep their old states. Thus a coordinator never raises `UpdateFailed` or `ConfigEntryNotReady` when a source does not answer, and a failed fetch keeps the last data. The Bronze rule `test-before-setup` of the integration quality scale conflicts with this requirement, because Home Assistant shows each entity of an entry that retries its setup as unavailable after a restart. The integration does not follow that rule on purpose.

The old states also stay across a restart. `IntegrationCoordinator` keeps the last data of the source in a `Store` with the key `svitlo_yeah.<entry_id>`. `_async_setup` loads it before the first fetch, `_async_store_last_data` saves it when it changed, and `async_remove_entry` in `__init__.py` deletes it. Each provider coordinator implements `_source_data` and `_restore_source_data`. DTEK keeps `fact` and `preset`, Yasno keeps the planned outages and the region of the entry, and E-Svitlo keeps the raw answer of the disconnections request, its update time and the group. A kept Yasno region and a kept E-Svitlo group only name the device: the clients still ask the source for them, so that a change at the source comes through. The kept answer about the group (`group_listed`) counts only when the kept group is the configured group, because a Reconfigure changes the group.

### DTEK JSON freshness

`api/dtek/json.py` fetches JSON with a `fact` (and optional `preset`) structure and checks an `update` timestamp against `DTEK_FRESH_DATA_DAYS`. `fetch_data` returns a `FetchResult` enum — `FRESH`, `STALE`, or `UNAVAILABLE`. Newly fetched stale data is only adopted during setup with explicit user consent (`allow_stale_data=True`). At runtime, `STALE` leaves `self.data` as it is. Thus the coordinator keeps serving the last fresh copy, also after that copy is older than `DTEK_FRESH_DATA_DAYS`. The store of the entry keeps that copy across a restart (see «Old states until new data»). `test_stale_at_runtime_keeps_the_last_fresh_copy` pins this behavior. The `update` field uses `DD.MM.YYYY HH:MM` (or `HH:MM DD.MM.YYYY`).

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
- **Version-sync gotcha:** the version lives in **both** `pyproject.toml` (`version = "..."`) and `custom_components/svitlo_yeah/manifest.json` (`"version"`). They must match. Use `just version X.Y.Z` rather than editing either by hand.
