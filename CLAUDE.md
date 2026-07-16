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

**Version:** bump `core/version.py` (`__version__`) — the ONLY bump site
(M26.17). `main.py`, `pyproject.toml` (dynamic), and the health test all read
it. Details in `docs/INVARIANTS.md`.

## Guardrails

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
core/version.py             __version__ — the single bump site
core/urlguard.py            DAV same-origin guard (M26.13)
providers/                  router.py + adapters (claude/gemini/chatgpt/grok/ollama/hermes/chatgpt_cli)
cli/                        one-shot CLI (main.py, status.py) — python -m cli / athena
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
in `docs/ARCHITECTURE.md` mirror each other — update both together.

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
- **M28.4 — profile switcher** (→ 2.8.4). Activate a different profile at
  runtime (endpoint + UI dropdown) instead of editing `ACTIVE_PROFILE` +
  restart. Completes M28: imported portable profiles become usable in-app.
- **M28.5 — `athena doctor`** (→ 2.8.5). Preflight diagnostics CLI: `.env` keys
  present, vendor CLIs found/logged-in, DAV reachability, versions, disk. The
  executable form of the M26.27 platform matrix.
- **M28.6 — mobile-responsive UI pass** (→ 2.8.6). CSS-only responsive layout
  for the phone-over-Tailscale + PWA (M26.28) path. No logic changes.

*M29 — Conversations (epic, 2.9.x) — in dependency order:*

- **M29.0 — shared chat-turn helper.** ONE code path assembling a turn
  (history, system prompt, memory extraction) used by both the web `/chat`
  handler and the CLI. Prerequisite for everything below.
- **M29.1 — persistent cross-session history.** Conversations survive restarts
  as plain local files. Chat history stays OUT of portable bundles (M28
  striplist — already an invariant).
- **M29.2 — CLI REPL.** `athena` with no prompt → interactive multi-turn
  session (leans on M27 live status + M29.0/29.1).
- **M29.3 — real file uploads.** Attach a file to a turn; policed by the
  existing files allowlist.
- **M29.4 — conversation export.** Markdown export of a conversation
  (depends on M29.1).

*M30 — Streaming (epic, → 3.0.0).* SSE per-provider streaming for API
transports; streamed rendering in the web UI; streamed stdout in the CLI. CLI
transports degrade gracefully to today's one-shot behaviour (same honest-
fallback pattern as token usage). This changes the `/chat` response contract —
the reason it IS the major bump.

**Later / unscheduled:** Ollama phase 2 (multi-model, embeddings, tools);
generic OpenAI-compatible local-provider abstraction; saved-items surfacing
(`athena saved …`) + non-file saved-search targets; relevance-based memory
retrieval (inject only relevant entries per turn — embeddings via Ollama when
available, keyword fallback; measure prompt sizes first); real tool-calling for
API transports (OpenAI-SDK function calling so API providers can invoke
calendar/contacts/files; needs its own safety framing — write actions gated as
the UI gates them); update checker / `athena update` (blocked on the repo
having a git remote).

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
