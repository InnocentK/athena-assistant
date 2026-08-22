# CLAUDE.md — Athena Assistant (agent handoff)

Read this before touching any code. This is the durable operating guide; it is
deliberately kept small. Volatile detail lives elsewhere:

- **Release history / what each milestone did** → [`CHANGELOG.md`](CHANGELOG.md)
- **"Do not break these" mechanisms & safety invariants** → [`docs/INVARIANTS.md`](docs/INVARIANTS.md)
- **Architecture & design** → [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- **All docs index** → [`docs/README.md`](docs/README.md)

> This file is canonical. `AGENTS.md` points here for tools that look for it.
> A copy of the parent-dir handoff is a pointer stub — edit *this* file.

---

## Project overview

Athena is a **local-first AI assistant**: Python 3.10+ / FastAPI, a dark-theme
browser chat UI, and a one-shot CLI (`athena "..."` / `python -m cli "..."`).
All config, memory, and profile data are plain local YAML files — no cloud
database, no auth layer. Designed to run in Docker on modest hardware.

**Status:** run `task test:run` for the live test count; `/health` reports the
running version. The roadmap (below) tracks what's shipped vs open. Do not
hardcode the version or test count into prose — they drift.

## How milestone work is done (the loop — maintain it)

Every change ships as a narrow milestone following this exact loop:

1. **Plan/spec → explicit approval.** Never write code before the plan is
   approved. Do not start a milestone until asked.
2. **Read** all files you plan to touch before writing anything.
3. **Implement** in the narrowest set of files. Reuse existing
   architecture/patterns; no scope creep.
4. **Gate: lint + types + tests** — `task ci` must pass (`ruff check` +
   `mypy .` + editable install + `pytest`), or run them individually
   (`task lint`, `task typecheck`, `task test:run`). All prior tests must still
   pass; add a targeted, fully-mocked regression test for the change (no real
   CLIs/keys/network in the suite).
5. **Docs** — update `CHANGELOG.md`, `docs/TESTING.md` (if tests were added),
   any affected doc, and — on a code release — bump **`core/version.py`**
   (the single version source; see below). Add any new "do not break" rule to
   `docs/INVARIANTS.md`.
6. **Commit / package** — the project is **git-tracked** (M26.23; `.gitignore`
   already excludes `.env`, `.venv/`, `node_modules/`, `data/`, logs, etc.).
   Commits are the record of change. **Only commit when asked** (the
   commit-when-asked norm still holds). For a handoff *zip* instead, exclude
   `.venv/`, `__pycache__/`, `.git/`, `node_modules/`, `logs/`, `audit/*.log`
   (keep `audit/` **source**), `data/exports/`, `data/carddav_staged/`,
   `data/restore_staging/`.
7. **Stop** — report files changed / test result / version; wait for the next
   approval.

### Review cadence (M29.7 rule — reviews are scheduled, not optional)

Fresh-eyes reviews happen on THREE triggers, whichever fires first — chosen to
track *unreviewed change volume*, not version arithmetic:

1. **Before any major version bump (X.0.0):** a FULL review is a mandatory
   release gate — all six lenses (correctness, security, concurrency,
   cross-surface AND cross-adapter consistency, test quality, agent
   ergonomics) over everything
   unreviewed, plus a docs sweep and a coverage re-measure.
2. **At each epic close** (end of a minor series, before the next epic
   starts): a scoped review of that epic's code — correctness, security, and
   cross-surface consistency at minimum.
3. **After any autonomous batch of >=5 milestones** (overnight/pre-approved
   runs): the batch's output gets the scoped review before new feature work.

Every review: findings exit through exactly one of three buckets — **fix**
(a scoped follow-up milestone), **defer** (an actionable entry with a trigger
condition in Later/unscheduled below), or **bless** (an INVARIANTS/docs note
that the behavior is intended). A lens that finds nothing states what it
checked. Reports are archived in `docs/history/` (see REVIEW-2026-07 and
REVIEW-3.0-2026-07 for the format).

**Version:** bump `core/version.py` (`__version__`) — the ONLY bump site
(M26.17). `main.py`, `pyproject.toml` (dynamic), and the health test all read
it. Details in `docs/INVARIANTS.md`.

## Guardrails

- **Truth over agreement — do not be a yes-man.** Prioritize correctness over
  making the user feel right. Challenge flawed assumptions and point out errors,
  especially when competing ideas can't both be good. Ground every conclusion in
  evidence — read the code, run it, cite the test — which this repo rewards:
  several fixes (e.g. the M26.1 stale-cache and M26.4 packaging bugs) were only
  correctly diagnosed by **reproducing**, not assuming. When evidence is
  insufficient, say **"I don't know"** rather than inventing an answer; don't
  guess confidently. Unsupported confidence is worse than admitting uncertainty
  — confident guessing is the worst outcome. In short: *tell the truth, ground
  it in evidence, and if you can't support it with evidence, say you don't know.*
- **Read `docs/INVARIANTS.md` before editing a subsystem** — it lists the
  mechanisms that must not be reverted (concurrency wrapping, write-safety
  guards, provider bounding, ICS formatting, UI correctness, CLI logging, etc.),
  each with its enforcing test.
- Add targeted mocked tests; keep the suite green.
- Do not introduce heavyweight dependencies without a good reason.
- Flag-bearing CLI features don't fit the repo's named-var Taskfile convention —
  skip a Taskfile task for those.
- Guiding principle (from live testing): some latency is normal for CLI-backed
  providers. **Measure first, then UX feedback, then optimize only if the data
  shows a problem** — this is why diagnostics (M22) precede the UI/CLI status
  work (M24/M25).

## Files to read first

| File | Why |
|---|---|
| `main.py` | App assembly + state: lifespan, `_require_*`, shared helpers, `GET /`, router includes |
| `app/routers/<domain>.py` | The actual route handlers (edit these to change an endpoint); reach state via `main.` — see INVARIANTS "router split" |
| `app/models.py` | Pydantic request/response models |
| `core/config.py` | `APP_ROOT`, Settings, path helpers — used everywhere |
| `providers/router.py` | `ProviderRouter.route()` — core orchestration |
| `providers/base.py` + `providers/ollama.py` / `providers/claude.py` | Adapter contract + API and CLI patterns |
| `memory/manager.py` | YAML-backed memory + pending review queue |
| `profiles/athena/profile.yaml` | Active profile structure |
| `tests/conftest.py` | Test fixtures — read before writing tests |
| `docs/INVARIANTS.md` | The "do not break these" contract |
| `docs/ARCHITECTURE.md` | Component map & design decisions |
| `Taskfile.yml` | All project commands (`task --list`) |

## App structure (map)

```
main.py                     FastAPI app assembly + state layer (lifespan,
                            _require_*, shared helpers, GET /; includes routers)
app/models.py               Pydantic request/response models (M26.18)
app/routers/<domain>.py     one APIRouter per domain (M26.18) — handlers reach
                            main state via `main.` after `import main`
core/{config,loader,logger} APP_ROOT/Settings, YAML I/O, logging
core/chat_turn.py           shared turn assembly + memory/history cores (M29.0/.1)
history/manager.py          per-profile JSONL conversation store (M29.1)
core/version.py             __version__ — the single bump site
core/urlguard.py            DAV same-origin guard (M26.13)
providers/                  router.py + adapters (claude/gemini/chatgpt/grok/ollama/hermes/chatgpt_cli)
cli/                        athena CLI: one-shot + REPL + history + doctor (M29.2/.6, M28.6)
memory/ · saved/ · files/   YAML memory + saved items + allowlisted file access
caldav_integration/ · carddav_integration/ · nextcloud_integration/   NETWORK clients
dav_io/                     LOCAL ICS/VCF parse/format/conflicts (no network)
dav_status/store.py         in-memory DAV health ledger (thread-safe singleton)
diagnostics/store.py        provider latency ledger (measure-only, M22)
backup/manager.py           export zip+manifest, diff, staged restore
audit/ops_audit.py          JSON-lines ops audit
config/ · profiles/         YAML config + active profile (memory subdirs)
templates/ · static/        Jinja2 chat UI + CSS/JS
tests/                      pytest suite (run `task test:run`)
docs/                       see docs/README.md for the index
```

Naming convention inside single-module packages: `manager.py` = stateful CRUD
over local files, `store.py` = in-memory ledger/singleton, `client.py` =
network integration. Each package's `__init__.py` says what it owns, what it
does *not*, and where its tests live — read it first. Data/code look-alikes:
`saved/` is code, `profiles/<name>/saved/` is that profile's data; `config/`
is user-editable YAML, `core/config.py` is the loader. This map and the tree
in `docs/ARCHITECTURE.md` mirror each other — update both together, and
record every shipped milestone in `docs/specs/README.md` (the M29.7 review
found 13 unlisted specs — do not let that recur).

## Roadmap

**Shipped:** M0–M26 (core through editable settings) + the post-2.6.0 fix series
M26.1–M26.4 + the post-review fix series M26.5–M26.10 (concurrency, CLI logging,
write-safety, provider robustness, calendar/DAV correctness, web UI correctness)
+ M26.11 (docs & handoff consolidation) + M26.12–M26.18 (DAV timeouts, DAV SSRF
guard, file-read robustness, Nextcloud/XML correctness, thread-safety, docs &
single-`__version__` + SessionStart hook, `main.py` router split) + the tooling
batch M26.19–M26.22 (ruff lint + pinned deps, CI gate, mypy type gate, jsdom
frontend test harness). Full per-milestone detail is in `CHANGELOG.md`.

**Quality gates now in place** (run all via `task ci` + `task test:js`): ruff
(`task lint`), mypy (`task typecheck`), pytest (`task test:run`), vitest jsdom
(`task test:js`). The SessionStart hook reports lint+types+suite at session start.

**Shipped (continued) — the foundations batch M26.23–M26.26** (git init + first
commits, coverage floor, pip-audit + CVE fix → 2.6.25, pre-commit hooks) and the
feature run below. Specs for all shipped milestones are archived in `docs/specs/`.

**Shipped feature milestones (specs in `docs/specs/`):**

- **M26.27 — platform support & limitations docs.** *Shipped* (no bump): a
  "Running Athena on <platform>" support matrix (Mac tested / Linux expected /
  Windows CLI-adapter caveats / container API-transport-only / mobile via
  Tailscale-VPN, no native app) + a remote-access pointer. `docs/PLATFORMS.md`.
- **M26.28 — installable PWA (web UI).** *Shipped → 2.6.28*: manifest +
  version-scoped service worker (caches the static shell only, never dynamic/API)
  + icons; registration guarded so it degrades to an ordinary page off a secure
  context (HTTPS/localhost). Polish on the remote-access path, not a replacement.
  → `docs/specs/M26.28-pwa.md`
- **M27 — Live status & usage telemetry (epic).** **M27.0 *shipped* → 2.7.0**:
  live CLI status line via a measure-only `ProviderRouter.route(on_attempt=…)`
  callback. **M27.1 *shipped* → 2.7.1**: token usage on the web UI
  (`buildUsageText`) *and* athena-cli (`build_cli_usage`), content-free counts on
  `ProviderCallRecord.usage`, captured for API transports (`extract_openai_usage`).
  *Deferred follow-up:* Claude-CLI usage via `--output-format json` (changes the
  primary provider's output path; can't be validated from the mocked suite — CLI
  transports report "unavailable" for now). → `docs/specs/M27-live-status-and-usage.md`
- **M28 — Portable Profiles (epic) — *shipped*.** Snapshot (not sync) identity
  bundles (`backup/portable.py` + `app/routers/portable.py`). **M28.0 → 2.8.0**:
  allowlist-built, leak-guarded export with a preview/review step (per-entry
  `exclude_ids`; a striplist hit is a hard 409). **M28.1 → 2.8.1**: import that
  re-enforces the same allowlist + leak scan on incoming bundles, never
  clobbers an existing profile / `.env` / `config/`, warns on unresolvable
  provider names, and repeats the fork warning.
  → `docs/specs/M28-portable-profiles.md` + `docs/PORTABLE-PROFILES.md`

**Upcoming — agreed direction to 3.0 (spec each before implementing; the loop
still applies):**

*The 2.8.z patch batch — small, independent mini-milestones, done BEFORE M29:*

- **M28.2 — Claude-CLI token usage** (→ 2.8.2) — *shipped.* Feature-detected
  JSON mode (`claude --help` probe, cached) with defensive envelope parsing;
  every deviation degrades to plain text. **USER TODO: validate against the
  real CLI** — `claude -p "Say hi" --output-format json` should show `result`
  + `usage` keys. → `docs/specs/M28.2-claude-cli-usage.md`
- **M28.3 — remote-access doc** (docs only, no bump) — *shipped.*
  `docs/REMOTE-ACCESS.md`: Tailscale/VPN + reverse-proxy-TLS how-tos,
  anti-patterns, verification. No code; no auth layer in Athena, ever.
- **M28.4 — mobile-responsive UI pass** (→ 2.8.4) — *shipped* (renumbered:
  smallest, done first). Full-width panels on phones, 16px input (no iOS
  focus-zoom), `100dvh`, safe-area insets + `viewport-fit=cover`. **USER TODO:
  eyeball on the phone.** → `docs/specs/M28.4-mobile-ui-pass.md`
- **M28.5 — profile switcher** (→ 2.8.5) — *shipped.* `GET /profiles` +
  `POST /profiles/activate` (validated, ops-audited, never touches `.env`) +
  settings-panel dropdown; resolution order override > switch-file > env >
  default (see INVARIANTS). → `docs/specs/M28.5-profile-switcher.md`
- **M28.6 — `athena doctor`** (→ 2.8.6) — *shipped.* Preflight report
  (config/filesystem only, NO network, never prints secret values): versions,
  key names set/not, vendor CLIs, profile resolution, dir writability, disk,
  DAV config. Exit 1 iff a check fails. → `docs/specs/M28.6-doctor.md`
  **The 2.8.z patch batch is complete — next up is M29.0.**

*M29 — Conversations (epic, 2.9.x) — in dependency order:*

- **M29.0 — shared chat-turn helper** (→ 2.9.0) — *shipped.*
  `core/chat_turn.py` (`build_turn_messages` / `system_prompt_from` /
  `extract_memory`); both surfaces rewired, execution models untouched.
  → `docs/specs/M29.0-chat-turn-helper.md`
- **M29.1 — persistent cross-session history** (→ 2.9.1) — *shipped.*
  `history/manager.py` (JSONL per conversation, id-guarded, lock-guarded),
  `/chat` records + returns `conversation_id`, `/history/*` endpoints, UI
  past-conversations restore. `profiles/*/history/` gitignored; portable
  bundles exclude it. → `docs/specs/M29.1-persistent-history.md`
- **M29.2 — CLI REPL** (→ 2.9.2) — *shipped.* Bare `athena` on a TTY →
  multi-turn session (`cli/repl.py`): success-only history replay, per-turn
  live status/usage, persisted to the M29.1 store, `/new` `/exit`. Non-TTY
  bare invocation stays exit-2. → `docs/specs/M29.2-cli-repl.md`
- **M29.3 — real file uploads** (→ 2.9.3) — *shipped.* `POST /files/upload`
  (sanitized names, streamed 10 MB cap, unique suffixes) into the allowlisted
  `data/uploads/`; 📎 UI attach inserts a path reference; reads stay
  allowlist-governed. → `docs/specs/M29.3-file-uploads.md`
- **M29.4 — conversation export** (→ 2.9.4) — *shipped.* Markdown export
  endpoint + UI button. → `docs/specs/M29.4-conversation-export.md`
- **M29.5 — Claude model attribution** (→ 2.9.5) — *shipped.* Model from
  `modelUsage`'s key; tests pin the REAL 2.1.206 envelope (validated live).
  → `docs/specs/M29.5-claude-model-attribution.md`
- **M29.6 — CLI history surfaces** (→ 2.9.6) — *shipped.* `athena history`
  list/show/export (variadic + `--all`), REPL `/list` + `/resume`
  (success-only replay), shared `render_markdown` on the store. **The M29
  Conversations epic is complete.** → `docs/specs/M29.6-cli-history.md`
- **M29.7 — pre-3.0 review & docs sweep** (no bump) — *shipped.* Six-lens
  review of M28.2–M29.6 (report: `docs/history/REVIEW-3.0-2026-07.md`), docs
  drift fixed everywhere, coverage floor 70→74, review-cadence rule codified
  above. → `docs/specs/M29.7-pre-3.0-review.md`
- **M29.8 — review remediation** (→ 2.9.8) — *shipped.* All eight
  post-errata FIX findings implemented, each test-pinned (incl. a real
  two-thread upload race test). → `docs/specs/M29.8-review-remediation.md`
- **M29.9 — remediation diff-review** (no bump) — *shipped.* M29.8 verified
  fix-by-fix; no new findings; two observations blessed (addendum in
  REVIEW-3.0). **M30 (→ 3.0.0) is clear to start** and embeds a scoped
  review of its own diff before the final version-bump commit — the
  pre-major review gate applied to code that IS the major.

- **M30 — Streaming** (→ **3.0.0**) — *shipped. Athena 3.0.0 is released.*
  Adapters `complete_stream()` (chatgpt w/ include_usage; ollama + grok-api
  without it — usage honest-absent), `route_stream()` on SHARED router
  internals (zero-chunk failures fall through; failures after chunks stop),
  `POST /chat/stream` SSE with `/chat`-identical semantics, web UI streams
  with unconditional buffered fallback before the first chunk, CLI streams
  stdout by default with `--no-stream` for strict scripts. Empty output is
  now a failure on EVERY adapter in both modes (the F14 norm, uniform).
  Pre-release scoped diff-review addendum in REVIEW-3.0 (the cadence rule
  applied to the major's own diff). The buffered `POST /chat` is unchanged —
  the 2.x compatibility surface. → `docs/specs/M30-streaming.md`

**Athena 3.0.0 — the roadmap target — is shipped.** Post-3.0 work starts
from the "Later / unscheduled" list below (spec first, as always).

*Post-3.0 milestones:*

- **M30.1 — Taskfile DX** (no bump) — *shipped.* `task setup`/`task install`
  now run the editable self-install (the `athena` command + package mapping);
  new `task update` (post-pull one-shot) and `task doctor`; TASKFILE.md
  backfilled (M26.19–26.26 tasks were undocumented); TROUBLESHOOTING documents
  the stale-editable-install failure observed live after 3.0.0.
  → `docs/specs/M30.1-taskfile-dx.md`
- **M30.2 — green mypy gate + CalDAV ETag fix** (→ 3.0.1) — *shipped.*
  `mypy .` had exited 1 for several milestones (pipe-masked; erratum in
  REVIEW-3.0). 7 precise ignores for caldav's `__getattr__ -> object`
  lazy-loader artifact (load-bearing — see INVARIANTS) + 1 REAL fix mypy was
  pointing at: `caldav.dav` doesn't exist in caldav 3.x, so etags silently
  recorded as `""`; GetEtag now imports from `caldav.elements.dav`
  (regression-pinned). → `docs/specs/M30.2-mypy-gate-fix.md`
- **M30.3 — neutral cwd for CLI provider subprocesses** (→ 3.0.2) —
  *shipped.* Vendor CLIs discover project agent config by walking up from
  cwd; `athena` run inside any repo leaked that repo's CLAUDE.md/hooks into
  chats (observed live: hook ran the test suite per message). All adapter
  subprocesses (probes included) now run from `neutral_cwd()`; user-global
  vendor config still applies. → `docs/specs/M30.3-neutral-cwd.md`

**Agreed direction (user-approved 2026-07-16, spec each before implementing):**

*Remainder of 3.0.z — bug-fix window.* Fixes for issues found in the user's
post-release testing, each its own small milestone. Approved queue from the
2026-07-17 desktop triage: **M30.4** uploads visibility + attach UX (→
3.0.3, *shipped*); **M30.5** attachment semantics — inline small TEXT
attachments server-side, provider-agnostic, images stay reference-only (→
3.0.4, *shipped*); **M30.6** voice controls — Settings "Voice" section persisted
per-browser via localStorage: speak-responses toggle DEFAULT OFF, voice
picker from system voices, transcript auto-send toggle DEFAULT OFF,
continuous-mic mode (→ 3.0.5, *shipped*; the scaffolding M31.0 reuses);
**M30.7** claude transport tool restriction — `--disallowedTools` for a
pure-LLM chat (→ 3.0.6, *shipped*). Pt 2 queue (2026-07-17): **M30.8** voice
settings polish — dropdown shrink fix + Test-voice button (→ 3.0.7,
*shipped*); **M30.9** temporal context — date/time+TZ appended to the
provider-bound system prompt (→ 3.0.8, *shipped*). **Both triage queues are
complete**, the mobile pass is done (M28.4 layout verified live; PWA needs
the documented HTTPS step — no code), and **M30.10** (no bump) ran the
cadence-rule scoped review of the whole wave: FIX none / DEFER none / BLESS
five (`docs/history/REVIEW-3.0.z-2026-07.md`).

*M31 — Voice epic (3.1.y).* Live-voice research (products, protocols,
pricing, self-hosted pipelines) is summarized in this entry + the M31.0
spec; the decision record is this entry.

- **M31.0 — Conversation mode** (→ **3.1.0, SHIPPED** under the 2026-07-17
  overnight pre-approval; spec + amendments A1–A4 in
  `docs/specs/M31.0-conversation-mode.md`): browser-only upgrade of the M5
  voice + M30 streaming — sentence-by-sentence TTS as SSE chunks arrive
  (`voice.enqueue()`, dumb splitter, tail at done, reconcile never spoken),
  a hands-free listen loop (armed ONLY by a mic click; auto-restarts
  recognition when the last utterance ends; stops on mic-off/typed
  send/STT error/hidden tab/toggle-off), and barge-in (synthesis cancels
  before the mic opens, on transcript, on send — speech is a VIEW of the
  answer, never the answer). Settings toggle default OFF; implies
  speak+auto-send for the session. No backend change, no new deps, no
  per-minute cost. KNOWN LIMITS stated in PLATFORMS.md: Web Speech STT is
  Chromium/Safari (not Firefox); CLI-transport providers answer whole
  (voice waits — same honest degrade as M30 text streaming); the mic needs
  a secure context (HTTPS over Tailscale — REMOTE-ACCESS.md). M31.0 is
  deliberately the CHEAP PROBE — **the probe is now running: live with it
  before building more.**
- **M31.1 — Mobile voice enablement** (→ **3.1.1, SHIPPED**; spec
  `docs/specs/M31.1-mobile-voice.md`): the user's probe target is the
  phone. M28.4's narrow-screen CSS hid `#ptt-btn` — the only control that
  can arm the loop — so it now slims instead of disappearing (pinned:
  the media block may restyle the mic, never hide it). The HTTPS half is
  operator-side (`tailscale serve` per REMOTE-ACCESS.md; phones grant no
  mic over bare http). Phone realities documented in PLATFORMS: app-switch/
  screen-lock disarms the loop by design; iOS may need one Test-voice tap.
- **M31.2 — Audible turn indicator** (→ **3.1.2, SHIPPED**; spec
  `docs/specs/M31.2-turn-earcon.md`): the probe's first lived-experience
  refinement — a Web Audio rising blip when the loop AUTO-reopens the mic
  (never on manual clicks), AudioContext unlocked by the same arming
  click. Decision recorded: turn cues are transport-independent and carry
  into Athena Live; the epic itself stays probe-gated.
- **M31.3 — Save reply as file** (→ **3.1.3, SHIPPED**; spec
  `docs/specs/M31.3-save-reply.md`): probe finding #2 — "get me notes as
  a markdown file" can't be done BY a provider (pure-LLM policy, M30.7,
  deliberate). A per-reply Save button posts the reply through the
  EXISTING /files/upload envelope (no new write surface, user-initiated
  by construction). Voice-commanded saving stays in the Later
  tool-calling safety framing.
- **M31.4 — Save destinations + derived filenames** (→ **3.1.4,
  SHIPPED**; spec `docs/specs/M31.4-save-destinations.md`): the user's
  same-day review of M31.3. Filenames derive from the reply (heading →
  slug; timestamp only as fallback); server copies land in `data/saved/`
  via a FIXED dest enum on the one upload envelope (never a
  client-controlled path); a client-side device-download option; both
  governed by Settings → "Saving replies" (browser-local, server ON /
  device OFF defaults).
- **M31.5+ — Athena Live (self-hosted cascaded voice)** — only if the M31.0
  probe earns it; staged mini-milestones, spec'd separately: (a) local Piper/
  Kokoro TTS endpoint (better voices than SpeechSynthesis, standalone win);
  (b) WebSocket audio path on FastAPI; (c) server STT via faster-whisper
  (CPU-class, small/int8) + VAD; (d) barge-in. Architecture rule: the voice
  layer WRAPS the existing text loop — `route_stream()` + history + memory
  untouched (the kyutai-labs/unmute pattern, scaled to modest hardware).
  Provider-agnostic, fully local, ~1–2.5s turns on NUC/Mac-class CPUs.
- Vendor realtime bridges are Later/unscheduled (below), not part of M31
  unless explicitly promoted.

**Later / unscheduled:** per-provider **enable/disable toggles in Settings**
(writes providers.yaml — needs router re-init semantics; use case observed
live: an available-but-broken CLI provider); a **failure cooldown /
circuit-breaker** for repeatedly failing providers (observed: ~28–52s wasted
per message when a broken gemini preceded the answering provider); **probe
`stream_options={"include_usage"}` support on grok/ollama** (the web UI
streams by default since M30, so those turns show "Tokens: unavailable" —
honest but a UX regression vs buffered 2.x); vendor realtime-voice bridge (OpenAI
gpt-realtime / Gemini Live / Grok Voice Agent as an explicit opt-in voice
transport: Athena mints ephemeral client tokens, the browser connects
directly to the vendor, transcripts are recorded into history afterward —
sub-second full-duplex but cloud-only, per-minute economics, and it bypasses
the provider router; revisit only if the M31 path's latency ever genuinely
pinches — Gemini Live's free tier makes the experiment cheap); Ollama
phase 2 (multi-model, embeddings, tools);
generic OpenAI-compatible local-provider abstraction; saved-items surfacing
(`athena saved …`) + non-file saved-search targets; relevance-based memory
retrieval (inject only relevant entries per turn — embeddings via Ollama when
available, keyword fallback; measure prompt sizes first); real tool-calling for
API transports (OpenAI-SDK function calling so API providers can invoke
calendar/contacts/files; needs its own safety framing — write actions gated as
the UI gates them); update checker / `athena update` (blocked on the repo
having a git remote); richer history export (zip bundles of many
conversations, an export-all web endpoint, date-range selection — the
deliberate scope cut from M29.6's stdout-only variadic CLI export; revisit
only if plain-Markdown-to-stdout ever pinches); deterministic conversation
ordering (REVIEW-3.0 F3: two conversations created in the same second tie in
newest-first listings and the random id suffix decides — display-only, no
code path decides on ordering; fix would be sub-second id stamps or a
last-activity sort; revisit if listing order ever visibly misleads); consolidate shared test
fakes (REVIEW-3.0 F8: `_FakeRouter`/scripted-stdin helpers are imported
across test modules from test_cli/test_repl — move them to conftest.py or
tests/helpers when they next change or gain another importer).

## Suggested first actions

0. A **SessionStart hook** (`.claude/settings.json` →
   `scripts/session-start-check.sh`) already ran when this session opened and
   printed the baseline: deps status + the suite result (~30s when green,
   fail-fast when red). **If it reported failures, they are pre-existing —
   record them before changing anything.** If you don't see its output (other
   tooling, hooks disabled), do step 1 manually.
1. `source .venv/bin/activate && task test:run` — confirm the suite is green
   before changing anything.
2. Skim `docs/INVARIANTS.md` for the subsystem you're about to touch.
3. Do not write milestone code until its plan/spec is explicitly approved.
   Packaging + the `athena` command already exist (M17) — don't re-add them.
