# Changelog

All notable changes to Athena Assistant. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project versions
each milestone as a release. Newest first.

## [3.0.5] — Milestone 30.6 — Voice output/input controls

**App bumped to 3.0.5.** Spec: `docs/specs/M30.6-voice-controls.md`. From the
desktop triage: answers were read aloud unconditionally in an unpleasant
default voice, the mic stopped at the first pause, and transcripts
auto-sent.

### Added
- **Settings → Voice section** (Profile tab): per-BROWSER preferences,
  instant-apply, persisted in `localStorage` (`athena-voice-prefs`) — NOT in
  profile.yaml (device-level accessibility settings; the narrow editable
  profile set is untouched). Defaults per the user's direction: **speak
  responses OFF**, **auto-send transcript OFF** (dictation lands in the
  input for review, like typing), voice = browser default, continuous mic
  OFF.
- **Voice picker** from the browser's system voices
  (`speechSynthesis.getVoices()`, async-load handled via `voiceschanged`) —
  TTS is browser-side and provider-independent; the genuinely-human upgrade
  remains the M31.1 Piper endpoint on the roadmap.
- **Continuous mic mode**: keep listening across pauses until the mic is
  clicked again; final results accumulate and deliver as one transcript.
  Default remains the M5 stop-on-pause behavior.

### Notes
- Pre-M30.6 behavior (always speak, always auto-send) remains reachable by
  flipping the toggles.
- Gate: ruff + mypy exit 0 + **612 pytest** + **34 vitest** (+6 jsdom).

## [3.0.4] — Milestone 30.5 — Attachment content inlining

**App bumped to 3.0.4.** Spec: `docs/specs/M30.5-attachment-inlining.md`.
"Attach a text file and ask about it" never actually worked by design —
`[Attached file: <path>]` was a bare reference no provider could act on (API
transports have no filesystem; the agentic claude transport correctly runs
in a neutral cwd since M30.3, searched there, and misdiagnosed the upload as
broken).

### Added
- `core/chat_turn.inline_attachments()` — applied inside the shared
  `build_turn_messages()` seam, so web AND CLI get it identically: the NEW
  message's reference lines are expanded with the file's content for the
  **provider-bound copy only**. History, the UI bubble, memory extraction,
  and exports keep the raw reference form; replayed history turns are not
  re-inlined (cost bound).
- Reads go through **FileManager** — the allowlist governs, like every
  read. Text extensions only (conservative list); 32 KB cap per file with an
  explicit truncation marker; max 3 attachments per message; best-effort —
  any failure leaves the reference byte-identical. Images/binaries stay
  reference-only until a vision path exists (Later).

### Notes
- Gate: ruff + mypy exit 0 + **609 pytest** + 28 vitest.

## [3.0.3] — Milestone 30.4 — Uploads visibility + attach UX

**App bumped to 3.0.3.** Spec: `docs/specs/M30.4-uploads-visibility.md`. From
live desktop testing: uploads WORKED (files verified on disk) but looked
broken — three UI defects created the illusion (and the agentic claude
transport, searching its M30.3 neutral cwd, confidently misdiagnosed it).

### Fixed
- **Raw `<input type="file">` rendered next to the 📎 button** — it carried
  `class="hidden"` but chat.css has only *scoped* `.hidden` rules, never a
  bare one, so the browser default applied (visible since M29.3). Now hidden
  via its own `#attach-input` rule (deliberately NOT a global `.hidden`).
- **Uploaded files were invisible in the Files tab** — the M20-era listing
  globs `*` non-recursively, one level short of `data/uploads/<file>`. The
  tab now merges the shallow listing with a best-effort `uploads/*` search.
- **Directories listed as clickable "files"** whose preview 400s —
  `search_files()` now returns files only.

### Docs (triage decisions recorded, user-approved)
- INVARIANTS: integrations settings are **read-only by design** (a no-auth
  LAN-reachable UI must never write credentials); search results files-only.
- TROUBLESHOOTING: "the model *says* it's a different model than the label"
  — the meta line is ground truth; self-reports come from configured
  identity + replayed history (observed: grok-4.3 claiming to be Claude
  Opus because a prior claude turn said so in context).
- CLAUDE.md Later/unscheduled: provider enable/disable UI toggles;
  failure-cooldown for repeatedly failing providers (the observed 28–52s
  "gemini tax" per message); probe `include_usage` support on grok/ollama
  streams (web UI streams by default now, so those turns show "Tokens:
  unavailable").

## [3.0.2] — Milestone 30.3 — Neutral cwd for CLI provider subprocesses

**App bumped to 3.0.2.** Spec: `docs/specs/M30.3-neutral-cwd.md`. Found live:
`athena --provider claude "hello"` run from inside the Athena repo answered
as the repo's coding agent after 54 seconds — the claude CLI inherited the
caller's cwd, discovered the project's `CLAUDE.md` + SessionStart hook (which
ran the full test suite per message), and pulled ~15k tokens of project
context into a chat turn.

### Fixed
- All five CLI-adapter subprocess calls (claude completion + `--help` probe,
  gemini, grok-cli, hermes) now pass `cwd=neutral_cwd()` (the system temp
  dir, `providers/base.py`) so vendor CLIs cannot discover project-level
  agent config from wherever `athena` happens to be invoked. User-global
  vendor config (`~/.claude/` login/identity) still applies by design.
  Test-pinned per adapter, probe included.

### Notes
- Gate: ruff + mypy (exit 0) + **595 pytest** + 28 vitest.

## [3.0.1] — Milestone 30.2 — Green mypy gate + CalDAV ETag fix

**App bumped to 3.0.1.** Spec: `docs/specs/M30.2-mypy-gate-fix.md`. Found via
the M30.1 incident's claude-in-repo session flagging "type-check issues":
`mypy .` exited 1 on a fresh checkout (8 errors; `task ci`'s typecheck step
was red), and the gate had been mis-assessed through a shell pipe for several
milestones (erratum in `docs/history/REVIEW-3.0-2026-07.md`).

### Fixed
- **CalDAV ETag recording** — `caldav.dav` does not exist in caldav 3.x, so
  the ETag fetch (`caldav.dav.GetEtag()`) raised AttributeError into its
  guard on EVERY call and `dav_status` etags silently recorded as `""` since
  the caldav 3 pin. mypy's `attr-defined` error was pointing at this real
  bug. Now imports `GetEtag` from its true home (`caldav.elements.dav`);
  the import path is regression-pinned so a future caldav bump fails loudly.
- **The 7 remaining errors** are caldav's py.typed PEP 562 lazy loader typing
  module attrs as `object` — suppressed with precise per-line
  `# type: ignore[operator]` comments. Deliberately NOT "fixed" via
  real-submodule imports: the DAV test fakes mock at the `caldav` module
  boundary and would be silently bypassed (INVARIANTS now records this).
- **INVARIANTS**: the type gate is `mypy .`'s EXIT CODE — never assess it
  through a pipe.

### Notes
- Gate: `mypy .` exits 0 ("no issues found in 69 source files") — plus ruff,
  **594 pytest**, 28 vitest.

## [Unreleased] — Milestone 30.1 — Taskfile developer experience

Tooling/docs only — **no code change; the app stays 3.0.0**. Spec:
`docs/specs/M30.1-taskfile-dx.md`. Closes the gap behind a real post-3.0
incident (`athena` failing with `No module named 'diagnostics'` in a venv
whose editable install was missing): `task setup` and `task install` now run
`pip install -e .` (the step that provides the `athena` command and maps
Athena's packages — previously only buried inside `task ci`); new
`task update` (post-pull one-shot: install + guarded `npm install` + prints
the installed version) and `task doctor` (surfaces the M28.6 preflight).
`docs/TASKFILE.md` also backfills the never-documented M26.19–M26.26
quality-gate and operations tasks; README quick start now produces a working
`athena`; TROUBLESHOOTING's `No module named` entry documents the real cause
(stale editable snapshot) and the `task install` remedy. Deliberately not
added: a `task cli` passthrough.

## [3.0.0] — Milestone 30 — Streaming

**Major release.** Spec: `docs/specs/M30-streaming.md`. Responses render as
they are generated on both surfaces; everything that can't stream degrades
honestly to the buffered behavior. Major because the *delivery contract*
changes (new `/chat/stream` endpoint is the web UI's default path; the CLI
prints incrementally by default) — the buffered `POST /chat` remains,
byte-compatible, as the safety net and the API contract for anything
scripted against 2.x.

### Added
- **Adapters** — `ProviderAdapter.supports_streaming()` (default False) and
  `complete_stream()` → yield text chunks, then the final ProviderResponse.
  Implemented by `chatgpt` (with `stream_options={"include_usage": True}` —
  usage lands on the final chunk), `ollama` and `grok` *api transport only*
  (no `stream_options` — compat risk; usage recorded only if the server
  volunteers it, honestly absent otherwise). CLI transports answer whole and
  keep the default False. Error strings and client bounding
  (`timeout=…, max_retries=0`) identical to `complete()`.
- **Router** — `route_stream()`: the SAME attempt loop as `route()` (shared
  `_build_attempt_order`/`_callable_attempts`/`_attempt_*` internals — the
  routing logic is not forked), yielding `("chunk", text)` events then
  exactly one `("done", ProviderResponse)`. Zero-chunk failures fall through
  to the next provider exactly like `route()`; a failure AFTER chunks stops
  the request (text cannot be un-emitted); non-streaming adapters degrade to
  one buffered chunk + done. `on_attempt` (M27.0) and the M22 trace behave
  identically in both modes.
- **HTTP** — `POST /chat/stream` (SSE, `text/event-stream`): `event: chunk`
  / `data: {"text": …}` frames, then one `event: done` whose payload mirrors
  ChatResponse (+ `error`, for failures that occur after text was already
  delivered). Same conversation_id validation/creation, user-turn record,
  memory extraction, assistant-turn record (all complete BEFORE the done
  frame), and total `_ROUTE_TIMEOUT` budget as `/chat`. The sync generator
  is driven by per-step `asyncio.to_thread(next, it, sentinel)` against a
  monotonic deadline (M26.5 — the loop stays responsive).
- **Web UI** — `sendMessage` posts to `/chat/stream` first and grows the
  assistant bubble as chunks arrive (`textContent` — XSS posture unchanged);
  the done event supplies provider/model meta, diagnostics, history push,
  TTS, and the authoritative full text. **Any failure before the first
  chunk falls back to the buffered `/chat`** — the UI is never less reliable
  than 2.x. Failures after chunks render the partial text plus an error
  bubble and are never re-sent or recorded as context (M26.10).
- **CLI** — streams by default: chunks print to stdout as they arrive (the
  answer-only contract holds — the chunks ARE the answer; spinner stops at
  the first chunk; status stays on stderr). New `--no-stream` flag keeps the
  buffered pre-3.0 behavior — recommended for strict scripts, since a
  provider dying mid-reply can leave a partial answer on stdout (the run
  still exits 1 with the error on stderr). The REPL streams per turn the
  same way.

### Changed
- **Empty output is now a failure on EVERY adapter, in BOTH modes**
  (chatgpt / ollama / grok-api / grok-cli / gemini added here; hermes
  always did; claude since M29.8): "<Provider> returned no output." The
  router falls back to a provider that answers instead of returning a blank
  success — and streaming's zero-chunk fallback depends on it. This is the
  REVIEW-3.0 F14 norm applied uniformly for 3.0.

### Notes
- Diagnostics: a streaming attempt's `call_ms`/`duration_ms` include
  delivery time (the generator is suspended at each yielded chunk) — the
  user-perceived answer time, stated in `route_stream`'s docstring.
- Client disconnect mid-stream abandons the turn: user turn kept, no
  assistant turn recorded (the reply was never delivered).
- Out of scope (unchanged from the spec): WebSockets, mid-stream token
  ticking in the UI, streaming for CLI transports, SSE reconnect/resume.
- Pre-release scoped diff-review of M30's own diff: addendum in
  `docs/history/REVIEW-3.0-2026-07.md` (3 fixes applied, 4 observations
  blessed, verdict: fit to ship).
- Gate: ruff + mypy (8-error pre-existing stub baseline) + **593 pytest**
  (coverage 77%, floor 74) + **28 vitest**. +49 Python / +6 JS tests.

## [Unreleased] — Milestone 29.9 — Remediation diff-review

Docs only — **no code change; the app stays at 2.9.8**. Spec:
`docs/specs/M29.9-remediation-review.md`. Scoped fresh-eyes review of the
M29.8 diff (user-directed cadence-rule application): every fix verified
against its finding in the final committed state; **no new findings**; two
observations blessed (strict `is True` on `is_error`; REPL exception-path
parity). Addendum in `docs/history/REVIEW-3.0-2026-07.md`. **M30 → 3.0.0 is
clear to start** (and embeds a scoped review of its own diff before the
version-bump commit).

## [2.9.8] — Milestone 29.8 — Review remediation

**App bumped to 2.9.8.** Spec: `docs/specs/M29.8-review-remediation.md` —
implements the eight FIX-bucket findings of REVIEW-3.0 (post-errata queue),
each test-pinned. ~45 lines of code.

### Fixed
- **F1** — uploads now create files with **exclusive `"xb"`** inside the
  suffix loop: the filesystem enforces never-overwrite; a real two-thread
  same-name race test pins it (both payloads intact, distinct names).
- **F2** — the REPL keeps the user's question in context when a turn fails
  (web/`/resume` parity); only the failure TEXT is never replayed (M26.10).
- **F4** — claude envelope parse checks `is_error` **before** any shape
  fallback: an error envelope with null/absent `result` is a failure (text
  from `result`→`subtype`→generic), never raw-JSON-as-success.
- **F14** — claude **empty output → provider failure** in both modes
  ("Claude CLI returned no output.") — hermes parity; the router falls
  through to a provider that answers.
- **F5** — profile switch uses **update-then-prune** (never `clear()`+
  `update()`): `_profile_data` is never empty mid-switch, object identity
  preserved; structural + behavioral test pins.
- **F6** — one conversation-id validator
  (`history.manager.is_valid_conversation_id`) shared by `/chat` and the
  store; layer-agreement test added.
- **F7** — portable bundles: explicit negative test that `history/` (chat
  content) never travels.
- **F10** — claude.py module docstring refreshed (current CLI reference,
  M29.5 + M29.8 behavior documented).

### Notes
- Gate: ruff + mypy + 544 pytest (@74 floor) + 22 vitest. Per the cadence
  rule's spirit (user direction), M29.9 runs a scoped diff-review of this
  milestone before M30 begins.

## [Unreleased] — Milestone 29.7 — Pre-3.0 review & docs sweep

Docs/quality only — **no code change; the app stays at 2.9.6**. Spec:
`docs/specs/M29.7-pre-3.0-review.md`. Report:
`docs/history/REVIEW-3.0-2026-07.md`.

### Review (six lenses over M28.2–M29.6 + spot-checks of M26.27–M28.1)
- **15 findings, three buckets.** FIX → the proposed **M29.8 review-
  remediation queue** (awaiting approval): F1 upload same-name overwrite
  race, F2 orphan-user-turn inconsistency across surfaces (REPL to be
  aligned), **F4 claude.py error-envelope ordering gap** (new: an `is_error`
  envelope without a string `result` renders raw JSON as a successful
  answer), **F5 profile-switch empty-window race** (new: `clear()`+`update()`
  can expose an empty profile to a racing `/chat`), F6 duplicated
  conversation-id regex (new), F7 missing portable/history negative test,
  F10 claude docstring drift, **F14 empty-output→failure for claude (hermes
  parity)**. DEFER → F3 same-second id ordering tie and F8 cross-module test
  fakes (both with actionable Later/unscheduled entries). BLESS → F11 REPL
  closure, F12 probe cache, F13 store lock pattern (INVARIANTS note added).
  *Errata:* F8 and F14 were re-bucketed during the user's review of the
  dispositions — the report records why, and the consistency lens now names
  cross-adapter explicitly.
- Lens statements recorded for everything that came back clean (security
  traversal/secret sweep, concurrency audit, cross-surface contracts, test
  quality, ergonomics, pre-batch spot-checks).

### Docs sweep (all drift found in the spec investigation, all fixed)
- `docs/specs/README.md` rebuilt — 13 unlisted specs indexed, stale header
  gone; `docs/ARCHITECTURE.md` tree now carries `core/chat_turn.py`,
  `history/`, `cli/{repl,doctor,history_cmd}.py`, `backup/portable.py`, the
  `portable`/`history` routers; `docs/CONFIGURATION.md` documents the M28.5
  active-profile resolution order; root `README.md` CLI tour + layout brought
  current; `docs/VALIDATION.md`/`docs/RUNBOOK.md` lead with `athena doctor`;
  `docs/BACKUP.md` notes history rides in backups (portable bundles never);
  `docs/TESTING.md` "not covered" list updated (REPL terminal, SW runtime) +
  shared-fakes note; `docs/RUN_AND_VALIDATE.md` tombstone → `docs/history/`.
- **Review-cadence rule codified in CLAUDE.md** (user-requested): full review
  before any major; scoped review at each epic close; scoped review after any
  autonomous batch ≥5 milestones; three-bucket disposal mandatory.

### Quality
- **Coverage floor raised 70 → 74** (`pyproject.toml`): measured source-only
  coverage is 76.86% at 536 tests — same ~3-point headroom philosophy as the
  original setting.

## [2.9.6] — Milestone 29.6 — CLI history surfaces

**App bumped to 2.9.6.** Spec: `docs/specs/M29.6-cli-history.md`. Closes the
M29 asymmetry: the CLI can now read back what it writes.

### Added
- **`athena history`** — list (newest first; stdout, same answer rule as
  `--list-providers`); **`athena history <id> [<id> …]`** — transcript(s),
  order as given, `---` separated, failed turns marked; **`athena history
  export <id> [<id> …]`** and **`export --all`** — Markdown to stdout
  (redirect for one merged doc; shell-loop for separate files — the richer
  bundling deliberately deferred, see Later/unscheduled). Errors → stderr +
  exit 1. Routed as a pre-parser subcommand token (like `doctor`).
- **REPL**: `/list` (recent conversations, stderr — REPL status) and
  `/resume <id>` — loads stored turns as context (**success-only replay**,
  M26.10) and continues appending to that same conversation.
- **Shared renderer**: the Markdown builder moved from the HTTP router into
  `history/manager.py::render_markdown`; the export endpoint delegates —
  one renderer, two surfaces (test-pinned: HTTP body == store render).

### Notes
- Tests: `tests/test_history_cli.py` (7) + existing HTTP export regression.
  Gate: ruff + mypy + 536 pytest + 22 vitest.

## [2.9.5] — Milestone 29.5 — Claude model attribution

**App bumped to 2.9.5.** Spec: `docs/specs/M29.5-claude-model-attribution.md`.
Born from validating M28.2 against the **real** Claude CLI (2.1.206, run
live): the production envelope has no top-level `model` key — the model name
is the key of the `modelUsage` object.

### Changed
- `providers/claude.py`: when the envelope carries no top-level `model`, the
  name is attributed from `modelUsage`'s first key (best-effort: non-empty
  dict with a string key, else `None` — the M28.2 degradation contract
  unchanged). Claude turns now show their model in diagnostics, status lines,
  and history meta like every other provider.
- **Tests now pin the real 2.1.206 envelope** (structurally faithful fixture
  incl. `total_cost_usd`, cache-token fields, `iterations`, `session_id`) —
  the parser is proven against production shape, not a guess: content, usage
  mapping (5954/14/5968), `model == "claude-sonnet-5"`, top-level `model`
  precedence, and modelUsage edge cases.

### Notes
- Gate: ruff + mypy + 529 pytest + 22 vitest. Out of scope (unchanged
  decisions): cost fields, cache-token accounting.

## [2.9.4] — Milestone 29.4 — Conversation export

**App bumped to 2.9.4 — the M29 Conversations epic is complete.** Spec:
`docs/specs/M29.4-conversation-export.md`.

### Added
- **`GET /history/conversations/{id}/export`** — the persisted conversation
  as Markdown (`text/markdown`, attachment `<id>.md`): title + started-at,
  `## You` / `## Assistant (provider/model)` per turn, failed turns flagged
  `*(failed)*`. Same 400/404 semantics as the read endpoint (the store's id
  guard remains the single validation point).
- **UI**: an Export button on each Past-conversations item.

### Notes
- Tests: export round-trip (headers + structure + both turns), failed-turn
  flag, 404. Gate: ruff + mypy + 526 pytest + 22 vitest. **M29 shipped in
  full: shared turn helper → persistent history → REPL → uploads → export.
  Next: M30 — streaming → 3.0.0.**

## [2.9.3] — Milestone 29.3 — Real file uploads

**App bumped to 2.9.3.** Spec: `docs/specs/M29.3-file-uploads.md`.

### Added
- **`POST /files/upload`** (multipart): saves to `data/uploads/` — which the
  shipped allowlist already covers read/write, so uploads are immediately
  readable/searchable through the **existing guarded file machinery** (no new
  read path, no prompt auto-injection). Server-side name sanitization
  (basename only, `[A-Za-z0-9._-]`, no dotfiles), **10 MB cap enforced while
  streaming** (partial file removed on breach → 413), empty → 400, collisions
  get `-1`/`-2` suffixes (never overwrite). Content is opaque bytes. Ops-
  audited (name + size only).
- **`GET /files/uploads`** — newest-first listing.
- **UI**: 📎 attach button beside the input — uploads and inserts
  `[Attached file: data/uploads/<name>]` into the message box; the user stays
  in control of what's asked about the file.

### Notes
- Tests: `tests/test_uploads.py` (6) — allowlist round-trip via `/files/read`,
  traversal name lands sanitized *inside* the uploads dir, dotfile/weird
  chars cleaned, unique suffixing, oversize leaves nothing behind, empty
  rejected. Gate: ruff + mypy + 524 pytest + 22 vitest.

## [2.9.2] — Milestone 29.2 — CLI REPL

**App bumped to 2.9.2.** Spec: `docs/specs/M29.2-cli-repl.md`.

### Added
- **Interactive multi-turn REPL** (`cli/repl.py`): bare `athena` on an
  interactive stdin drops into a session — accumulated in-session history
  (replayed **only on success**, the M26.10 rule applied to the CLI), the
  M27 live-status spinner + summary/usage lines per turn, best-effort memory
  extraction, and **persistent history**: every REPL conversation is recorded
  to the M29.1 `ConversationStore` (visible in the web UI's Past
  conversations). Commands: `/new` (fresh conversation), `/exit`/`/quit`/EOF.
- **TTY-gated entry**: with stdin not a TTY (scripts, pipes, CI) the bare
  invocation stays a usage error (exit 2) — nothing can hang waiting for
  input, and the established one-shot behavior is untouched.
- **stdout stays answer-only** even in a session: the `you>` prompt, status,
  usage, and errors all print to stderr (M25 contract), so piping a REPL
  transcript yields clean answers.

### Notes
- Plain `input()` — no readline/TUI dependency. Streaming arrives in M30.
  Tests: `tests/test_repl.py` (5, scripted stdin): history accumulation,
  `/new` reset + one file per conversation, failure not replayed but
  persisted with `success:false`, EOF clean exit, non-TTY bare invocation
  still exit 2. Gate: ruff + mypy + 518 pytest + 22 vitest.

## [2.9.1] — Milestone 29.1 — Persistent cross-session history

**App bumped to 2.9.1.** Spec: `docs/specs/M29.1-persistent-history.md`.
Conversations now survive restarts as plain local files.

### Added
- **`history/manager.py`** (new package, declared in pyproject per M26.4):
  `ConversationStore` — append-only JSONL per conversation under
  `profiles/<name>/history/`, lock-guarded (worker-thread appends), ids
  validated `^[A-Za-z0-9_-]+$` **before any path build** (traversal guard);
  malformed lines skipped on read. `record_turn` joins the chat-turn helpers
  (same never-fail-a-turn contract as `extract_memory`).
- **`/chat`**: optional `conversation_id` in (400 on bad format; absent → a
  new conversation), returned in the response; user turn recorded before
  routing, assistant turn after (provider/model/success meta). History is
  best-effort throughout — store failure degrades to an unpersisted chat.
- **Endpoints**: `GET /history/conversations` (newest-first summaries with
  first-message preview), `GET/DELETE /history/conversations/{id}`.
- **UI**: the chat threads `conversation_id` automatically (Clear starts a
  fresh one); the History panel lists **Past conversations** — click restores
  the turns into the chat (failed turns render as errors and are NOT replayed
  as context, the M26.10 rule) and resumes that conversation.
- **Privacy**: `profiles/*/history/` is **gitignored** (chat text never lands
  in the repo); portable bundles (M28) already exclude it by allowlist
  construction. Full backups include it by design (same-host restore).

### Notes
- Profile switching re-points the store (test-pinned). CLI recording joins in
  M29.2 (REPL). Tests: `tests/test_history.py` (7) + jsdom threading test.
  Editable install re-verified from outside the tree (new package). Gate:
  ruff + mypy + 513 pytest + 22 vitest.

## [2.9.0] — Milestone 29.0 — Shared chat-turn helper

**App bumped to 2.9.0 — the M29 Conversations epic begins.** Spec:
`docs/specs/M29.0-chat-turn-helper.md`. Behavior-neutral refactor: ONE code
path assembling a chat turn for both the web `/chat` handler and the CLI, so
persistent history (M29.1) and streaming (M30) get built once.

### Added
- **`core/chat_turn.py`**: `build_turn_messages` (history pairs + new user
  message), `system_prompt_from` (the exact `or None` semantics), and
  `extract_memory` (the sync auto-extraction core — None-tolerant, swallows
  every exception, logged). FastAPI-free.

### Changed
- `/chat` and the CLI now assemble turns through the helpers. The surfaces'
  execution models are deliberately unchanged: HTTP keeps its
  `wait_for(to_thread(...))` + `_ROUTE_TIMEOUT`/`_AUTO_EXTRACT_TIMEOUT`
  wrappers; the CLI keeps the spinner + `on_attempt` live status. CLI bonus:
  a MemoryManager *construction* failure is now also non-fatal (previously
  only extraction was guarded).

### Notes
- Tests: `tests/test_chat_turn.py` (5 units); the full suite is the
  regression net for the rewiring. Gate: ruff + mypy + 506 pytest + 21
  vitest.

## [2.8.6] — Milestone 28.6 — `athena doctor` (preflight diagnostics)

**App bumped to 2.8.6.** Spec: `docs/specs/M28.6-doctor.md`. The executable
form of the M26.27 platform matrix.

### Added
- **`athena doctor`** (also `athena --doctor`): a preflight report —
  app/python versions, `.env` presence + which provider key **names** are set
  (**never values** — test-enforced), vendor CLIs on PATH, active-profile
  resolution (+ source: override/file/env/default) and `profile.yaml`
  validity, `logs/`/`audit/`/`data/` writability, free disk, DAV configs
  (enabled + url, **not probed**). Exit 1 iff any check fails; warns don't
  fail. Config/filesystem-only — deliberately **no network** (same rule as
  router availability), so it's deterministic and works offline.
- Implementation: `cli/doctor.py` (pure check functions → testable without
  stdout capture); `doctor` token normalised like the `ask` alias; runs
  before any profile/router init.

### Notes
- Tests: `tests/test_doctor.py` (6) — incl. the secret-hygiene contract (a
  planted key value never appears in the report). Gate: ruff + mypy + 501
  pytest + 21 vitest. **The 2.8.z patch batch (M28.2–M28.6) is complete.**

## [2.8.5] — Milestone 28.5 — Runtime profile switcher

**App bumped to 2.8.5.** Spec: `docs/specs/M28.5-profile-switcher.md`.
Completes the M28 story: an imported portable profile is now usable in-app.

### Added
- **`GET /profiles`** (list with `active` flag) and **`POST /profiles/activate`**
  — switch the active profile at runtime: validates the name
  (`^[A-Za-z0-9_-]+$`; blocks traversal) and the target `profile.yaml`,
  persists the selection to **`config/active_profile.yaml`**, clears the
  settings cache, and re-points `_profile_data`/memory/saved-items at the new
  profile dir. In-flight requests finish on the old profile (call-time `main.X`
  binding); new requests see the new one. Ops-audited; never touches `.env`.
- **Resolution order** (`core/config.py`): `ATHENA_PROFILE_OVERRIDE` env (the
  CLI's `--profile` now sets this — the explicit flag beats everything) →
  switch file → `ACTIVE_PROFILE` env → `athena`. The file deliberately beats
  env so a UI switch survives restart on default installs (where `.env` sets
  `ACTIVE_PROFILE`); a broken switch file falls through harmlessly.
- **UI**: settings → Profile tab gains an "Active profile" dropdown + Activate
  (shown when >1 profile exists); full reload on switch.

### Notes
- Test-infra: an autouse conftest guard clears `ATHENA_PROFILE_OVERRIDE`
  between tests (the CLI is one-shot in production but in-process in tests —
  without the guard the flag's env write leaked into 32 later tests).
  Tests: `tests/test_profile_switch.py` (6). Gate: ruff + mypy + 495 pytest +
  21 vitest.

## [2.8.4] — Milestone 28.4 — Mobile-responsive UI pass

CSS + one viewport-meta attribute — **app bumped to 2.8.4**. Spec:
`docs/specs/M28.4-mobile-ui-pass.md` (renumbered: shipped before the profile
switcher/doctor, which become M28.5/M28.6 — milestone==version stays monotonic).

### Changed
- **Phone correctness layer** in the existing small-screen media query: the
  three side panels (memory/settings/history) go full-width (was fixed 340px —
  a dead sliver on a 375px screen), `#message-input` gets `font-size: 16px` on
  phones (kills the iOS focus-zoom; desktop unchanged), header buttons get
  36px+ tap targets.
- **Viewport correctness**: `#app` gains `height: 100dvh` (input stays above
  mobile browser chrome; older browsers keep `100vh`) and
  `env(safe-area-inset-*)` padding for notched phones in PWA standalone;
  template viewport meta gains `viewport-fit=cover` (required for env() to be
  non-zero). Insets are 0 on non-notched devices — desktop is visually
  unchanged.

### Notes
- Built without a physical phone: every rule is media-query-scoped or
  zero-by-default. **USER TODO (morning):** open Athena on the phone over
  Tailscale (and as the installed PWA) and eyeball; report anything off.
  Gate: ruff + 489 pytest + 21 vitest.

## [Unreleased] — Milestone 28.3 — Remote-access doc

Documentation only — **no code change; the app stays at 2.8.2**. Spec:
`docs/specs/M28.3-remote-access-doc.md`.

### Added
- **`docs/REMOTE-ACCESS.md`** — the how-to behind the platform matrix's
  remote-access caveat: Pattern A (Tailscale/VPN, incl. `tailscale serve` for
  tailnet HTTPS → PWA install), Pattern B (authenticated reverse proxy + TLS
  with an illustrative Caddy snippet), an explicit anti-pattern list (no
  `0.0.0.0` on public bridges, no direct port-forwarding, no auth shim inside
  Athena — the no-auth design is deliberate), and bind-verification commands.
  Linked from `docs/README.md`; `PLATFORMS.md`'s summary now points here for
  detail (the how-to lives in exactly one place).

## [2.8.2] — Milestone 28.2 — Claude-CLI token usage (JSON envelope)

The deferred M27.1 follow-up — **app bumped to 2.8.2**. Spec:
`docs/specs/M28.2-claude-cli-usage.md`.

### Added
- **Claude CLI usage capture**: when the installed CLI advertises
  `--output-format` (feature-detected once via `claude --help`, cached),
  completions run with `--output-format json`; the envelope's `result` becomes
  the answer, `model` is recorded, and `usage.input_tokens`/`output_tokens`
  map onto `metadata["usage"]` (prompt/completion/total) — so the M27.1 UI and
  CLI token surfaces now light up for Claude too.
- **Defense throughout** (built without access to a real CLI — the mocked
  suite pins the documented envelope): no flag in help → plain invocation
  verbatim; non-JSON stdout or missing `result` → raw stdout is the answer, no
  usage; `is_error: true` → provider failure with the result text; probe
  failure → plain. The error path (non-zero exit/timeout) is byte-identical to
  before.

### Notes
- **Morning validation (user TODO):** run
  `claude -p "Say hi" --output-format json` and confirm the envelope has
  `result` + `usage.input_tokens`/`output_tokens`. If it differs, Athena still
  answers correctly via the fallbacks — send the real envelope so the parser
  can be adjusted. Tests: `tests/test_claude_usage.py` (13). Gate: ruff + mypy
  + 489 pytest + 21 vitest.

## [2.8.1] — Milestone 28.1 — Portable Profiles: import

Second half of the **M28 epic** — **app bumped to 2.8.1**. Spec:
`docs/specs/M28-portable-profiles.md`. Docs: `docs/PORTABLE-PROFILES.md`.

### Added
- **`PortableProfileManager.import_bundle`** + **`POST /portable/import`**:
  materialize a **new** profile from a bundle in `data/exports/`. Defense in
  depth — the incoming content is re-run through the **same allowlist**
  (`_sanitize_profile`: a hand-edited bundle's `machine_overrides`/`memory.path`
  are stripped on the way in) and the **same leak scan** (a planted secret /
  credential-shaped string / profile URL → 409, nothing written). Wrong or
  missing bundle type marker → 409.
- **No-clobber**: importing never overwrites an existing profile (409 — pass
  `new_name` to import alongside), and never touches `.env`, `config/`, or
  `data/`. Only fixed member names are read from the zip (no member-derived
  write paths → no Zip-Slip surface).
- **Graceful provider degradation**: provider names the new host can't resolve
  are kept (the router already skips unavailable providers at runtime) and
  surfaced as a warning. The result repeats the **fork warning** — the two
  identities diverge from this point.

### Notes
- Tests (now 14 in `tests/test_portable.py`): round-trip preserves identity +
  empty pending queue, clobber attempt 409s, a full-backup zip is rejected as
  wrong type, **planted secret in a hand-crafted bundle → 409 with no profile
  dir created**, host fields re-sanitized on import, unknown provider warns but
  imports. Gate: ruff + mypy + 476 pytest + 21 vitest.

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
