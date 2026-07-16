# Athena Assistant — Testing Guide

## Route → test map (where to add an endpoint test)

Routes live in `app/routers/<domain>.py` (M26.18); their tests fan out by
concern. When you touch a route, extend the matching file (M26.17):

| Route prefix | Test file(s) |
|---|---|
| `/health`, `/`, `/profile`, `/providers`, `/chat` | `test_api_core.py` (+ `test_settings_edit.py` for `PATCH /profile`, `test_chat_status_ui.py` for chat diagnostics) |
| `/memory/*` | `test_memory_api.py` (manager: `test_memory_manager.py`) |
| `/files/*` | `test_files_api.py`, `test_files_hygiene.py` (manager: `test_file_manager.py`) |
| `/saved/*` | `test_saved_api.py` (manager: `test_saved_items.py`) |
| `/caldav/*`, `/carddav/*` | `test_dav_io.py` (import/export/conflicts), `test_carddav_safety.py` (merge gating), `test_dav_ssrf.py` (URL guard), `test_dav_transport.py` (timeouts) |
| `/nextcloud/*` | `test_nextcloud_correctness.py`, `test_dav_correctness.py` |
| `/status/dav*` | `test_dav_status.py` |
| `/backup/*` | `test_backup.py`, `test_ops_hardening.py` (diff_token), `test_write_safety.py` (Zip-Slip / export-path guard), `test_thread_safety.py` (inspect guard) |
| `/diagnostics*` | `test_diagnostics.py`, `test_diagnostics_ui.py` |
| cross-cutting: event-loop / offloading | `test_concurrency.py` |
| cross-cutting: version, sanitized 500, audit | `test_ops_hardening.py` |
| CLI (`athena`, `python -m cli`) | `test_cli.py`, `test_cli_status.py` |

Suite hermeticity: an autouse conftest fixture blanks `shutil.which` for the
provider binary names so no real provider CLI can ever run from a test —
even on machines where `claude`/`gemini`/… are installed. Never remove it.

## What the test suite covers

- **Core API endpoints** (`test_api_core.py`): health, profile, providers, chat (provider failure path), integration disabled 503 responses
- **Config and profile loading** (`test_config.py`): APP_ROOT type, settings defaults, env var overrides
- **FileManager** (`test_file_manager.py`): allowlist CRUD, path traversal rejection, read/write permissions, audit logging, config write protection
- **MemoryManager** (`test_memory_manager.py`): CRUD, pending queue, approve/discard, auto-extract regex patterns, safety invariant (auto-extract → pending only, never direct save)
- **ProviderRouter** (`test_provider_router.py`): routing mode ordering, preferred provider, fallback on failure, skip disabled/unavailable adapters; Ollama adapter registered, skipped when disabled, and chosen when enabled + preferred (Milestone 15.5)
- **Ollama provider** (`test_provider_ollama.py`): name/cost tier; health-check availability (model gating, healthy, unreachable, missing `openai`, custom endpoint); completion happy path; system-prompt + message-order mapping; custom timeout; failure modes (missing model, connection error, timeout, generic exception) — all fully mocked, no live Ollama server
- **Grok provider** (`test_provider_grok.py`): transport resolution (`GROK_TRANSPORT` env > `providers.yaml` > default cli); **default-CLI guarantee** (the API client is never constructed by default); CLI success/timeout/non-zero; API success (base_url/model/system-prompt mapping), missing-key, custom model+url, error mapping; `is_available` per transport — all fully mocked (Milestone 21)
- **Provider/version truthfulness** (`test_provider_truthfulness.py`): `/providers` reports Grok's **effective** transport (`api` under `GROK_TRANSPORT=api`, else `cli`) while a static-transport provider is unchanged; `/health` equals the single FastAPI app version (Milestone 26.2)
- **Provider diagnostics** (`test_diagnostics.py`): store/formatter/`classify_error_kind` units; router integration — trace attached to `response.metadata["diagnostics"]` + stored; transport attribution (`metadata.transport` vs config `type`); unavailable/exception/failure outcomes + error_kind; deterministic timing via a patched clock; **routing unchanged** and **no message content** in the trace; disabled-mode produces no trace (Milestone 22)
- **Hermes provider** (`test_provider_hermes.py`): `_extract_answer` on real Hermes samples (box extraction → `stripped`, multi-line dedent, `raw` fallback); `hermes chat -q` invocation (DEVNULL stdin, timeout, `HERMES_BIN`/`HERMES_TIMEOUT` overrides); `is_available`; timeout/non-zero/exception errors; metadata (`transport="cli"`, `source`, `parse_mode`); empty-output failure; diagnostics records hermes as a `cli` attempt — all fully mocked (Milestone 23)
- **Web UI status** (`test_chat_status_ui.py`): `/chat` forwards the M22 trace on `ChatResponse.diagnostics` (and `null` when absent); template-presence of `#chat-status` and the existing memory/settings/history panels (Milestone 24; JS summary/in-flight behavior not exercised — no JS runtime); plus M26.1 cache-busting — `/` emits versioned `?v=` asset URLs and static responses send a `no-cache` revalidation header
- **Diagnostics UI** (`test_diagnostics_ui.py`): contract — `RequestTrace`/`ProviderCallRecord` `as_dict()` expose the keys the M24.5 timeline/details read, preserved through `/chat`; template-presence of the in-flight progress bar; existing panels unaffected (Milestone 24.5; JS render not exercised — no JS runtime)
- **CLI** (`test_cli.py`): argument parsing; one-shot prints the answer to stdout; `--list-providers` skips routing; `--provider`/`--mode` overrides reach `route()`; missing prompt → usage error (exit 2); all-providers-failed → exit 1 with clean stdout; invalid profile → exit 1; auto-extraction runs by default, is skipped with `--no-memory`, and is non-fatal on failure; plus the `ask` alias (`_normalize_argv`, `ask`-prefixed routing, lone `ask` → usage error, Milestone 17); plus M25 status: `--diagnostics` emits the summary + breakdown on stderr while `--quiet` suppresses both, with stdout staying answer-only — all mocked (no real provider/router/network). M26.6 adds `test_configure_cli_logging_only_touches_tagged_handler`: `_configure_cli_logging` retargets only Athena's own tagged (`_athena_console`) console handler to stderr and leaves foreign handlers on the shared `athena` logger untouched — the regression guard for the bug that previously broke the whole CLI suite
- **CLI status feedback** (`test_cli_status.py`): `build_cli_summary` (the three web-mirrored forms + empty when no trace), `build_cli_breakdown` (multi-line, selected marked), and the `Spinner` (TTY-gated — silent off-TTY/when disabled, animates + clears on stop) (Milestone 25); plus the M27.0 live status — `live_status_text` label formatting (with/without transport, graceful on a malformed payload) and `Spinner.set_text` (updates the live label shown on a TTY, safe/no-output when disabled)
- **Router live-status callback** (`test_provider_router.py`, M27.0): `route(on_attempt=…)` fires once per *available* provider in attempt order (including fall-through), does not announce unavailable/skipped providers, and a **raising callback never breaks routing** (measure-only, mirrors diagnostics)
- **Token usage** (`test_token_usage.py` + `tests/js/usage.test.js`, M27.1): `extract_openai_usage` (counts-only, defensive — partial counts, rejects `bool`, `None` when absent), the router copying `usage` onto the selected record (and `None` when the provider doesn't report), `build_cli_usage` (full / "unavailable" / partial), and the web-UI `buildUsageText` (full / "unavailable" / partial, thousands-separated). Content-free throughout — counts, never token text
- **Saved items** (`test_saved_items.py`): `SavedItemsManager` CRUD for searches and actions, allowed-field-only updates (id protected), delete, persistence round-trip, search/action independence — pure unit tests over a temp dir
- **Saved items API** (`test_saved_api.py`): `/saved/searches` and `/saved/actions` CRUD; non-`files` target rejected (400); saved file-search run returns matching paths; saved-action run routes the prompt through a mocked router with mode/provider overrides; 404s — via the `client` fixture (Milestone 18)
- **Settings panel (template)** (`test_settings_ui.py`): the served page wires the Settings panel (button, panel, three Profile/Providers/Integrations tabs) and the existing Memory panel is unaffected — template-presence only, no JS runtime (Milestone 19)
- **Editable settings** (`test_settings_edit.py`): `PATCH /profile` persists and applies `system_prompt`/`routing.mode`/`routing.preferred_provider` (and clears preferred with `""`); invalid mode, unknown provider, empty body, and over-long prompt each return 400 with **no disk write and no runtime mutation**; a success writes a `settings_update` audit event; non-editable fields (e.g. `name`) are ignored — all via the `client` fixture (Milestone 26; the editable UI is JS-rendered and not exercised)
- **History panel (template)** (`test_history_ui.py`): the served page wires the History & Attachments panel (button, panel, Conversation/Files tabs) and the Memory and Settings panels are unaffected — template-presence only (Milestone 20)
- **Files-tab hygiene** (`test_files_hygiene.py`): `_is_internal_path` classifies internal (logs/audit/staging/backups, `*.log`/`.gitkeep`/`*.pyc`) vs user files; `/files/search` with `exclude_internal: true` hides the internal set while the default listing is unfiltered (backwards-compatible) — the allowlist is unchanged (Milestone 26.3)
- **CardDAV safety invariants** (`test_carddav_safety.py`): config error on missing credentials, stage_merge never writes to server, commit requires valid staged_merge_id, stage+discard flow
- **Memory API** (`test_memory_api.py`): create/read/delete memory via HTTP
- **Files API** (`test_files_api.py`): allowlist management, write/read via HTTP, path traversal rejection, config write protection
- **VCF/ICS import & export** (`test_dav_io.py`): VCF parse (single/multiple/invalid cards), conflict detection (UID match, FN+email match, no-conflict), import flow with mocked CardDAV client (no conflicts, conflict queued, failed PUT, invalid content, mixed batch), VCF export from dicts; ICS parse (VEVENT/VTODO/invalid), conflict detection (UID match, no-match, empty UID), import flow with mocked CalDAV client (no conflicts, conflict queued, add_event failure), ICS export (from dicts, with raw_component, empty); API endpoint tests (503 when disabled, 200 for local conflict list, 404 for missing batch/conflict)
- **Backup/Export/Import** (`test_backup.py`): export creation (path, manifest, profile.yaml inclusion), `.env` exclusion, optional audit inclusion, list exports (empty and after create), inspect manifest, dry-run diff (new files, overwrite files), restore confirm=false (no writes), restore confirm=true (applies changes), pre-restore file staging, `.env` skipped during restore, delete export, audit log written on export; API endpoint tests (list, create, diff, restore dry-run, inspect, 404 for nonexistent)
- **DAV status store** (`test_dav_status.py`): DavStatusStore init (all three integrations pre-populated), success/error recording, field updates, error-then-success clears error fields, error humanisation (ConnectionRefusedError, 401/403/404 strings, TimeoutError, SSL, config errors), ETag/CTag/sync_token storage, warning cap at 10 (most recent retained), set_enabled, reset(), get() returns copies, get_all() returns copies, item_counts merging; API endpoint tests: `GET /status/dav` always 200 with all three integrations and required fields, `GET /status/dav/{integration}` returns correct record, `GET /status/dav/unknown` returns 404, status always 200 when disabled, `POST /status/dav/{integration}/check` returns 503 when disabled, unknown integration returns 404
- **Operational hardening** (`test_ops_hardening.py`): `write_ops_event` writes valid JSON-lines entry, `write_ops_event` never raises on bad input, multiple entries appended correctly; diff endpoint returns `diff_token`; restore with `confirm=True` and no token returns 409, expired token returns 409, valid token succeeds (200), confirm=False needs no token; memory delete audit call verified (mock); file write audit call verified (mock); unhandled exception handler returns sanitised 500 (not raw traceback); `/health` reports the current release version; token is single-use (second use returns 409); restore timeout returns 504; DAV check timeout returns 504; unknown DAV integration still 404
- **Web UI correctness** (`test_ui_correctness.py`, 7 tests, M26.10): source-structure guards on the shipped `static/js/chat.js` and `static/css/chat.css` — the assistant turn is pushed only inside the success branch (not before the `success` check), the network `catch` is scoped (a single "Network error" emission + `try/finally` reset), `voice` is accessed via `typeof` guards, the canonical mode/provider is injected as a selectable option, panel loaders are `_panelLoadToken`-guarded, the post-save re-render is tab-guarded, and `.history-count`/`.settings-note` have CSS rules. **No JS runtime is exercised by the suite** (a JS/UI harness is on the "Later / unscheduled" list); the M26.10 behaviour was verified live with headless Chromium (Playwright) during implementation — failed-answer non-replay, provider-error vs "Network error", UI survival with `voice.js` aborted, and canonical-provider selectability when `/providers` returns 500 — but that browser check is intentionally not added to the pytest suite to avoid new flaky browser-dependent infra
- **Calendar/DAV correctness** (`test_dav_correctness.py`, 14 tests, M26.9): ICS DATE-TIME formatting via `_format_ics_datetime` (offset→UTC+`Z`, negative offset, naive→floating no-`Z`, trailing-`Z` round-trip, date-only unchanged, unparseable→floating fallback); ICS TEXT escaping via `escape_ics_text` in both `_reconstruct_component` and CalDAV `create_task` (newline/comma/semicolon/backslash escaped — no property injection); `DavStatusStore.get()`/`get_all()` return deep copies (mutating a snapshot doesn't corrupt the singleton); Nextcloud `read_file` enforces the 2MB cap while streaming (an oversized body is not fully buffered); backup manifest `app_version` reflects the constructed version; and vCard multi-value `EMAIL`/`TEL` survive parse→`export_vcf` reconstruct. Mocked `requests`/caldav; no network
- **Provider robustness** (`test_provider_robustness.py`, 11 tests, M26.8): ChatGPT API is bounded (`timeout`/`max_retries=0` passed to the client; `OPENAI_TIMEOUT` honoured) and maps `APITimeoutError`/`APIConnectionError` to clean `success=false` responses (timeout classified as `timeout`); the CLI adapters (claude/gemini/grok/hermes) pass `stdin=DEVNULL` + `encoding="utf-8"`/`errors="replace"`; an unknown routing mode falls back to `balanced` (not `quality-first`) with a warning; and `ProviderRouter._transport_for` reports a dynamic adapter's real `transport()` on records with no response metadata (e.g. an unavailable Grok in API mode). Saved-action override validation is in `test_saved_api.py` (invalid mode / unknown provider → 400) and CLI `--provider` typo handling in `test_cli.py` (exit 2). All mocked; no network
- **Portable Profiles** (`test_portable.py`, M28.0 export + M28.1 import, 14 tests): identity kept vs host fields stripped (`machine_overrides`/`memory.path`), pending-review + `config/` + `.env` never in the zip, no `hostname` in the manifest, preview lists entries and `exclude_ids` is honored, **the leak guard hard-fails (409, nothing emitted) on a planted `.env` value, a credential-shaped string, and a URL in profile fields**, a memory URL is warning-only, portable/backup listings stay disjoint; import: round-trip preserves identity (+ empty pending queue), clobber attempt → 409, full-backup zip rejected as wrong type, **planted secret in a hand-crafted bundle → 409 with no profile dir created**, host fields re-sanitized on the way in, unknown provider warns but imports
- **Filesystem write-safety** (`test_write_safety.py`, 13 tests, M26.7): memory `category` traversal is rejected at both the API (`POST /memory` → 400) and the manager (`_category_path` raises for any non-allowlisted stem), with no file written outside the memory dir; backup restore Zip-Slip is contained (`BackupManager.restore_backup`/`diff_restore` skip and `rejected`-count any member — relative `../…` or absolute — that would escape the app root, while in-root members restore normally); `diff_token` is bound to its `zip_filename` (a token from one backup's diff → 409 on another); and `_safe_export_path` rejects `../`/absolute backup filenames (400). Real temp zips, no network
- **Thread-safety & consistency** (`test_thread_safety.py`, 6 tests, M26.16): `DavStatusStore` survives concurrent writer threads vs `get`/`get_all` deepcopy snapshots (previously "dictionary changed size during iteration"); `DiagnosticsStore` survives concurrent `record` vs `recent`/`last`; `MemoryManager.add_to_pending` from 8 racing threads loses no updates (RLock-serialised YAML read-modify-write); `humanise_error` is public with the `_humanise_error` compat alias; and `backup_inspect` routes through `_safe_export_path` like its sibling routes (spy assertion + valid-zip 200). Threads + tmp dirs; no network
- **Nextcloud/XML correctness** (`test_nextcloud_correctness.py`, 4 tests, M26.15): the DASL search body XML-escapes the query (a query containing `&`/`<`/`>` produces well-formed XML, LIKE `%` wildcards survive, and the SEARCH result is used — no silent fallback to the local filter); the Nextcloud client logs through the shared `core.logger`; and entity-defining XML from a (compromised) server is rejected by defusedxml in both the Nextcloud (`NextcloudConnectionError`) and CardDAV (`CardDAVConnectionError`) clients instead of being expanded. Mocked `requests`; no network
- **File-read robustness & local-I/O offload** (M26.14, 5 tests across three existing files): `read_file` caps at 2MB with `truncated: true` and decodes binary/non-UTF-8 content with replacement characters instead of raising (`test_file_manager.py`); `GET /files/read` on a binary allowlisted file returns **200**, not the previous unhandled-`UnicodeDecodeError` 500 (`test_files_api.py`); and a slow `/files/search` no longer blocks a concurrent `/health` — representative of the `files_read` + backup create/list/inspect/diff `to_thread` offloads (`test_concurrency.py`)
- **DAV SSRF guard** (`test_dav_ssrf.py`, 21 tests, M26.13): `ensure_same_origin` unit matrix (same origin / default-port equivalence / case-insensitive host / relative hrefs allowed; other host, other scheme, other port, userinfo trick, scheme-relative, metadata-service IP, unparseable port all rejected); `CardDAVClient._request` refuses an off-origin URL **before any network I/O** (and still allows the configured origin); `delete_contact` rejects an off-origin absolute href; CalDAV `list_events`/`create_task` reject off-origin calendar URLs before connecting; `import_ics`/`import_vcf` fail fast on off-origin targets; and API-level checks that `GET /caldav/events` / `GET /carddav/contacts` with a foreign URL return **400** (the `DAVSecurityError` handler), not 5xx. Mocked; no network
- **DAV transport timeouts** (`test_dav_transport.py`, 7 tests, M26.12): every outbound CardDAV request flows through `CardDAVClient._request`, which applies an explicit socket timeout by default (caller can override), returns non-2xx responses with `check=False` while still raising `CardDAVConnectionError` on network errors, and is the module's only `requests.request` call site (source-level chokepoint guard — timeouts and future URL validation can't be bypassed); `delete_contact` keeps its 204→True / 404→error semantics through the chokepoint; CalDAV `_connect` constructs `caldav.DAVClient` with an explicit `timeout`. Mocked `requests` / fake `caldav` module; no network
- **Concurrency hardening** (`test_concurrency.py`, 6 tests): a slow `POST /chat` (route blocks 1s in a worker thread) does **not** block a concurrent `GET /health` (returns in <0.5s — the loop-not-blocked proof); a forced route timeout returns a clean `success=false` "timed out" response (HTTP 200, not 500); a hanging `auto_extract` times out without failing the answered chat; a `/providers` availability-probe timeout returns 503 (not 500); a slow CalDAV read (`GET /caldav/calendars`) likewise does not block `/health` and a forced DAV-read timeout returns 504 — representative of all the wrapped CalDAV/CardDAV/Nextcloud endpoints. Drives the ASGI app via `httpx.AsyncClient` inside `asyncio.run` — no pytest-asyncio dependency, no real providers/network (Milestone 26.5)

## Frontend tests (jsdom, M26.22)

The Python suite checks the shipped JS by *source-structure* assertions only (it
runs no JS engine). A separate **jsdom** suite runs the **unmodified**
`static/js/chat.js` and `voice.js` for real — `tests/js/*.test.js`, driven by
`vitest`. It's independent of the Python suite (different toolchain), so
Python-only contributors don't need Node.

```bash
npm install        # first time (dev-only; node_modules is gitignored)
npm run test       # or: task test:js   (vitest run)
```

`tests/js/loadChat.js` boots the real scripts in a jsdom DOM skeleton with a
mocked `fetch` (a test-only shim footer exposes the module-scope helpers — the
production files are never modified). Coverage: the M26.10 send behaviours — a
provider-failure (`success:false`) is **not** replayed into history, a network
error shows exactly one message and records no assistant turn, an HTTP error
surfaces the server detail (not a generic network error), empty input is a
no-op; `appendMessage` is XSS-safe (`textContent`); `buildDiagnosticsSummary`
formatting; and `voice.js` degrades safely (answers still render when the Web
Speech APIs are absent). `pwa.test.js` (M26.28) covers the service-worker
**registration guard** — a clean no-op on an insecure context (no
`navigator.serviceWorker`), and `register("/sw.js")` when the API is present (the
worker's runtime caching isn't unit-tested — jsdom has no service-worker
runtime; the `/sw.js` route + manifest are covered by `test_pwa.py`). The
Python-side source-structure guards (`test_chat_status_ui.py`,
`test_ui_correctness.py`) are kept as belt-and-braces.

## What is intentionally not covered yet

- Live CalDAV / CardDAV / Nextcloud network calls (all mocked)
- AI provider completions (all adapters are not available in CI without credentials)
- Voice STT/TTS *end-to-end* (browser-only Web Speech API; the jsdom suite covers
  the unsupported-environment degradation, not real speech)
- Full end-to-end browser rendering/CSS (jsdom is not a full browser; M26.10 was
  smoke-verified with headless Chromium during implementation)
- Docker build and container integration

## Running the tests

### Setup (first time only)

```bash
cd athena-assistant
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Run all tests

```bash
source .venv/bin/activate
pytest
```

### Coverage (M26.24)

```bash
task coverage        # pytest --cov --cov-report=term-missing
task coverage:html   # browsable htmlcov/index.html
```

Config in `pyproject.toml` `[tool.coverage]` (measures application code only —
`tests/` omitted). Source-only baseline is **~74%**; CI enforces a `fail_under`
floor of **70%** (a ratchet, not a target — raise it as coverage improves). The
biggest gaps are the DAV/network clients, whose critical paths are covered by
the M26.12–M26.15 tests but which would need live servers to exercise fully.

### Run a specific test file

```bash
pytest tests/test_file_manager.py
pytest tests/test_carddav_safety.py
```

### Run with output

```bash
pytest -s                        # show print statements
pytest -v                        # verbose (already default via pytest.ini)
pytest --tb=long                 # full tracebacks on failure
```

### Run a single test

```bash
pytest tests/test_file_manager.py::test_path_traversal_via_write_rejected
```

## Required test setup

No environment variables, live servers, or API keys are needed. All network calls are mocked. Tests run entirely in temporary directories — no production data is touched.

## Known issues / notes

- `test_chat_returns_error_when_no_providers` expects `success: false` in the response body since no real AI providers are available in CI. This is intentional — it validates the fallback path.
- The `client` fixture re-imports `main` on each test function to ensure APP_ROOT patching takes effect. This adds ~100ms per test using the fixture.
