# Changelog

All notable changes to Athena Assistant. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project versions
each milestone as a release. Newest first.

## [2.8.0] — Milestone 28.0 — Portable Profiles: export

First half of the **M28 Portable Profiles epic** — **app bumped to 2.8.0**.
Spec: `docs/specs/M28-portable-profiles.md`. Docs: `docs/PORTABLE-PROFILES.md`.

### Added
- **`backup/portable.py`** (`PortableProfileManager`): builds a host-agnostic,
  secret-free identity **snapshot** (system prompt + memory + portable prefs)
  as `data/exports/<stamp>_athena_portable.zip`. **Allowlist-built**
  (`_sanitize_profile` constructs from a KEEP set — a future profile field
  fails closed) and **leak-guarded**: live `.env` values or credential-shaped
  strings anywhere, and URLs/host-paths in profile fields, are a **hard
  failure** (never emitted). URLs in *memory* are user content → warnings for
  review. Strips `memory.path`, `machine_overrides`, all of `config/`;
  excludes pending-review + archive; the manifest carries **no hostname** and
  states the snapshot-forks-on-import limitation.
- **Routes** (`app/routers/portable.py`): `GET /portable/preview` (the review
  step — sanitized fields + every memory entry id/category/key),
  `POST /portable/exports` (with `exclude_ids` for per-entry exclusion; 409 on
  a leak-guard hit), plus list/download/delete. Ops-audited via
  `write_ops_event("portable_export")`.

### Notes
- Import is **M28.1** (next). Tests: `tests/test_portable.py` — identity kept
  vs host fields stripped, pending-review/config/.env never travel, preview +
  exclusion honored, **planted `.env` value / `sk-…` string / profile URL all
  hard-fail with nothing emitted**, memory URL is warning-only, and portable/
  backup listings stay disjoint. Gate: ruff + mypy + 470 pytest + 21 vitest.

## [2.7.1] — Milestone 27.1 — Token / context usage surfaces

Second half of the **M27 epic** — **app bumped to 2.7.1**. Spec:
`docs/specs/M27-live-status-and-usage.md`. Surfaces per-response token usage of
the selected provider in both the web UI and athena-cli, off the shared M22
diagnostics trace.

### Added
- **Content-free `usage` on the diagnostics record** (`ProviderCallRecord.usage`):
  optional token *counts* (`prompt`/`completion`/`total`), or `None`
  ("unavailable"). Counts are metadata — the "diagnostics store no content" rule
  still holds (never token text).
- **Best-effort capture for API transports** (`extract_openai_usage` in
  `providers/base.py`): chatgpt, grok (api path), and ollama read the OpenAI-SDK
  `usage` object into `metadata["usage"]`; the router copies it onto the record.
  The extractor is defensive — a missing/mangled `usage` yields `None`, never an
  exception (and a stray `bool` is not mistaken for a count).
- **Web UI** (`buildUsageText` in `static/js/chat.js`): a quiet token line under
  the answer ("Tokens: 1,204 prompt + 320 completion = 1,524 total" / "Tokens:
  unavailable"), rendered with `textContent` (counts only, no XSS).
- **CLI** (`build_cli_usage` in `cli/status.py`): the same line on **stderr**
  alongside the status summary — stdout stays answer-only (M25/M27.0 contract).

### Deferred (deliberate, flagged)
- **Claude-CLI usage via `--output-format json` is NOT in this release.** Capturing
  it means switching the Claude invocation to a JSON envelope and re-parsing its
  output — a change to the primary provider's output path that can't be validated
  against the real CLI from the fully-mocked suite. Rather than risk breaking a
  working `claude` for a best-effort metric, CLI transports (incl. Claude) report
  "unavailable" here; the Claude-JSON path is a separate follow-up to be developed
  against a real CLI with proper fallback. API transports are fully covered.

### Notes
- Tests: `tests/test_token_usage.py` (extractor incl. bool/partial edge cases,
  router copies usage onto the record / `None` when absent, `build_cli_usage`
  full + unavailable + partial) and `tests/js/usage.test.js` (`buildUsageText`).
  Gate: ruff + mypy + 462 pytest + 21 vitest.

## [2.7.0] — Milestone 27.0 — Live status core (CLI)

First half of the **M27 live-status & usage-telemetry epic** — **app bumped to
2.7.0**. Spec: `docs/specs/M27-live-status-and-usage.md`. Makes the CLI's
in-flight status line *live*: it now names the provider being tried right now
and shows fall-through across providers, instead of a generic "Working…".

### Added
- **Router progress callback** (`ProviderRouter.route(..., on_attempt=…)`): an
  optional, **measure-only** hook invoked with `{"provider", "transport",
  "mode"}` immediately before each *available* provider is called. Callback
  exceptions are swallowed — like diagnostics (M22), it can never change routing
  or the result. Unavailable/skipped providers are not announced (we only
  announce what's actually about to be called).
- **Live CLI status** (`cli/status.py`): `Spinner.set_text()` updates the label
  mid-flight (the animation loop reads it each frame), and `live_status_text()`
  formats the callback payload ("Trying claude/cli…"). `cli/main.py` passes a
  callback that drives the spinner. Still stderr-only and TTY-gated — piped
  stdout stays answer-only (M25 contract intact).

### Notes
- Synchronous routing is unchanged; the callback fires at attempt boundaries,
  which is enough for a live line without streaming (token-level streaming stays
  future work). Tests: router callback behaviour (fires per available provider,
  skips unavailable, a raising callback never breaks routing) + `set_text` /
  `live_status_text` units. Gate: ruff + mypy + 452 pytest + 17 vitest.

## [2.6.28] — Milestone 26.28 — Installable PWA (web UI)

User-visible frontend feature — **app bumped to 2.6.28**. Spec:
`docs/specs/M26.28-pwa.md`. Makes the browser UI installable (add-to-home-screen,
standalone display, app icon) so reaching a server instance from a phone over
Tailscale/VPN feels like an app.

### Added
- **Web app manifest** (`static/manifest.webmanifest`): `standalone` display,
  root `start_url`/`scope`, theme/background colors matching the dark UI, and
  `any` + `maskable` icons.
- **Icons** under `static/icons/` (192, 512, maskable-512, apple-touch-180).
- **Service worker** (`static/js/sw.js`) served at **`/sw.js`** (root scope)
  via a small route that substitutes the running version into the cache name, so
  each release drops the old shell cache on `activate` (same anti-stale
  discipline as the M26.1 `?v=` versioning). It caches **only the static shell +
  root navigation** (runtime caching, allowlist) and **never** dynamic/API
  responses — Athena is server-dependent, so faking offline answers would be a
  correctness bug.
- **Registration** (`static/js/pwa.js`) guarded by `'serviceWorker' in
  navigator`; template `<head>` gains the manifest link, `theme-color`,
  apple-touch-icon, and iOS standalone metas.

### Notes
- **Secure-context dependency (by design):** service workers + install require
  HTTPS or `localhost`. Over a plain `http://<tailscale-ip>` origin the worker
  never registers and the page runs as an ordinary tab — no errors. So the PWA
  only fully lights up once the TLS path (`tailscale serve` / reverse proxy +
  TLS) from `docs/PLATFORMS.md` is in place: it is polish on the remote-access
  pattern, not a replacement for it.
- Tests: `tests/test_pwa.py` (route + manifest + icons, 6) and
  `tests/js/pwa.test.js` (registration guard, 3). Gate green (ruff + mypy + 444
  pytest + 17 vitest).

## [Unreleased] — Milestone 26.27 — platform support & limitations docs

Documentation only — **no code change; the app stays at 2.6.25**. Spec:
`docs/specs/M26.27-platform-support-docs.md`.

### Added
- **`docs/PLATFORMS.md`** — an honest "Running Athena on <platform>" support
  matrix: **macOS** *Tested* (reference experience, both transports), **Linux**
  *Expected good* (POSIX + exercised by the CI matrix; recommended server),
  **Windows** *Works with caveats* (FastAPI/UI/API transports expected to run,
  but the **CLI provider adapters are POSIX-flavoured and untested on Windows** —
  use WSL2), **Container (Docker/LXC)** *API-transport-only by default* (vendor
  CLIs absent + need interactive login unless baked into the image), **Mobile**
  *no native app* (reach a server instance over Tailscale/VPN via the browser
  UI). Includes a **Remote access** section restating the no-auth posture and the
  two safe patterns (Tailscale/VPN or authenticated reverse proxy + TLS). This is
  the single source of truth the out-of-tree LXC installer and the (later)
  remote-access doc reference rather than restate.

### Changed
- `docs/README.md` links the new `PLATFORMS.md` from the "Getting started"
  section.

### Notes
- Deliberately honest about support *levels*: "Tested" (macOS) vs "Expected
  good" (Linux) vs "Works with caveats" (Windows/container) — the value is not
  over-promising an untested path to a future operator or agent. No code was
  touched; documenting current behaviour, not changing it.

## [Unreleased] — Milestone 26.26 — pre-commit hooks

Tooling only — **no code change; the app stays at 2.6.25** (the two whitespace/
final-newline fixes below are cosmetic). Spec: `docs/specs/M26.26-pre-commit.md`.
Depends on M26.23 (git).

### Added
- **`.pre-commit-config.yaml`** — fast, deterministic gates that run *before a
  commit is made*: **ruff** (`ruff-pre-commit` v0.15.11, check-only, matches CI),
  **mypy** (a `local`/system hook so it uses the project config exactly like
  `task typecheck`), and stock hygiene hooks (`end-of-file-fixer`,
  `trailing-whitespace`, `check-yaml`, `check-toml`, `check-merge-conflict`,
  `check-added-large-files`, `detect-private-key`). The full pytest/vitest
  suites deliberately stay in CI / `task ci` (too slow per-commit).
- `pre-commit==4.6.0` (dev dep); `task hooks:install` (one-time) and
  `task hooks:run` (all files).

### Changed / fixed (hygiene)
- Ran the hooks across the tree and applied their fixes so the repo is
  pre-commit-clean from day one: **final newlines** added to the 10
  `app/routers/*.py` files (an artifact of the M26.18 split's code generation)
  and **trailing whitespace** trimmed from two archived `docs/history/*.md`
  files. Behaviour-neutral; gate stays green (ruff + mypy + 438 tests).

### Notes
- **Activate once per clone:** `pre-commit install` (or `task hooks:install`) —
  this must be run on a machine with network access (pre-commit fetches the hook
  repos on first use), so it's a manual step, not baked into this commit.
- The ruff/mypy versions in `.pre-commit-config.yaml` are kept in **lockstep**
  with `requirements.txt` — bump them together (INVARIANTS). Emergency bypass:
  `git commit --no-verify`.

## [Unreleased] — Milestone 26.24 — Coverage measurement

Test-infra only — **no code change; the app stays at 2.6.25**. Spec:
`docs/specs/M26.24-coverage.md`.

### Added
- **Coverage measurement** (`pytest-cov==7.1.0`). Config in `pyproject.toml`
  `[tool.coverage]`: measures **application code only** (`tests/`, `.venv/`,
  `__init__.py` omitted) — the honest **source-only baseline is 74%** (an
  earlier ad-hoc `--cov` reported 86% only because it counted the test files
  themselves). `fail_under = 70` is a deliberate **ratchet-down floor set below
  74%**, not a target: the DAV/network clients are mocked but not fully
  exercised (they'd need live servers), so their coverage swings a few points —
  the headroom keeps honest refactors from tripping CI. Raise the floor as those
  gaps get real tests.
- `task coverage` (term-missing report) + `task coverage:html` (browsable
  `htmlcov/`). CI's pytest step now runs `--cov` so the floor is enforced on
  every push; `task ci` matches. `.coverage`/`htmlcov/` are gitignored.

### Notes
- Deliberately did **not** chase the number — coverage measures execution, not
  correctness (the M26.18 conflict bug ran with 438 tests green). The largest
  gaps are the DAV clients/routers (30–50%), which are network code covered at
  their critical paths by M26.12–M26.15's targeted tests; fully exercising them
  needs live servers and isn't worth mock-grinding here. Branch coverage
  (`--cov-branch`) is a possible future tightening.

## [2.6.25] — Milestone 26.25 — Dependency vulnerability scanning + CVE fix

Adds a dependency-audit gate **and remediates a real, measured finding**. Spec:
`docs/specs/M26.25-pip-audit.md`. (2.6.22–2.6.24 were not released —
M26.22/26.23/26.24 are infra/docs-only.)

### Security
- **Fixed 4 known CVEs in `python-multipart`** (`0.0.26 → 0.0.31`):
  PYSEC-2026-3036/3037 (fixed in 0.0.30), PYSEC-2026-3040 (0.0.31),
  PYSEC-2026-3039 (0.0.27). `python-multipart` is FastAPI's form-parser; Athena
  uses it only transitively (no active form/upload path), so the bump is
  low-risk — the full gate (ruff + mypy + 438 tests) stays green on 0.0.31, and
  `pip-audit` now reports **no known vulnerabilities**.

### Added
- **`pip-audit`** as the dependency-vulnerability gate (`pip-audit==2.10.1` in
  dev deps). `task audit` scans the pinned set (`-r requirements.txt --no-deps`).
  A CI step runs it **non-blocking** (`continue-on-error`) — a newly-disclosed
  upstream CVE surfaces in the report without red-walling an unrelated PR;
  triage locally with `task audit`. Tighten to blocking later if desired.

### Notes
- Pinned deps (M26.19) go stale silently; this is the watcher. `pip-audit`
  itself is pinned, but its advisory database updates over time — that's the
  point. INVARIANTS: pins must stay CVE-clean (`task audit`).

## [Unreleased] — Milestone 26.23 — Version control (git init)

Foundational, tooling only — **no code change; the app stays at 2.6.21**. Spec:
`docs/specs/M26.23-git-init.md`.

The project is now a **local git repository** (`git init` + a single initial
commit of the 2.6.21 tree). Before the first `git add`, the `.gitignore` was
verified to exclude `.env` (real credentials), the virtualenv, `node_modules/`,
`*.egg-info/`, and all runtime data (`data/`, logs) — a secret/data sweep of the
staged set came back empty (164 source/docs/config/test files tracked).

### Notes
- **No remote yet** — commit history is local; CI ([docs/CI.md](docs/CI.md))
  stays inert until a GitHub (or other) remote is added and pushed. Committer
  identity: `Innocent <InnocentK@users.noreply.github.com>` (repo-local, no global git
  identity was configured); amend the initial commit if you'd prefer different
  authorship before pushing anywhere.
- `docs/CI.md` activation steps and the `CLAUDE.md` milestone-loop "package"
  step updated to reflect that the repo is git-tracked (commits are the record;
  the zip-exclude list stays for the handoff-zip case).

## [Unreleased] — Milestone 26.22 — Frontend (jsdom) test harness

Test infrastructure + docs only — **no production code change; the app stays at
2.6.21** (docs/infra precedent, M26.11/M26.20). Spec:
`docs/specs/M26.22-js-test-harness.md`. Closes the long-deferred "JS/UI test
harness" roadmap item (M26.10 verified the UI by hand with Playwright; there was
no automated JS coverage).

### Added
- **`tests/js/` — a jsdom test suite (vitest) that runs the *unmodified*
  `static/js/chat.js` and `voice.js`.** `tests/js/loadChat.js` boots the real
  scripts in a jsdom DOM skeleton with a mocked `fetch`; a test-only shim footer
  exposes the module-scope helpers so the **production files are never touched**
  (chosen over the spec's Path-A refactor to avoid any production-JS risk).
  14 tests across three files:
  - **`sendMessage.test.js`** — the M26.10 behaviours, now real runtime tests:
    a `success:false` provider failure is **not** replayed into
    `conversationHistory` (verified end-to-end — the next request's history
    excludes it), a network failure shows exactly one message and records no
    assistant turn, an HTTP error surfaces the server `detail` (not a generic
    "network error"), empty input is a no-op; plus `appendMessage` XSS-safety
    (`textContent`) and error-bubble styling.
  - **`diagnostics.test.js`** — `buildDiagnosticsSummary` formatting cases.
  - **`voice.test.js`** — `voice.js` degrades safely where the Web Speech APIs
    are absent (jsdom), and an answer still renders when TTS is unsupported.
- **`package.json` + `vitest.config.js`** (dev-only; `node_modules/`
  gitignored), `task test:js`, and a separate `test-js` CI job (Node 20). The
  Python and JS suites are independent — a backend-only contributor needs
  neither Node nor the JS suite.

### Notes
- The Python-side source-structure guards (`test_chat_status_ui.py`,
  `test_ui_correctness.py`) are **kept** as belt-and-braces. Node stays strictly
  dev/CI — never a runtime dependency (the app is Python/Docker). Documented in
  `docs/INVARIANTS.md`. `docs/TESTING.md` gains a "Frontend tests" section.
- **`.dockerignore` updated** to exclude the new `node_modules/` + JS toolchain
  and `tests/` / `.github/` from the Docker build context — otherwise
  `COPY . .` would bake 100+ MB of dev-only files into the runtime image.

## [2.6.21] — Milestone 26.21 — mypy type gate (lenient)

Adds the type-level complement to the ruff name-level gate. Lenient by design —
catches real contract/narrowing gaps without demanding full annotation coverage.
Spec: `docs/specs/M26.21-mypy.md`. (2.6.20 was not released — M26.20 was
docs-only, per the 2.6.11 precedent.)

### Added
- **mypy** as the type gate. Config in `pyproject.toml` `[tool.mypy]`
  (`ignore_missing_imports`, `import-untyped` disabled for env-robust stub
  handling, tests excluded, `warn_unused_ignores` off for this first pass).
  `task typecheck`; added to `task ci`, the CI workflow, and the SessionStart
  hook (report-only). Pinned `mypy==2.3.0` + `types-PyYAML` / `types-requests`.

### Fixed (the 18 gaps mypy surfaced — real narrowing/annotation issues)
- **`providers/router.py`**: `trace.add(rec)` on a `RequestTrace | None` — the
  `rec`-is-non-None guard didn't narrow `trace`. Added `assert trace is not None`
  at the 4 sites (the invariant is `rec` non-None ⟺ `trace` non-None; documented).
- **`caldav_integration/client.py`**: `self._client`/`self._principal` were
  inferred `None`-only (assigned `None` in `__init__`), so every later
  `self._principal.calendars()` was an `attr-defined` error masked by a stale
  `# type: ignore`. Annotated both `: Any` and dropped the dead ignore.
- **`cli/main.py`**: `handler.stream = …` on a base `logging.Handler` (no
  `.stream`). Added `isinstance(handler, logging.StreamHandler)` to the guard —
  correct (only StreamHandlers have a stream) and defensive.
- **`app/routers/core.py`**: `update_profile`'s `provided` field-set was
  `Any | None` (so `in` checks and `_validate_routing_mode` tripped mypy).
  Narrowed to a definite `set[str]`; widened `_validate_routing_mode(mode)` to
  `str | None` (it already correctly 400s on `None`).
- **`app/routers/dav_status.py`**: dropped a heterogeneously-reassigned `client`
  variable (three client types, no common base) — bind `check_fn` directly.
- **`files/manager.py`**: `read_file` returns a `truncated: bool`, so its
  annotation is now `dict[str, Any]` (was `dict[str, str]`).

### Tests
- No new tests — all fixes are annotation/narrowing (the one logic touch, the
  cli isinstance guard, is behaviour-preserving for the real StreamHandler case).
  Suite: **438 passed**; ruff + mypy clean.

## [Unreleased] — Milestone 26.20 — CI gate

Tooling/docs only — **no code or behaviour change; the app stays at 2.6.19** (the
docs-only precedent set by M26.11). Spec: `docs/specs/M26.20-ci-workflow.md`.

Adds the project's CI gate: **lint + full suite**, needing no secrets (the suite
is fully mocked — M26.17). Because the project is **not yet under git**, the
GitHub workflow is inert until a remote exists, so this milestone also makes the
gate usable *today*:

### Added
- **`task ci`** — runs the exact CI sequence locally (`ruff check` →
  `pip install -e .` → `pytest -q`). One reproducible "is this shippable?" gate,
  no remote required.
- **`.github/workflows/ci.yml`** — GitHub Actions, matrix Python 3.10 (floor) +
  3.11 (tested). Checkout → setup-python (pip cache) → install requirements →
  editable install (proves packaging) → `ruff check` → `pytest`. Activates
  automatically on the first push to a GitHub remote.
- **`docs/CI.md`** — what CI checks, how to run it locally, and turn-key
  activation steps (`git init` → GitHub repo → push) plus a badge snippet.

### Notes
- CI needs no secrets or credentials — the hermeticity fixture (M26.17) means the
  suite never touches a real provider/network. Documented in `docs/INVARIANTS.md`.

## [2.6.19] — Milestone 26.19 — Ruff lint gate + pinned dependencies

Adds the project's first automated correctness gate besides the test suite, and
makes the environment reproducible. Spec: `docs/specs/M26.19-ruff-and-pinning.md`.

### Added
- **Ruff** as the lint gate. Config in `pyproject.toml` `[tool.ruff]`:
  `select = ["E4","E7","E9","F","B"]` — correctness-strict (undefined/unused
  names, exception-chaining, bugbear footguns), style-lenient (isort and
  `ruff format` deliberately deferred to avoid a whole-tree reformat).
  `task lint` / `task lint:fix`; the SessionStart hook now runs ruff as a fast
  report-only step before the suite.

### Fixed (the 56 violations ruff surfaced)
- Removed ~21 unused imports (mostly leftovers from the M26.18 split) and a
  duplicate `MagicMock` import; deleted two dead locals (`in_component` in
  `dav_io/ics_io.py`, an unused `tmp_project` in a weak conflict test — replaced
  with a comment pointing at the real round-trip coverage); renamed an ambiguous
  `l` loop var.
- Added the missing `from pathlib import Path` to `main.py` (the
  `_safe_export_path(...) -> Path` annotation referenced an undefined name;
  harmless under `from __future__ import annotations` but now correct).
- **Exception chaining on 30 re-raises** (`B904`): `raise … from exc` where the
  handler binds the cause, `from None` for expected timeout/validation
  conversions. Behaviour-neutral; makes server-log tracebacks precise.
- **Guard:** `main.py`'s `write_ops_event` import (reached by routers via
  `main.write_ops_event`) is marked `# noqa: F401 (router-facing re-export)` —
  `ruff --fix` had removed it as "unused" and broke every audit-logging handler
  until restored. Documented in INVARIANTS.

### Changed
- **`requirements.txt` pinned to exact tested versions** (`==`) for
  reproducibility — this is an app, not a library. Bumping a pin is now a
  deliberate, tested act (some behaviour is version-dependent: caldav ≥3
  `timeout=` forwarding, defusedxml entity rejection). Added `ruff==0.15.11` to
  dev deps.

### Tests
- No new tests (this is a tooling/cleanup milestone); all fixes are
  behaviour-neutral. Suite: **438 passed**, ruff clean.

## [2.6.18] — Milestone 26.18 — main.py router split

Closes the review's highest-leverage ergonomics finding (O1): `main.py` was a
2,638-line monolith of 77 routes. It's now a **725-line assembly + state layer**;
the route handlers live in one `APIRouter` module per domain, so a future agent
can edit a single domain without loading the whole file. **No behaviour change** —
the OpenAPI path set is byte-for-byte identical to pre-split and all 436 tests
pass unchanged.

### Added
- `app/models.py` — the 21 Pydantic request/response models (+ `ProfileUpdate`),
  moved out of `main.py`. Pure data; imported by both main and the routers.
- `app/routers/{core,memory,saved,voice,files,caldav,carddav,nextcloud,backup,
  dav_status}.py` — one `APIRouter` per domain. `main.py` `importlib.reload`s and
  includes them as it assembles the app.

### Changed
- `main.py` (2,638 → 725 lines) keeps only the app assembly and the state layer:
  module state + timeout constants, the `_require_*` accessors, the shared
  helpers (`_safe_export_path`, `_write_audit`, the conflict-file helpers, the
  profile helpers), the lifespan, exception handlers, static/template mounts, and
  the `GET /` index route.
- **Router handlers reach app state through `main.<name>` (after a module-level
  `import main`), never `from main import <name>`.** This is required for the
  test suite, which swaps the `main` module per test; a captured reference would
  read stale state. The reload-on-include loop rebinds each router to the live
  main. Documented as an invariant so it isn't "cleaned up" into a stale import.

### Tests
- No test changes needed for the split itself — it preserves `main`'s
  module-level attribute surface (state, `_require_*`, helpers, timeout
  constants), so every existing `monkeypatch.setattr(main, …)` still targets
  the live symbol. OpenAPI path set unchanged (76 API routes).

### Fixed (post-split review)
- **Conflict-queue endpoints were broken by the split's mechanical renaming**:
  the filename-suffix string literals `"_carddav"`/`"_caldav"` passed to the
  conflict-file helpers were accidentally rewritten to `"main._carddav"` /
  `"main._caldav"`, so `GET /{carddav,caldav}/conflicts` always returned `[]`
  and get/resolve always 404'd (imports still *wrote* conflict files correctly
  — only the endpoints looked in the wrong place). The existing endpoint tests
  couldn't see it (they only assert empty-list-200 and missing-batch-404), so
  two **API-level conflict round-trip regression tests** were added (write a
  real conflict file → list shows it → get returns it → resolve-skip updates
  the same file end-to-end) for both DAV domains.
- Trimmed the split's copied-everywhere import preambles down to what each
  router actually uses (and repaired one import-name corruption the trim
  itself introduced — every from-import name is now programmatically verified
  to resolve); refreshed `main.py`'s module docstring and `app/__init__.py`'s
  description of the `import main` + reload pattern to match the shipped
  mechanism; removed a leftover empty section banner.
- Suite: **438 passed** (436 + 2 round-trip regressions).

## [2.6.17] — Milestone 26.17 — Docs & version single-source + SessionStart hook

Closes review findings O2–O6 and ships the SessionStart hook deferred from
M26.11 (Workstream 7), plus a test-hermeticity fix found while building it.

### Added
- **`core/version.py` — the single version bump site.** `main.py` imports
  `__version__` (→ `/health`), `pyproject.toml` reads it via
  `[tool.setuptools.dynamic]` (editable install verified), and the health test
  became `test_health_version_matches_single_source` (asserts `/health` equals
  the constant). The old three-anchor manual sync is gone; on a release, bump
  one file.
- **SessionStart hook** — `.claude/settings.json` +
  `scripts/session-start-check.sh` (travels with the repo, so Claude Code
  web/CLI sessions get it too). At session start it reports deps status and
  runs the suite (`-x` fail-fast; ~30s green), always exiting 0 — a red
  baseline informs ("failures are PRE-EXISTING") but never blocks.
- **Package `__init__.py` orientation headers** for the six formerly-empty
  ones (`dav_io`, `dav_status`, `caldav_integration`, `carddav_integration`,
  `nextcloud_integration`, `backup`): what each owns, what it does **not**
  (the local-parse vs network-client distinction), and where its tests live.
- **Route → test map** in `docs/TESTING.md` (route prefix → test file), so the
  right file to extend is look-up-able instead of tribal knowledge.

### Fixed
- **Test-suite hermeticity: provider CLIs can no longer really run.** The
  router fixtures copy the real `providers.yaml`, and `is_available()` is
  `shutil.which`-based — on any machine with `claude`/`gemini`/… on PATH
  (a dev box, an agent sandbox), an unmocked `route()` invoked the **real**
  CLI: observed live as one router test jumping from <1s to 120.15s (the full
  subprocess timeout), and on a real workstation it would burn actual tokens.
  An autouse conftest fixture now blanks `which()` for the provider binary
  names suite-wide (tests that exercise "CLI available" paths patch deeper
  themselves and are unaffected). Suite runtime restored to ~30s.
- **Stale 127-line milestone log removed from `main.py`'s docstring** (it
  stopped at M14 while the app is at 2.6.x — the first thing an agent read in
  the entry-point was wrong). Replaced with a 12-line orientation docstring;
  history lives in this changelog.
- **The two component maps no longer disagree.** `docs/ARCHITECTURE.md`'s tree
  gained the six packages it omitted (`diagnostics`, `backup`, `audit`,
  `dav_io`, `dav_status`, `saved`... and `core/version.py`/`core/urlguard.py`),
  and both it and `CLAUDE.md`'s map now state they mirror each other.
  `CLAUDE.md` also documents the `manager.py`/`store.py`/`client.py` naming
  convention and the `saved/`-vs-data, `config/`-vs-`core/config.py`
  look-alikes, and its "Suggested first actions" now leads with the hook.

### Tests
- Suite: **436 passed** (unchanged count; the health-version test was
  rewritten, the hermeticity fixture is infrastructure).

## [2.6.16] — Milestone 26.16 — Consistency & thread-safety pass

Closes review findings S3, C6, C7 and two standards items
(`docs/history/REVIEW-2026-07.md`).

### Fixed
- **`DavStatusStore` and `DiagnosticsStore` are now lock-guarded.** Their old
  header comments reasoned "single-worker uvicorn → no thread safety needed",
  conflating processes with threads: DAV clients and `route()` mutate these
  singletons from `asyncio.to_thread` worker threads while routes snapshot
  them on the loop thread — an unlocked `deepcopy`/deque-iteration during a
  concurrent update raises ("dictionary changed size during iteration" /
  RuntimeError). All access now holds a `threading.Lock`; comments corrected.
- **`MemoryManager` YAML read-modify-write is serialised.** `auto_extract`
  (worker thread) and `approve`/`discard` (loop thread) rewrite the same
  `pending_review.yaml`; unserialised, the last writer silently won. The
  public read/modify methods now share an `RLock` (nesting:
  `auto_extract → add_to_pending`, `approve_pending → add_memory`).
- **`backup_inspect` routes through `_safe_export_path`** like diff /
  download / delete — it was the one exports route building the path from the
  raw parameter (defense-in-depth; INVARIANTS already claimed full coverage).

### Changed
- **`humanise_error` is public** on `DavStatusStore` (the three DAV clients
  called the private `_humanise_error` from outside the class); callers
  migrated, `_humanise_error` kept as a compat alias.

### Tests
- New `tests/test_thread_safety.py` (6 tests): concurrent-hammer regressions
  for both stores, a lost-update regression for the pending queue (8 racing
  threads, zero lost writes), the public/alias contract, and the inspect
  guard (spy + valid-zip 200). Suite: **436 passed** (430 + 6).

## [2.6.15] — Milestone 26.15 — Nextcloud correctness, shared logger, hardened XML

Closes review findings C4, S4 and the logger standards item
(`docs/history/REVIEW-2026-07.md`).

### Fixed
- **Nextcloud search no longer silently degrades on special characters.**
  `search_files` interpolated the query and DAV root into the DASL XML body
  unescaped — a query containing `&`, `<`, or `>` produced malformed XML, the
  server returned non-207, and the code quietly fell back to `list_files` +
  local filtering (wrong/incomplete results). Both values are now XML-escaped
  (`xml.sax.saxutils.escape`); LIKE `%` wildcards are unaffected.
- **Nextcloud client now logs through the shared `core.logger`** (was
  `logging.getLogger(__name__)`, whose records skipped Athena's
  handler/formatter — the only subsystem that did).

### Security hardening
- **Server-controlled XML parses via defusedxml.** Nextcloud and CardDAV
  multistatus bodies are parsed with `defusedxml.ElementTree.fromstring` —
  entity definitions and external references from a (compromised) server are
  rejected instead of expanded (billion-laughs DoS). Nextcloud wraps parse
  failures in `NextcloudConnectionError` (`_parse_multistatus`); CardDAV's
  existing broad wrapper does the equivalent. New runtime dependency:
  `defusedxml` (tiny, pure-Python) in `requirements.txt`.

### Tests
- New `tests/test_nextcloud_correctness.py` (4 tests): escaped+well-formed
  search body with no fallback, shared-logger identity, and entity-bomb
  rejection in both clients. Suite: **430 passed** (426 + 4).

## [2.6.14] — Milestone 26.14 — File-read robustness & local-I/O offload

Closes review findings C3 and C5 (`docs/history/REVIEW-2026-07.md`).

### Fixed
- **`GET /files/read` no longer 500s on binary files.** `FileManager.read_file`
  previously did a bare `read_text(encoding="utf-8")`: a binary or non-UTF-8
  allowlisted file raised an unhandled `UnicodeDecodeError`. It now decodes
  with `errors="replace"` (replacement characters, clean 200).
- **Reads are size-capped.** `read_file` returns at most 2MB
  (`_MAX_READ_BYTES`, deliberately equal to the Nextcloud streaming cap) and
  reports `truncated: true` beyond it — a huge allowlisted file can no longer
  be buffered whole. The response gained an additive `truncated` key.

### Changed
- **Heavy local disk I/O runs off the event loop.** `/files/search` (rglob
  across roots), `/files/read`, and backup **create / list / inspect / diff**
  are now wrapped in `asyncio.to_thread` like the network paths
  (`backup_restore` already was). Deliberately no `wait_for` deadline: local
  disk has no network-style hang mode, a big export legitimately takes time,
  and a timeout can't cancel the thread anyway. `docs/INVARIANTS.md`'s "local
  I/O intentionally unwrapped" note updated accordingly — only trivially small
  YAML/JSON I/O stays inline.

### Tests
- 3 manager tests (binary decode, 2MB cap, small-file round-trip), 1 API
  regression (binary → 200), 1 concurrency test (slow `/files/search` doesn't
  block `/health`). Suite: **426 passed** (421 + 5).

## [2.6.13] — Milestone 26.13 — DAV SSRF guard

Closes the July 2026 review's top security finding (S1, HIGH): the CalDAV /
CardDAV endpoints accepted **full URLs** (`calendar_url`, `address_book_url`,
hrefs) and attached the configured Basic-Auth credentials to whatever host the
URL named. A prompt-injected assistant could exfiltrate the DAV credentials
(`?calendar_url=http://attacker/…`) or reach internal-only services
(cloud-metadata IPs, LAN hosts). Nextcloud was never affected (fixed base).

### Added
- **`core/urlguard.py`** — `ensure_same_origin(url, base, label)` +
  `DAVSecurityError`. A caller-supplied URL is accepted only if it is relative
  (joined onto the configured base) or matches the configured server's
  scheme+host+port (default ports normalised; userinfo ignored on hostname so
  `https://trusted@evil/` compares `evil`; unparseable ports rejected).
- **App-level `DAVSecurityError` handler** in `main.py` → HTTP **400** with the
  reason (never 5xx, never egress).

### Changed (enforcement points)
- `CardDAVClient._request` validates every URL — the M26.12 chokepoint means
  this covers list/search/fetch, vCard import PUT/GET, `commit_merge`
  PUT/DELETE, `delete_contact`, and the conflict-overwrite PUT. The client's
  broad `except Exception → CardDAVConnectionError` wrappers explicitly
  re-raise `DAVSecurityError` so it reaches the 400 handler instead of being
  re-labelled 502.
- `CalDAVClient` gained `_check_url()`, called as the **first** statement of
  `list_events` / `list_tasks` / `create_task`.
- `import_ics` / `import_vcf` fail fast on an off-origin target (their bodies
  otherwise warn-and-continue, and `import_ics` builds `caldav.Calendar`
  directly, bypassing client methods).
- Route-level checks where errors are swallowed by design: `/caldav/export`
  (best-effort empty-file contract) and the CalDAV conflict-overwrite push
  (`except Exception → 502`).

### Tests
- New `tests/test_dav_ssrf.py` (21 tests) — unit matrix, client-level
  no-network-I/O proofs, import fail-fast, API-level 400s. Existing mocked
  clients in `test_dav_io.py` / `test_dav_correctness.py` gained a `_url`
  attribute (the real clients always have one).
- Suite: **421 passed** (400 + 21).

### Docs
- `docs/SECURITY.md`: new "Network egress" section. `docs/INVARIANTS.md`: new
  "Network egress (M26.13) — security" section listing every enforcement point
  and the known redirect limit. `docs/TESTING.md`: new row.

## [2.6.12] — Milestone 26.12 — DAV transport timeouts

Closes the top finding of the July 2026 review (`docs/history/REVIEW-2026-07.md`,
S2/C1/C2 — flagged independently by both the correctness and security streams):
CardDAV and CalDAV network calls had **no socket timeout**. The route-level
`asyncio.wait_for` returns a timely 504 but cannot cancel the worker thread, so
a hung DAV server pinned a `to_thread` executor slot forever; enough such calls
would exhaust the pool and freeze all offloaded work. This also made
SECURITY.md's "bounded timeouts" claim false for CardDAV/CalDAV (Nextcloud
already passed `timeout=15`). Version 2.6.11 is intentionally skipped — M26.11
was docs-only and shipped no release.

### Fixed
- **CardDAV transport is bounded.** `CardDAVClient._request` now applies an
  explicit default socket timeout (`_HTTP_TIMEOUT = 15`, matching Nextcloud);
  callers may override via `timeout=`.
- **CalDAV transport is bounded.** `caldav.DAVClient` is constructed with
  `timeout=_CONNECT_TIMEOUT` (15s; the installed caldav 3.x forwards it to its
  HTTP session).

### Changed
- **All CardDAV HTTP now flows through the `_request` chokepoint.** The two raw
  `requests.request` calls (`commit_merge`'s source-contact DELETE loop and
  `delete_contact`) were routed through `_request(..., check=False)`, which
  returns non-2xx responses for caller-side status handling while still raising
  `CardDAVConnectionError` on network errors. Behaviour is preserved (404/non-ok
  logging in `commit_merge`; 204→True / 404→error in `delete_contact`); the
  single chokepoint is also where M26.13's URL validation will live.

### Tests
- New `tests/test_dav_transport.py` (7 tests): default timeout applied, caller
  override honoured, `check=False` semantics, network-error behaviour,
  `delete_contact` flow, a source-level guard that `requests.request` appears
  exactly once in the CardDAV module, and CalDAV `DAVClient(timeout=…)`.
- Suite: **400 passed** (393 + 7).

### Docs
- `docs/INVARIANTS.md`: new "every outbound DAV HTTP call sets an explicit
  socket timeout" rule under Concurrency, with the chokepoint do-not-bypass
  note. `docs/SECURITY.md`: bounded-timeouts claim now notes transport-level
  enforcement. `docs/TESTING.md`: new test-file row; the ops-hardening row no
  longer hardcodes the version string.

## [Unreleased] — Milestone 26.11 — Docs & handoff consolidation

**Docs and handoff only — no code or behaviour change; the app stays at 2.6.10
and the test suite is unchanged.** Restructures the agent-handoff and docs layer
so it's durable, portable, and doesn't drift.

### Changed
- **`CLAUDE.md` moved into the repo and slimmed.** The canonical agent handoff is
  now `athena-assistant/CLAUDE.md` (so it packages with the code); the parent
  `Athena/CLAUDE.md` is a pointer stub. It dropped the append-only milestone list
  (history lives here in the changelog) and stopped hardcoding the version/test
  count (they drift) — down from ~41KB to a stable ~9KB core.
- **`RUN_AND_VALIDATE.md` split.** Its ~1,500-line milestone-by-milestone
  validation log moved to `docs/history/RUN_AND_VALIDATE-milestones.md`; current
  smoke checks are a lean new `docs/VALIDATION.md`; the old filename is now a
  pointer stub. The automated suite is the authoritative regression gate.
- **`HANDOFF.md` and `RUNBOOK.md` de-staled.** HANDOFF is now a short operator
  reading-order; RUNBOOK's health/version and log-path (`logs/app.log`) are fixed
  and its Backup section uses the built-in backup feature instead of a manual
  `tar`. Swept remaining hardcoded `1.0.0` and the wrong `task test:all`
  (→ `task test:run`) out of the docs.
- **`MILESTONE_16_NEXT_STEPS.md`** (completed planning brief) archived to
  `docs/history/`.

### Added
- **`docs/INVARIANTS.md`** — the "do not break these" contract: every load-bearing
  mechanism/safety guarantee (concurrency wrapping, write-safety guards, provider
  bounding, ICS formatting, UI correctness, CLI logging, …) with its enforcing
  test, grouped by subsystem. Extracted from CLAUDE.md's constraints + known
  risks.
- **`AGENTS.md`** (repo root) — points cross-tool agents at `CLAUDE.md`.
- **`docs/global-claude-template.md`** — project-agnostic agent norms to copy to
  `~/.claude/CLAUDE.md` so the discipline is portable to other projects.
- **`docs/BACKUP.md`** — user docs for the built-in backup/restore subsystem
  (previously undocumented for users).
- **`docs/SECURITY.md`** — what Athena protects and how (allowlist, Zip-Slip
  guard, CardDAV gating, credential handling, bounded timeouts), linking to
  INVARIANTS.md.
- **`docs/README.md`** — a "which doc do I want?" index for the doc set.

## [2.6.10] — Milestone 26.10 — Web UI correctness

### Fixed
- **Failed answers polluted conversation history.** The browser recorded the
  assistant turn before checking `success`, so `"All providers failed."` (or a
  timeout message) was stored and replayed to providers on every later message.
  The assistant turn is now recorded only on a successful response.
- **Render/TTS errors were reported as "Network error".** A single broad `catch`
  wrapped both the request and the rendering, so a throw in diagnostics rendering
  or `voice.speak` produced a spurious "Network error" bubble after a good answer.
  The network `catch` now guards only the fetch/parse; rendering runs outside it,
  with a `try/finally` guaranteeing the input-state reset.
- **A missing `voice.js` broke the whole UI.** `voice.isSupported`/`isTTSSupported`
  were accessed unguarded, so a failed `voice.js` threw a `ReferenceError` that
  aborted init (dead send button / panels). Both are now guarded with
  `typeof voice !== "undefined"`, and `voice.speak` is wrapped.
- **Settings save could silently clear `preferred_provider` / reset `mode`.** If
  `GET /providers` failed (or the configured provider wasn't listed), the
  `<select>` fell back to its first option and a prompt-only save wiped the
  provider. The canonical value is now always injected as a selectable option, so
  the control faithfully shows and submits the configured value; a muted note is
  shown when the provider list can't be loaded.
- **Panel tab-switch race.** Switching Memory/Settings/History tabs during a slow
  fetch could append the older tab's content beneath the newer tab's. Each async
  panel loader now carries a per-panel load token and bails if superseded; the
  post-save Profile re-render only runs if the Profile tab is still active.
- **`.history-count` was unstyled.** Added the missing CSS rule (and a
  `.settings-note` rule for the new provider-list-unavailable note).

### Added
- `tests/test_ui_correctness.py` (7 source-structure guards) locking each fix.
  Behaviour was also verified live with a headless browser (Playwright) during
  implementation — failed-answer non-replay, accurate error reporting, UI
  survival without `voice.js`, and canonical-provider selectability when
  `/providers` fails — see `docs/TESTING.md`.

### Notes
- Frontend-only (`static/js/chat.js`, `static/css/chat.css`); no backend or
  API-shape change. The `?v={app.version}` cache-busting (M26.1) makes upgraded
  browsers fetch the new assets. **This completes the post-review fix series
  M26.5–M26.10.**

## [2.6.9] — Milestone 26.9 — Calendar / DAV correctness

### Fixed
- **ICS export corrupted event times.** `dav_io/ics_io.py` built DTSTART/DTEND/DUE
  by string-stripping the ISO value and always appending `Z`, which shifted
  offset-bearing times (`10:00+02:00` was emitted as `10:00Z` — a 2-hour error),
  declared naive times as UTC, and mangled negative offsets. A new
  `_format_ics_datetime` parses to a real datetime and emits proper UTC-with-`Z`
  for offset-aware values or floating (no `Z`) for naive ones; date-only values
  are unchanged.
- **ICS text fields could inject or malform properties.** SUMMARY/DESCRIPTION/
  LOCATION (in `_reconstruct_component`) and SUMMARY/DESCRIPTION (in CalDAV
  `create_task`) were interpolated raw, so a value containing a newline/comma/
  semicolon injected content lines or produced malformed output. A shared
  `escape_ics_text` now escapes per RFC 5545 §3.3.11.
- **DavStatusStore leaked internal state.** `get()`/`get_all()` returned shallow
  copies, so a caller mutating a nested `item_counts`/`warnings`/etc. corrupted
  the singleton. They now return deep copies.
- **Nextcloud `read_file` buffered the whole body before the 2MB cap.** It now
  streams (`stream=True` + `iter_content`) and stops the moment the running total
  exceeds the cap, so an oversized remote file is never fully loaded into memory.
- **Backup manifest mislabelled the app version.** `app_version` was a hardcoded
  `"1.3.0"`; it now derives from the real `app.version` (passed into
  `BackupManager`), keeping the FastAPI version the single source.
- **vCard multi-value email/phone were dropped on reconstruct.** `parse_vcf_string`
  now captures all values as `emails`/`phones` lists (singular `email`/`phone`
  kept as the first value for compatibility), and `export_vcf`'s reconstruct path
  prefers the lists — so a contact with several emails/phones no longer loses the
  extras. (The primary server-fetch export path already preserved them.)

### Added
- `tests/test_dav_correctness.py` (14 tests) covering all six fixes: ICS datetime
  formatting (offset/negative/naive/Z/date-only/fallback), ICS text escaping
  (reconstruct + create_task), status-store deep-copy isolation, Nextcloud
  streamed-cap behaviour, manifest version, and vCard multi-value round-trip.

### Notes
- No new dependencies. The one behaviour change with real surface area is the ICS
  datetime formatter (now correct instead of corrupting); everything else is
  additive/localized. All affected integrations are disabled by default.

## [2.6.8] — Milestone 26.8 — Provider robustness

### Fixed
- **ChatGPT API had no timeout or retry bound.** `providers/chatgpt.py` created
  `openai.OpenAI()` with SDK defaults (600s read × up to 3 tries ≈ 30 min worst
  case) and mapped a stall to a generic failure. It now uses
  `openai.OpenAI(timeout=…, max_retries=0)` with an `OPENAI_TIMEOUT` env
  (default 120s) and catches `APITimeoutError`/`APIConnectionError` explicitly —
  mirroring the Grok API path — so a stall returns a clean `success=false`
  (classified as `timeout` in diagnostics) instead of hanging a worker.
- **Grok transport mislabelled in diagnostics.** `ProviderRouter._transport_for`
  fell back to the static `providers.yaml` `type` on `unavailable`/`skipped`/
  `exception` records, so with `GROK_TRANSPORT=api` and no key the trace read
  "grok/cli unavailable" when the API key was what was missing. It now consults
  the adapter's `transport()` (like `list_providers()` since M26.2), so records
  report the real transport.
- **Unknown routing mode silently inverted cost.** `_get_ordered_names` mapped an
  unrecognized mode (e.g. the underscore typo `budget_first`) to the
  most-expensive `quality_first` order with no log. It now logs a warning and
  falls back to **`balanced`** (the neutral middle). *Intentional behaviour
  change on the previously-silent unknown-mode path.*
- **Saved-action / CLI routing overrides were unvalidated.** `POST`/`PATCH
  /saved/actions` now reject an invalid `mode` or unknown `provider` with **400**
  (same rules as `PATCH /profile`, via a shared validator), and the CLI
  `--provider` flag now fails with a clear "unknown provider" message and
  **exit 2** instead of silently ignoring a typo. `--mode` was already validated.
- **CLI adapters hardened.** `claude`, `gemini`, `grok`, and `hermes` subprocess
  calls now pass `stdin=subprocess.DEVNULL` (no hang on an interactive prompt)
  and `encoding="utf-8", errors="replace"` (a stray byte no longer turns a good
  run into a decode error).

### Added
- `tests/test_provider_robustness.py` (11 tests): ChatGPT timeout/connection
  mapping + bounded-client kwargs; CLI-subprocess `stdin`/encoding for all four
  adapters; unknown-mode→balanced + warning; and the router reporting a dynamic
  adapter's real `transport()` on unavailable records. Plus saved-action
  validation cases in `test_saved_api.py` and `--provider` cases in `test_cli.py`.

### Notes
- No new dependencies; no response-shape changes (validation adds 400s only).
  `OPENAI_TIMEOUT` joins `GROK_TIMEOUT` as an optional env knob (default 120s).

## [2.6.7] — Milestone 26.7 — Filesystem write-safety

### Security / Fixed
- **Memory category path traversal.** `POST /memory` (and `MemoryManager.add_memory`)
  passed a caller-supplied `category` straight into a file path, so
  `{"category":"../evil",...}` wrote `profiles/athena/evil.yaml` outside the
  memory directory (deeper `../` escaped the profile tree entirely).
  `MemoryManager._category_path` — the single chokepoint for every category file
  — now rejects any stem not in the known allowlist (`CATEGORIES` +
  `pending_review`), and the API returns a clean **400** for an unknown category.
- **Backup restore Zip-Slip.** `restore_backup` / `diff_restore` joined zip member
  names to the app root with no containment check, so a member like
  `../../x.txt` (or an absolute path) wrote outside the app root. Every member is
  now resolved through `_safe_target` and skipped unless it stays within the app
  root; escaping members are counted under a new `rejected` field and surfaced in
  the diff/restore `warnings`. Legitimate in-root members restore unchanged.
- **`diff_token` not bound to its backup.** A restore `diff_token` recorded only
  an expiry, so a token from `A.zip`'s diff authorized restoring `B.zip`. Tokens
  are now stored as `(zip_filename, expiry)` and the confirm restore requires the
  token to have been issued for that exact filename (else **409**).
- **`zip_filename` traversal in restore.** `POST /backup/restore` resolved the
  body's `zip_filename` under `data/exports/` with no guard, so `../` escaped it.
  A shared `_safe_export_path` helper (now used by the restore, diff, download,
  and delete endpoints) rejects traversal and absolute paths with a **400**.

### Added
- `tests/test_write_safety.py` (13 tests) — regression guards for all four holes
  above: memory-category rejection (API + manager), Zip-Slip containment
  (relative and absolute escapes), `diff_token`↔filename binding, and the
  `zip_filename`/export-path guard. Self-contained; real temp zips, no network.

### Notes
- Guards are additive and reject-only — normal categories, in-root zip members,
  and ordinary export filenames all pass unchanged. The only structural change is
  the `_restore_diff_tokens` value type (`float` → `(filename, expiry)`),
  contained to `main.py` and its tests. Restore/diff results gain a `rejected`
  field (additive). Out of scope (tracked separately): the restore `force`-flag
  no-op and the hardcoded manifest `app_version`.

## [2.6.6] — Milestone 26.6 — CLI logging isolation & test-suite restoration

### Fixed
- The one-shot CLI no longer corrupts other code's log handlers. To keep stdout
  answer-only, `cli/main.py::_configure_cli_logging` redirects Athena's console
  logs to stderr — but it did this by reassigning `.stream` on **every** handler
  attached to the shared, non-propagating `"athena"` logger. Because pytest's
  logging plugin attaches its own `StringIO`-backed capture handler to that
  logger, the CLI clobbered pytest's handler stream, and every CLI test that
  reached this code failed with `AttributeError: 'EncodedFile' object has no
  attribute 'getvalue'` / `ValueError: I/O operation on closed file` (16 tests).
  The CLI now retargets **only** Athena's own console handler, which is tagged
  `_athena_console = True` in `core/logger.py`. Foreign handlers are left
  untouched. **The full test suite is green again (342 passing, 0 failing).**

### Added
- `tests/test_cli.py::test_configure_cli_logging_only_touches_tagged_handler` —
  a direct regression guard: a foreign (untagged) handler on the `"athena"`
  logger keeps its stream after `_configure_cli_logging`, while the tagged
  console handler is retargeted to stderr.

### Notes
- Runtime CLI behaviour is unchanged: stdout still carries only the answer and
  Athena's logs still go to stderr. Two tiny, behaviour-preserving edits
  (`core/logger.py` tag + `cli/main.py` filter); no new dependencies.

## [2.6.5] — Milestone 26.5 — Concurrency hardening

### Fixed
- The FastAPI event loop no longer blocks while a provider generates or a remote
  integration is queried. Every `async` handler that ran synchronous
  provider/DAV/Nextcloud code directly on the event loop — so the whole server
  (including `/health`, static assets, and every panel fetch) was frozen for the
  duration of the call — now runs that work in a worker thread via
  `asyncio.wait_for(asyncio.to_thread(...), timeout=...)`, matching the pattern
  already used by `PATCH /profile`, backup restore, and the DAV status check.
  Wrapped call sites:
  - `POST /chat` (`route()` + memory `auto_extract`) and `POST
    /saved/actions/{id}/run` (`route()`).
  - `GET /providers` **and** the `list_providers()` availability probe inside
    `PATCH /profile` (both probe adapters; Ollama does a network health check).
  - **All** CalDAV endpoints: `GET /caldav/calendars|events|tasks|export`, `POST
    /caldav/tasks` (create), and the CalDAV conflict-resolve write.
  - **All** CardDAV endpoints: `GET
    /carddav/addressbooks|contacts|contacts/search|duplicates|export`, `POST
    /carddav/merges` (stage), `DELETE /carddav/contacts`, and the CardDAV
    conflict-resolve write. (Local-only staged-merge reads/discard are left
    unwrapped — they touch local files, not the network.)
  - **All** Nextcloud endpoints: `GET
    /nextcloud/ping|user|files|files/read|files/search|notes|notes/{id}|activity`.

### Changed
- **Bounded request time (intentional behaviour change):** the wrapped calls now
  enforce timeouts. A single `ProviderRouter.route()` call is capped at
  `_ROUTE_TIMEOUT` (130s — each CLI adapter already self-limits at 120s); on
  timeout `/chat` and saved-action run return a clean `success=False` response
  ("The request timed out.") instead of hanging or 500ing. `GET /providers`
  (and the `PATCH /profile` probe) return 503 on their `_PROVIDERS_TIMEOUT`
  (15s). CalDAV/CardDAV/Nextcloud endpoints return **504** on their DAV timeouts
  (`_DAV_READ_TIMEOUT`/`_DAV_WRITE_TIMEOUT`, 30s) — except `GET /nextcloud/ping`
  (keeps its reachability-status contract → `{reachable: false, error}`) and
  `GET /caldav/export` (keeps its best-effort contract → empty calendar).
  Memory auto-extraction is capped at 10s and remains best-effort (a timeout is
  logged and never fails an answered chat).

### Added
- `tests/test_concurrency.py` (6 tests) — proves `/health` stays responsive
  while a slow `/chat` **and** a slow CalDAV read are in flight, and that forced
  route / auto-extract / `/providers` / DAV-read timeouts degrade cleanly (clean
  `success=false`, non-fatal memory hang, 503, 504 — never a hang or 500).

### Notes
- `main.py`-only change plus the new test file. No router/adapter/provider
  refactors, no new dependencies, no API-shape changes. Timeout constants live at
  the top of `main.py`: `_ROUTE_TIMEOUT=130`, `_AUTO_EXTRACT_TIMEOUT=10`,
  `_PROVIDERS_TIMEOUT=15`, `_DAV_READ_TIMEOUT=30`, `_DAV_WRITE_TIMEOUT=30`.
- On a route timeout, `asyncio` cannot cancel the worker thread, so the
  underlying provider attempt keeps running to its own limit and is discarded in
  the background — the client still gets a prompt timeout response. Noted in-code.
- The `_profile_data` read in `/chat` and the `_restore_diff_tokens` dict are now
  theoretically concurrent-accessible; this is safe under single-worker uvicorn
  and is noted in-code — a lock would only matter under a multi-worker deployment.

## [2.6.4] — Milestone 26.4 — Docs, CLI packaging & install flow

### Fixed
- `athena` / `ask` CLI failing after `pip install -e .` with
  `Error: failed to load Athena modules: No module named 'diagnostics'`. The
  `[tool.setuptools] packages` list omitted the `diagnostics` (M22) and `saved`
  (M18) packages, so an editable install did not expose them. Both are now
  declared and the install flow is verified end-to-end.

### Changed
- Documentation restructured: the README is now lean (what Athena is, quick
  install/run, CLI usage, links). Milestone/release history moved here.

### Added
- `CHANGELOG.md`, `docs/INSTALLATION.md`, `docs/CONFIGURATION.md`,
  `docs/TROUBLESHOOTING.md`.

## [2.6.3] — Milestone 26.3 — File/history hygiene

### Changed
- The History → Files tab hides internal/operational artifacts by default
  (`logs/`, `audit/`, `data/` staging & exports, `*.log`/`.gitkeep`/`*.pyc`)
  via a new `exclude_internal` flag on `POST /files/search`. An explicit
  "Show internal/ops files" toggle reveals them. The allowlist and FileManager
  security are unchanged (the endpoint default stays unfiltered).

## [2.6.2] — Milestone 26.2 — Provider/config truthfulness & version consistency

### Fixed
- The provider listing (Providers tab, `--list-providers`) now reports each
  provider's **effective** transport — e.g. Grok shows `api` when the API
  transport is configured, not the static `cli`. Availability stays
  config-based (no network probe).
- Version reporting is consistent: the app/release version is a single FastAPI
  source (logs, UI, `/health`), clearly distinct from the relabeled
  "Profile schema version".
- `config/app.yaml` no longer carries a stale version.

## [2.6.1] — Milestone 26.1 — Settings UI & status fixes

### Fixed
- Static assets are cache-busted (versioned `?v=` URLs + a
  `Cache-Control: no-cache, must-revalidate` header) so editable settings and
  the in-flight status actually update after an upgrade (the symptoms were
  stale browser-cached JS/CSS).
- The startup provider chip reflects the configured preferred provider, else
  stays blank, instead of showing an arbitrary one.
- A successful settings save re-renders the Profile tab from `/profile`.

## [2.6.0] — Milestone 26 — Editable settings in the UI

### Added
- `PATCH /profile` makes three behaviour-affecting profile fields editable from
  the Settings panel (`system_prompt`, `routing.mode`, `routing.preferred_provider`).
  Validated before any write; persisted to `profile.yaml`; applied to the live
  runtime with no restart. Providers/integrations/credentials/memory stay
  read-only.

## [2.5.0] — Milestone 25 — CLI status/progress feedback

### Added
- A generic TTY-only in-flight spinner and a concise one-line summary on stderr
  after completion (stdout stays the answer only); `--diagnostics` adds an
  expanded per-provider breakdown, `-q`/`--quiet` suppresses all status. Built
  from the M22 trace; no router changes.

## [2.4.5] — Milestone 24.5 — Enhanced web UI diagnostics & provider timeline

### Added
- An indeterminate in-flight progress bar, a compact proportional provider
  timeline (outcome-coloured, answering provider highlighted), and a collapsed
  Details view — all reconstructed at completion from `ChatResponse.diagnostics`
  (no backend changes, no streaming).

## [2.4.0] — Milestone 24 — Web UI status/progress (text-only)

### Added
- An in-flight "Working…" indicator and a concise muted summary under each
  answer, built from the M22 trace forwarded on `ChatResponse.diagnostics`.

## [2.3.0] — Milestone 23 — Hermes CLI provider

### Added
- An opt-in, CLI-backed Hermes provider (`hermes chat -q`) with answer-box
  parsing and a raw fallback. Disabled by default and in no ranking.

## [2.2.0] — Milestone 22 — Provider latency diagnostics

### Added
- Measure-only latency instrumentation in `ProviderRouter.route()`: a
  content-free `RequestTrace` per request (provider/transport/outcome/timing),
  stored in a bounded in-memory ring buffer and attached to response metadata.
  No routing changes.

## [2.1.0] — Milestone 21 — Grok CLI and API transports

### Added
- One logical `grok` provider with an explicit `cli` (default) or `api`
  transport, resolved from `GROK_TRANSPORT` env → `providers.yaml` → default
  `cli`. The API path uses the OpenAI-compatible endpoint (`XAI_API_KEY`).

## [2.0.0] — Milestones 0–20 — Foundation

The 2.0.0 baseline covers the full foundation built across milestones 0–20:

- Architecture, config loader, and multi-profile system (M0–M1).
- `ProviderRouter` with routing modes and provider adapters (M2).
- Dark-theme chat UI (FastAPI + Jinja2) (M3).
- `MemoryManager` — YAML flat-file memory with a pending-review queue (M4).
- Push-to-talk voice (Web Speech API; STT/TTS stubs) (M5).
- `FileManager` — allowlist, hot-reload, audit log, path-traversal guard (M6).
- CalDAV (M7), CardDAV safe-merge workflow (M8), Nextcloud read-only (M9).
- Export hardening, Docker polish, architecture/runbook docs (M10).
- Test suite + `TESTING.md` (M11), Taskfile (M11.5).
- VCF/ICS import+export and conflict queues (M12), backup/restore (M13).
- DAV sync status (M14), operational hardening (M15).
- Ollama local-LLM adapter, opt-in (M15.5).
- One-shot CLI `python -m cli` (M16) and the `athena` console command (M17).
- Saved searches & saved actions (M18).
- Read-only Settings panel (M19) and History & Attachments panel (M20).

[2.6.4]: #264--milestone-264--docs-cli-packaging--install-flow
[2.6.3]: #263--milestone-263--filehistory-hygiene
[2.6.2]: #262--milestone-262--providerconfig-truthfulness--version-consistency
[2.6.1]: #261--milestone-261--settings-ui--status-fixes
[2.6.0]: #260--milestone-26--editable-settings-in-the-ui
[2.5.0]: #250--milestone-25--cli-statusprogress-feedback
[2.4.5]: #245--milestone-245--enhanced-web-ui-diagnostics--provider-timeline
[2.4.0]: #240--milestone-24--web-ui-statusprogress-text-only
[2.3.0]: #230--milestone-23--hermes-cli-provider
[2.2.0]: #220--milestone-22--provider-latency-diagnostics
[2.1.0]: #210--milestone-21--grok-cli-and-api-transports
[2.0.0]: #200--milestones-020--foundation
