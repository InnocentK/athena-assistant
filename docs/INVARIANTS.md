# Athena — Invariants & "Do Not Break These"

The load-bearing mechanisms and safety guarantees in Athena, grouped by subsystem.
**Read the relevant section before editing that area.** Each item explains the
rule, why it exists, and what breaks if it's reverted. Regression tests enforce
most of these — the test file is named where one exists.

This file is the durable contract; per-release history lives in
[`../CHANGELOG.md`](../CHANGELOG.md).

---

## Core / app-wide

- **All paths resolve from `APP_ROOT`.** No hardcoded absolute paths anywhere —
  always use the helpers in `core/config.py`. (Enables the tmp-project test
  fixtures and relocatable deployments.)
- **App version has exactly ONE bump site: `core/version.py` (M26.17).**
  `main.py` imports `__version__` (→ `/health` + startup log), `pyproject.toml`
  reads it via `[tool.setuptools.dynamic]`, and
  `tests/test_ops_hardening.py::test_health_version_matches_single_source`
  asserts `/health` matches it. Never re-introduce a version literal in any of
  those spots — on a code release, bump `core/version.py` and nothing else.
  The profile's own `version` is its **schema/format** version (shown as
  "Profile schema version"), independent of the app/release version.
- **`TemplateResponse` signature (M3).** Always
  `_templates.TemplateResponse(request, "index.html", {...})` — never the old
  dict-as-name form (a breaking Starlette API change).
- **Global exception handler scope (M15).** `@app.exception_handler(Exception)`
  catches only unexpected bare exceptions. Do NOT add handlers for
  `HTTPException` or `RequestValidationError` — FastAPI's defaults must stay
  intact.

## Frontend tests (M26.22)

- **The jsdom suite runs the shipped `static/js/*.js` unmodified.** Tests load
  the real files via `tests/js/loadChat.js` (a test-only eval + shim footer);
  **do not restructure `chat.js`/`voice.js` for testability** and do not add a
  bundler — the production files stay plain browser scripts. If a new UI
  behaviour needs coverage, add a jsdom test that drives it, don't refactor the
  source to suit the test.
- **Node stays dev/CI-only.** `package.json` deps are `devDependencies`;
  `node_modules/` is gitignored. The web app is Python/Docker — Node must never
  become a runtime dependency. The Python suite (`task test:run`) and the JS
  suite (`task test:js` / `npm run test`) are independent; a Python-only
  contributor needs neither Node nor the JS suite to work on the backend.
- The Python-side source-structure guards (`test_chat_status_ui.py`,
  `test_ui_correctness.py`) are kept alongside the runtime tests — they catch
  "someone rewrote the file" cheaply even when no matching JS test exists.

## pre-commit hooks (M26.26)

- **The ruff/mypy versions in `.pre-commit-config.yaml` MUST match the pins in
  `requirements.txt`.** A mismatch means pre-commit and CI disagree about what's
  clean. Bump them together (ruff is `v0.15.11` in both; mypy runs as a
  `local`/system hook so it just uses the installed pin).
- pre-commit is **lint + types + hygiene only** — the pytest/vitest suites stay
  in CI / `task ci` (too slow to run on every commit). Don't add them to the
  pre-commit config.
- Hooks are a default, not a lock: `git commit --no-verify` bypasses them for
  emergencies. Activation (`pre-commit install`) is a per-clone manual step (it
  fetches hook repos over the network).

## Coverage floor (M26.24)

- **`task coverage` must stay ≥ the `fail_under` floor** (70%, in
  `pyproject.toml` `[tool.coverage.report]`; source-only real number ~74%). CI
  enforces it via `pytest --cov`. The floor is a **ratchet that only goes up** —
  raise it deliberately as coverage improves; never lower it to make a change
  pass (fix the tests instead). Coverage config omits `tests/`/`__init__.py` so
  the number reflects application code, not the test files.
- Coverage measures *execution, not correctness* — it complements the suite's
  assertions, never replaces them (the M26.18 bug ran at 100% line-execution).

## Dependency audit (M26.25)

- **Pinned dependencies must stay CVE-clean.** `task audit` (`pip-audit -r
  requirements.txt --no-deps`) must report no known vulnerabilities. When it
  flags a package, assess and bump the pin to the fix version, re-run the full
  gate (`task ci`), and re-audit → 0. A dependency bump is a code release (bump
  `core/version.py`). The CI `pip-audit` step is intentionally **non-blocking**
  so a newly-disclosed upstream CVE doesn't fail unrelated PRs — do not make it
  blocking without a triage plan.
- `pip-audit` is pinned for reproducible runs, but its advisory DB updates over
  time (intended). `--no-deps` scans exactly the pinned set (no hashed
  lockfile); a future tightening is `pip-compile --generate-hashes`.

## Type gate (M26.21)

- **`task typecheck` (mypy) must pass.** Config is `[tool.mypy]` in
  `pyproject.toml` (single source): lenient — `ignore_missing_imports`,
  `import-untyped` disabled (env-robust stub handling), **tests excluded**
  (heavy MagicMock/monkeypatch dynamism is high-noise), `warn_unused_ignores`
  off for now. In the CI gate and the SessionStart hook (report-only).
- Prefer **real narrowing** (assert / precise types / annotations) over
  `# type: ignore`; if an ignore is unavoidable, make it specific
  (`# type: ignore[code]`) and comment why.
- Invariant tie-in: `providers/router.py`'s diagnostics `trace` is `None` when
  diagnostics are disabled, and a per-attempt `rec` is created **iff** `trace`
  exists — the `assert trace is not None` before each `trace.add(rec)` encodes
  that. `caldav`/`carddav`/`nextcloud` client handles are `Any` (the libraries
  are untyped) — keep those annotations so the None-only inference doesn't
  return.
- Tightening (`strict`, `disallow_untyped_defs`, typing the test suite,
  `warn_unused_ignores`) is deferred to a future milestone.

## CI gate (M26.20)

- **The CI gate = `ruff check` + editable install + `pytest`** (`task ci`
  locally; `.github/workflows/ci.yml` on GitHub, Python 3.10 + 3.11). It must
  stay **secret-free** — the suite is fully mocked (see the M26.17 hermeticity
  fixture), so CI never needs provider keys or network. Do not add a CI step
  that requires credentials; if a test needs a real service, it doesn't belong
  in the suite.
- The editable-install step (`pip install -e .`) is also the packaging-invariant
  guard — keep it so a broken `pyproject.toml` `packages` list fails CI.
- CI is **inert until the project has a git remote** (it isn't under git yet);
  `task ci` is the always-available equivalent. See `docs/CI.md`.

## Lint gate (M26.19)

- **`task lint` (ruff) must pass.** Config is `[tool.ruff]` in `pyproject.toml`
  — the single source; `select = ["E4","E7","E9","F","B"]` (correctness-strict,
  style-lenient). Do not scatter `# noqa`; add one only for a genuine
  false-positive and say why in the comment. `task lint:fix` auto-fixes the safe
  subset. The SessionStart hook runs it (report-only).
- **Do not let `ruff --fix` delete `main.py`'s router-facing re-exports.**
  Symbols imported into `main.py` solely so routers can reach them via
  `main.<name>` (currently `write_ops_event`) look unused *to ruff* because the
  callers live in `app/routers/*`. They carry
  `# noqa: F401  (router-facing re-export)` — keep it. Running `ruff --fix`
  without it silently removes the import and breaks every handler that logs an
  audit event (caught only at request time). This is the same cross-module
  coupling documented under "HTTP layer / router split".
- **Exception chaining (`B904`).** Re-raises inside `except` use
  `raise … from exc` when the handler binds the cause, or `from None` for
  expected control-flow conversions (timeouts, validation) where the original is
  noise. Behaviour-neutral (only the traceback's `__cause__` changes) but keep
  it — it's what makes server logs debuggable.
- `I` (isort import ordering) and `ruff format` are intentionally **not** enabled
  yet (each is a whole-tree diff); they're candidate future opt-ins.

## HTTP layer / router split (M26.18)

- **Routes live in `app/routers/<domain>.py`; `main.py` is the assembly + state
  layer.** `main.py` keeps module state (`_router`, `_memory`, `_profile_data`,
  `_restore_diff_tokens`, the timeout constants, `_MAX_SYSTEM_PROMPT`, …), the
  `_require_*` accessors, the shared helpers (`_safe_export_path`,
  `_write_audit`, `_list/_load/_save_conflict_file`, `_known_provider_names`,
  `_validate_routing_mode`, `_persist_profile_changes`), the lifespan, exception
  handlers, static/template mounts, and the `GET /` index route. Everything else
  is a route handler in a domain router.
- **Router handlers resolve app state via `main.<name>` after a module-level
  `import main` — never `from main import <name>`.** The test suite pops `main`
  from `sys.modules` and re-imports it fresh per test; a captured reference (or
  a `from main import` binding) would point at a stale module and read `None`
  state. `main.py` `importlib.reload`s each router as it assembles the app so the
  router's module-level `main` always rebinds to the live module. Do not "tidy"
  `main.X` into a direct import, and keep the reload loop.
- **Pydantic models live in `app/models.py`** (pure data, no app dependency);
  main and routers import from there.
- **The route set is the contract.** After any change here, the OpenAPI path set
  (`app.openapi()["paths"]`) must be unchanged unless you intend to add/remove a
  route. The full suite (which drives every domain through the `client` fixture)
  is the behavioural guard; 436 tests pass unchanged across the split.

## Concurrency (M26.5)

- **Every blocking call in an async handler is wrapped** in
  `asyncio.wait_for(asyncio.to_thread(...), timeout=N)`. This covers `/chat`
  (`route` + `auto_extract`), `/saved/actions/{id}/run`, `/providers`, the
  `list_providers()` probe inside `PATCH /profile`, and **every**
  CalDAV/CardDAV/Nextcloud endpoint that hits the network. A bare sync call
  re-freezes the event loop — this was the code review's top finding.
- **Any NEW async endpoint** that shells out, hits the network, or does blocking
  file I/O must follow the same pattern. As of M26.14 the heavy **local** disk
  paths are wrapped too (`asyncio.to_thread`, deliberately without a
  `wait_for` deadline — local disk has no network-style hang mode and a
  timeout can't cancel the thread anyway): `/files/search`, `/files/read`,
  backup create/list/inspect/diff. Only trivially small local YAML/JSON I/O
  (e.g. staged-merge list/get/discard) remains unwrapped by choice.
- **`FileManager.read_file` is capped and decode-safe (M26.14).** Reads return
  at most `_MAX_READ_BYTES` (2MB — deliberately equal to the Nextcloud
  streaming cap) with `truncated: true` beyond it, and decode with
  `errors="replace"` so a binary/non-UTF-8 allowlisted file yields replacement
  characters, never an unhandled `UnicodeDecodeError` 500. Tests:
  `tests/test_file_manager.py` (cap/binary), `tests/test_files_api.py`
  (binary → 200), `tests/test_concurrency.py` (off-loop search).
- Timeout constants live at the top of `main.py`: `_ROUTE_TIMEOUT=130`,
  `_AUTO_EXTRACT_TIMEOUT=10`, `_PROVIDERS_TIMEOUT=15`, `_DAV_READ_TIMEOUT=30`,
  `_DAV_WRITE_TIMEOUT=30`.
- Contract-preserving exceptions to the 504-on-timeout rule: `/nextcloud/ping`
  returns `{reachable:false, error}` and `/caldav/export` returns an empty
  calendar.
- **Caveat:** a route/DAV timeout cannot cancel the worker thread — the orphaned
  attempt finishes in the background and is discarded. Handlers can now genuinely
  run concurrently, so `_profile_data` reads and the `_restore_diff_tokens` dict
  are theoretically racy — safe under single-worker uvicorn (noted in-code); add
  a lock only if a multi-worker deployment is introduced.
- **The shared singletons ARE locked (M26.16) — keep them that way.**
  "Single-worker uvicorn" does not mean single-*threaded*: DAV clients and
  `route()` run in `to_thread` workers while routes read on the loop thread.
  `DavStatusStore` and `DiagnosticsStore` guard all access with a
  `threading.Lock` (an unlocked deepcopy/deque-iteration during a concurrent
  update raises), and `MemoryManager` serialises its YAML read-modify-write
  cycles with an `RLock` via the `_locked` decorator (auto_extract in a worker
  vs approve/discard on the loop was a lost-update hazard). New mutating
  methods on any of these must take the same lock. Tests:
  `tests/test_thread_safety.py`.
- **Every outbound DAV HTTP call sets an explicit socket timeout (M26.12).**
  Because `wait_for` can't cancel the thread (previous bullet), the transport
  itself must be bounded or a hung server pins a `to_thread` executor slot
  forever (~32 such calls freeze all offloaded work). CardDAV: all requests flow
  through `CardDAVClient._request`, which applies `_HTTP_TIMEOUT` — do **not**
  add a raw `requests.*` call to that module (a source-level test enforces the
  single chokepoint). CalDAV: `caldav.DAVClient(..., timeout=_CONNECT_TIMEOUT)`.
  Nextcloud already passes `timeout=15` per call. Tests:
  `tests/test_dav_transport.py`.
- `ProviderRouter.route()` is **synchronous** — fine for the one-shot CLI and the
  `to_thread` wrapping. Never call it bare in a new async context.
- Tests: `tests/test_concurrency.py`.

## Network egress (M26.13) — security

- **Caller-supplied DAV URLs are same-origin-locked.** `calendar_url`,
  `address_book_url`, and absolute `href`s must share scheme+host+port with the
  configured `CALDAV_URL`/`CARDDAV_URL`; anything else raises
  `core.urlguard.DAVSecurityError` → HTTP **400** (app-level handler in
  `main.py`). Without this, the DAV Basic-Auth credentials would be attached to
  whatever host a crafted URL names (SSRF + credential exfiltration — the July
  2026 review's top security finding).
- Enforcement points — keep all of them: `CardDAVClient._request` (the single
  chokepoint; every CardDAV request flows through it — see the M26.12 rule),
  `CalDAVClient._check_url` as the **first** statement of
  `list_events`/`list_tasks`/`create_task` (before the broad
  `except → CalDAVConnectionError` wrappers, so the error type survives),
  fail-fast checks at the top of `import_ics`/`import_vcf` (their bodies
  warn-and-continue and `import_ics` builds `caldav.Calendar` directly), and
  route-level checks in `/caldav/export` (its `_gather` swallows exceptions by
  design) and the CalDAV conflict-overwrite push.
- Relative hrefs are allowed (they're joined onto the configured base);
  `urlsplit().hostname` ignores userinfo, so `https://trusted@evil/` compares
  `evil`. Default ports are normalised (`https://h` == `https://h:443`).
- Known limit: the check runs at request-build time; redirects issued by the
  *configured* server are followed. A malicious configured server is outside
  the threat model.
- Nextcloud needs no guard — it only ever appends paths to its fixed base.
- Tests: `tests/test_dav_ssrf.py` (unit matrix + client + import + API-level
  400s).

## Filesystem write-safety (M26.7) — security

- **Memory category allowlist.** `MemoryManager._category_path` allowlists
  category stems (`_ALLOWED_CATEGORY_FILES` = `CATEGORIES` + `pending_review`);
  every memory file path funnels through it. Never bypass it or build a category
  path directly — this is what stops `category="../evil"` writing outside the
  memory dir. `POST /memory` also returns a clean 400 for unknown categories.
- **Backup restore Zip-Slip containment.** `BackupManager._safe_target` contains
  every restore/diff zip member to the app root. Never
  `open(self._root / member)` on a raw join — always resolve through
  `_safe_target` and skip on `None` (both relative `../…` and absolute members
  are rejected).
- **`diff_token` is bound to its backup.** `_restore_diff_tokens` values are
  `(zip_filename, expiry)`; the confirmed restore must check the token was issued
  for that exact filename (else 409). Token TTL 5 min, single-use.
- **Export-filename guard.** `main.py::_safe_export_path` gates every
  `data/exports` filename (restore body + diff/download/delete path params)
  against `../`/absolute (400).
- Tests: `tests/test_write_safety.py`, `tests/test_ops_hardening.py`.

## Providers & routing (M26.8)

- **API adapters must be bounded.** Construct the client with `timeout=…,
  max_retries=0` and catch `APITimeoutError`/`APIConnectionError` (chatgpt + grok
  do this; `OPENAI_TIMEOUT`/`GROK_TIMEOUT` default 120s). A new API adapter that
  skips this can hang a worker for minutes.
- **CLI adapters** must pass `stdin=subprocess.DEVNULL` +
  `encoding="utf-8", errors="replace"` (claude/gemini/grok/hermes) — no hang on
  an interactive prompt, no decode failure on a stray byte.
- **Routing-override validation.** `PATCH /profile` and `POST/PATCH
  /saved/actions` share `_validate_routing_mode` + `_known_provider_names`; the
  CLI validates `--provider`. `ProviderRouter._get_ordered_names` falls back to
  **balanced** (not quality-first) on an unknown mode and logs it.
- **Transport truthfulness.** `_transport_for` reports a dynamic adapter's
  `transport()` on non-answer records; keep it in sync with `list_providers()`.
  A new dynamic-transport adapter should expose a `transport()` method.
  Availability is config-based (no network probe).
- **Claude-CLI JSON mode must keep degrading (M28.2).** The adapter
  feature-detects `--output-format` via a cached `claude --help` probe; every
  envelope deviation (non-JSON stdout, missing `result`, probe failure) falls
  back to plain-text success, and `is_error: true` maps to a provider failure.
  Do not make JSON parsing strict — an envelope change in a future CLI must
  degrade the metric, never the answer. Model attribution (M29.5) is the same
  contract: top-level `model`, else `modelUsage`'s first key, else `None` —
  never a guess. The test fixture pins the REAL 2.1.206 envelope; when a new
  CLI version changes the shape, update the fixture from a live capture.
  Tests: `tests/test_claude_usage.py`.
- **Token usage is counts-only (M27.1).** Adapters may put a `usage` dict of
  token *counts* into `response.metadata["usage"]` (API adapters via
  `extract_openai_usage`); the router copies it to `ProviderCallRecord.usage`.
  This is metadata, not content — **never** put prompt/response text in `usage`,
  or the "diagnostics store no content" rule breaks. Missing usage is `None`
  ("unavailable"), surfaced honestly by the UI (`buildUsageText`) and CLI
  (`build_cli_usage`) — never a fabricated number.
- Tests: `tests/test_provider_robustness.py`, `tests/test_provider_*`,
  `tests/test_diagnostics.py`, `tests/test_token_usage.py`.

## Calendar / DAV (M26.9)

- **Server XML parses via defusedxml (M26.15).** Both the Nextcloud and
  CardDAV clients parse multistatus bodies with
  `defusedxml.ElementTree.fromstring` (entity definitions / external refs
  rejected; Nextcloud wraps parse failures in `NextcloudConnectionError` via
  `_parse_multistatus`). Do not revert to bare `xml.etree` `fromstring` for
  server-controlled bytes. Stdlib `ET` remains only for Element construction
  and namespace registration.
- **DASL search interpolations stay escaped (M26.15).** `search_files` XML-
  escapes `query` and the dav root before f-string interpolation — unescaped
  `&`/`<`/`>` made the body malformed and silently degraded results to the
  local-filter fallback. The Nextcloud client also uses the shared
  `core.logger` (records must not skip Athena's handler).
- Tests: `tests/test_nextcloud_correctness.py`.

- **ICS date-times** go through `dav_io/ics_io.py::_format_ics_datetime`
  (offset→UTC+`Z`, naive→floating no-`Z`). Never re-introduce the string-munge
  that appended `Z` unconditionally (it shifted offset times and mis-stamped
  naive/negative ones).
- **ICS text values** (SUMMARY/DESCRIPTION/LOCATION) go through
  `escape_ics_text` — in `_reconstruct_component` AND CalDAV `create_task`. A new
  ICS-emitting path must escape too (RFC 5545).
- `DavStatusStore.get()`/`get_all()` return **deep copies** — don't revert to
  `dict(...)` (a caller mutating a snapshot would corrupt the singleton).
- Nextcloud `read_file` **streams with a running byte cap** — don't switch back
  to `resp.content` (unbounded buffering).
- Backup manifest `app_version` comes from `BackupManager(..., app_version=app.version)`.
- `parse_vcf_string` emits `emails`/`phones` lists (singular = first, for
  compat); `export_vcf` reconstruct prefers the lists.
- **CardDAV merge is human-gated (M8).** Never auto-commit a staged merge.
  `commit_merge` is the ONLY server write path and requires an explicit
  `staged_merge_id`. Enforced by `tests/test_carddav_safety.py`.
- **CalDAV/CardDAV disabled by default** — `config/caldav.yaml` /
  `config/carddav.yaml` have `enabled: false`; all client methods check this
  before connecting.
- **`DavStatusStore` is a singleton** — call `DavStatusStore().reset()` in tests
  that touch it to avoid state leakage.
- Tests: `tests/test_dav_correctness.py`, `tests/test_dav_io.py`,
  `tests/test_dav_status.py`, `tests/test_carddav_safety.py`.

## Web UI (`static/js/chat.js`, M26.10)

- Record an assistant turn **only in the success branch** (never before the
  `data.success` check) — otherwise a failure string is replayed as context.
- Keep the network `try/catch` scoped to fetch/parse with a `try/finally` reset;
  don't wrap rendering/TTS in it (a render error must not read as "Network
  error").
- Access `voice` only behind `typeof voice !== "undefined"` (a missing
  `voice.js` must not abort init).
- Always inject the canonical mode/provider as a `<select>` option so a save
  can't silently clear it when `/providers` is unavailable.
- Keep the `_panelLoadToken` guard in every async panel loader (and bump it in
  the sync `loadHistoryConversation`); a new async loader must capture + re-check
  the token after its awaits.
- **Static assets are cache-busted (M26.1).** `index.html` references
  `chat.css`/`voice.js`/`chat.js` with `?v={{ asset_version }}` (=`app.version`)
  and `/static` is served by `_RevalidateStaticFiles`
  (`Cache-Control: no-cache, must-revalidate`). Frontend changes rely on this to
  reach upgraded browsers — do not drop the versioned URLs or the header.
- **PWA service worker caches the shell only, version-scoped (M26.28).** The
  `/sw.js` route bakes `app.version` into the cache name so a release drops the
  old cache on `activate` — the SW analogue of the `?v=` rule above; keep them in
  sync. The `fetch` handler is an **allowlist**: it caches only `/static/*` +
  root navigation and **never** dynamic/API responses (`/chat`, memory, settings,
  DAV, backup) — Athena is server-dependent, so caching a turn would be a
  correctness bug. Registration (`static/js/pwa.js`) stays guarded by
  `'serviceWorker' in navigator` so plain-HTTP origins degrade to an ordinary
  page. Do not broaden the cache allowlist or drop the registration guard.
- Tests: `tests/test_ui_correctness.py` (source-structure guards; no JS runtime
  in the suite by design); `tests/test_pwa.py` + `tests/js/pwa.test.js` (M26.28).

## CLI (M16/M17/M25/M26.6)

- **CLI logger only retargets its OWN handler (M26.6).** `core/logger.py` tags
  its stdout console handler `_athena_console = True`; `_configure_cli_logging`
  retargets **only** tagged handlers. Never loop over all handlers of the shared
  non-propagating `"athena"` logger — that clobbers pytest's capture handler and
  broke the whole CLI suite. Enforced by
  `test_configure_cli_logging_only_touches_tagged_handler`.
- **CLI stdout is answer-only**; all logs/status/diagnostics go to stderr. The
  M27.0 live status line (`Spinner.set_text` driven by the router's `on_attempt`
  callback) is stderr-only and TTY-gated — do not route any of it to stdout.
  The M29.2 REPL keeps the same contract (the `you>` prompt itself is stderr),
  and its **entry is TTY-gated**: bare `athena` with a non-TTY stdin must stay
  a usage error (exit 2) so scripts can never hang in an input loop. REPL
  history replays a turn **only on success** (M26.10, CLI edition).
- **`route(on_attempt=…)` is measure-only (M27.0).** The progress callback fires
  before each available provider is called and is wrapped so any exception is
  swallowed — it must never influence routing, the attempt order, or the result
  (same contract as the M22 diagnostics trace). Enforced by
  `test_router_bad_on_attempt_callback_never_breaks_routing`.
- **Packaging: declare every runtime package (M26.4).** `pyproject.toml`'s
  `[tool.setuptools] packages` is an explicit list (flat, non-`src` layout). When
  you add a new top-level package, ADD it here too, or `pip install -e .` fails
  with `No module named '<pkg>'` from outside the project. Verify the editable
  install from a directory OUTSIDE the project tree (running inside it masks the
  bug via cwd on `sys.path`).

## Settings / profile (M26)

- **Active-profile resolution order is override > switch-file > env > default
  (M28.5).** `ATHENA_PROFILE_OVERRIDE` (set by the CLI `--profile` flag) beats
  `config/active_profile.yaml`, which beats `ACTIVE_PROFILE`. The switch file
  is written ONLY by `POST /profiles/activate`; its read is defensive (a broken
  file must fall through to env, never brick boot). Do not reorder these.
- **`POST /profiles/activate` validates `^[A-Za-z0-9_-]+$`** before touching
  the filesystem (traversal guard), never edits `.env`, and re-points
  `_profile_data` (clear+update in place) + `main._memory` + `main._saved`.
  In-flight requests finishing on the old managers is the intended semantics.
- **Env-mutating CLI flags need the conftest guard.** The CLI runs in-process
  in tests; `--profile`'s env write is cleared by an autouse fixture. A future
  flag that sets env must get the same treatment or it leaks across tests.
- Tests: `tests/test_profile_switch.py`.

- **`PATCH /profile` is the only UI write to `profile.yaml`.** It validates
  before writing, touches only `system_prompt` / `routing.mode` /
  `routing.preferred_provider`, persists with `save_yaml(..., sort_keys=False)`
  (key order kept, comments lost), and updates `_profile_data` in place so
  `/chat` applies changes without a restart (the CLI reloads the file next run).
  A validation failure must write nothing and mutate nothing. Do not widen the
  editable set or switch away from in-place mutation without revisiting the
  persistence/runtime/CLI interactions.

## File uploads (M29.3)

- **The upload endpoint fully controls the target path**: basename-only
  sanitization to `[A-Za-z0-9._-]` (no dotfiles, never empty) into
  `data/uploads/` only, unique-suffix on collision — never trust the client
  filename, never overwrite.
- **The 10 MB cap is enforced during the streamed write** (partial file
  removed on breach) — do not switch to read-then-check.
- **Reads stay allowlist-governed.** Uploads add no read path; do not
  auto-inject file contents into prompts.

## Conversation history (M29.1)

- **Ids are validated before any path is built.** `ConversationStore._path`
  rejects anything outside `^[A-Za-z0-9_-]+$` — every public method funnels
  through it. Never construct a history path from raw input elsewhere.
- **History must never fail a turn.** `record_turn` (like `extract_memory`)
  swallows everything; `/chat` degrades to an unpersisted conversation when
  the store errors. Keep it best-effort.
- **Chat content stays private.** `profiles/*/history/` is gitignored and
  excluded from portable bundles (by the M28 allowlist — do not add it);
  full backups include it deliberately.
- **The store is lock-guarded and per-profile** — `POST /profiles/activate`
  re-points `main._history` (test-pinned in `test_history.py`).
- **One Markdown renderer (M29.6).** `ConversationStore.render_markdown` is
  the only conversation-to-Markdown path — the HTTP export endpoint and
  `athena history export` both delegate to it (test-pinned equality). Don't
  reintroduce a second renderer.
- **CLI history output rules (M29.6).** `athena history …` prints its answer
  (list/transcript/Markdown) to stdout; errors/notices to stderr. Inside the
  REPL, `/list` is status → stderr. `/resume` replays success-only (M26.10).

## Memory (M4)

- `PENDING_LIST_KEY = "pending"` in `memory/manager.py` — not `"pending_review"`.
- **`auto_extract` writes only to the pending queue** — it never auto-approves.

## Portable Profiles (M28)

- **Export is allowlist-built.** `backup/portable.py::_sanitize_profile`
  constructs the bundle from an explicit KEEP set — never filter fields off a
  full copy. A new profile.yaml field must NOT travel until consciously added
  to the allowlist (fail closed).
- **A leak-guard hit is a hard failure.** Live `.env` values or
  credential-shaped strings anywhere in the bundle, and URLs/absolute host
  paths in profile fields, raise `PortableExportError` → HTTP 409 and **no zip
  is written**. Never downgrade these to warnings. (URLs in *memory* entries
  are the one warning-only case — user content, surfaced for review.)
- **No machine identifiers.** The portable manifest has no `hostname` (unlike
  the backup manifest); pending-review, archive, `config/`, and `.env` never
  travel.
- **Snapshot semantics.** Every surface (manifest, API response, docs) states
  that the bundle forks on import — do not add sync/merge behaviour casually.
- **Import re-enforces the allowlist and never clobbers (M28.1).** Incoming
  bundles go through the same `_sanitize_profile` + leak scan (409 on planted
  secrets; host fields stripped); an existing profile dir is never overwritten
  (`new_name` required instead); `.env`/`config/`/`data/` are never touched;
  only **fixed member names** are read from the zip — never derive a write path
  from a zip member name.
- Tests: `tests/test_portable.py` (the planted-secret hard-fail tests — export
  AND import — are the contract).

## Audit & packaging

- **Audit logs** — four JSON-lines logs under `audit/`: `file_audit`,
  `import_audit`, `backup_audit`, and `ops_audit` (M15).
- **`audit/` source is tracked.** `.gitignore`/`.dockerignore` and the packaging
  step ignore only `audit/*.log` (runtime logs), never the `.py` source. A
  wholesale `audit/` ignore strips `ops_audit.py` and breaks app boot — do not
  re-introduce one.
- **Restore staging** — restores always stage originals to
  `data/restore_staging/<ISO_timestamp>/` before overwriting. Do not bypass this.

## Taskfile

- `task` v3.51.1. Multiline shell blocks require the `cmd: |` form.
