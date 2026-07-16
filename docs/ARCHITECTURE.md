# Athena Assistant — Architecture

## Overview

Athena is a local-first AI assistant platform. All persistent state lives in plain files on the host. There is no cloud dependency except the AI provider API calls you explicitly configure.

## Component Map

```
Browser (vanilla JS)                       athena / python -m cli
    ↕ HTTP (FastAPI / uvicorn)                 ↕ (no HTTP — same Python stack)
main.py  ← app assembly + state layer      cli/main.py + cli/status.py
    │   (lifespan, _require_*, shared helpers, GET /; includes the routers)
    │                                          cli/repl.py      interactive session (M29.2)
    │                                          cli/doctor.py    preflight checks (M28.6)
    │                                          cli/history_cmd.py  athena history … (M29.6)
    ├── app/models.py         Pydantic request/response models (M26.18)
    ├── app/routers/*.py      one APIRouter per domain: core, memory, saved,
    │                         voice, files, caldav, carddav, nextcloud, backup,
    │                         portable, history, dav_status — handlers reach
    │                         state via `main.` (M26.18)
    ├── core/config.py        APP_ROOT, Settings (active-profile resolution:
    │                         override > switch file > env > default, M28.5)
    ├── core/loader.py        YAML read/write helpers
    ├── core/logger.py        Shared structured logger
    ├── core/version.py       __version__ — the single bump site (M26.17)
    ├── core/urlguard.py      DAV same-origin guard (M26.13)
    ├── core/chat_turn.py     Shared turn assembly + memory/history cores —
    │                         ONE pipeline for web + CLI (M29.0/29.1)
    │
    ├── providers/router.py   Route chat messages to AI providers (instrumented → diagnostics/, M22)
    │   ├── claude.py         Claude CLI adapter
    │   ├── gemini.py         Gemini CLI adapter
    │   ├── grok.py           Grok adapter — CLI or API transport (M21)
    │   ├── chatgpt.py        OpenAI API adapter
    │   ├── ollama.py         Local Ollama adapter (OpenAI-compatible API, opt-in)
    │   ├── hermes.py         Hermes CLI provider (opt-in, M23)
    │   └── chatgpt_cli.py    ChatGPT CLI stub (not a live adapter — see chatgpt.py)
    │
    ├── memory/manager.py     YAML flat-file memory (per profile) + pending review queue
    ├── history/manager.py    Persistent conversations — append-only JSONL per
    │                         conversation, per profile; shared Markdown renderer (M29.1/.6)
    ├── saved/manager.py      Saved searches (file) + saved actions (prompts), per profile
    ├── voice/stubs.py        STT/TTS stub + upgrade docs
    ├── files/manager.py      Dynamic allowlist, search/read/write, audit (+ uploads → data/uploads/, M29.3)
    ├── diagnostics/store.py  Provider latency + token-usage trace (measure-only, M22/M27.1)
    ├── backup/manager.py     Export zip+manifest, dry-run diff, staged restore
    ├── backup/portable.py    Portable Profiles — allowlist-built, leak-guarded identity snapshots (M28)
    ├── audit/ops_audit.py    JSON-lines ops audit (destructive/operational events)
    │
    ├── caldav_integration/   CalDAV network client (read + task create)
    ├── carddav_integration/  CardDAV network client (read + staged merge)
    ├── nextcloud_integration/ Nextcloud WebDAV/OCS network client (read-only)
    ├── dav_io/               LOCAL ICS/VCF parse+format+conflict logic (no network)
    └── dav_status/store.py   In-memory DAV health ledger (thread-safe singleton)
```

> This tree and the "App structure (map)" in [`CLAUDE.md`](../CLAUDE.md) mirror
> each other — when a package is added or renamed, update **both**.

**Two entry points, one stack.** `main.py` (FastAPI/HTTP) and `cli/main.py` (`python -m cli`, Milestone 16) are independent front-ends that both drive the same `ProviderRouter` / `MemoryManager` / profile layer. The CLI imports no FastAPI and adds no routing logic of its own — it builds a single-turn message and calls the same router seam the `/chat` handler uses (`route_stream(...)` by default since M30, `route(...)` under `--no-stream`). The CLI is also installable as the `athena` console command via `pyproject.toml` (Milestone 17); `python -m cli` remains the no-install equivalent. Since M25 the CLI also surfaces a generic in-flight spinner and a one-line status summary (with an expanded `--diagnostics` breakdown) on **stderr** — built from the same M22 trace via `cli/status.py` and never touching stdout, which stays the answer only. Since M30, answer chunks print to stdout as they arrive (`drive_stream`) — the answer-only contract holds because the chunks ARE the answer.

## Key Design Decisions

**All state is local files.** Config in `config/*.yaml`, memory in `profiles/<name>/memory/*.yaml`, staged merges in `data/carddav_staged/`. No database required.

**Credentials in `.env` only.** No secrets in YAML. Integrations check env vars at init and raise a clear error if missing.

**Integrations disabled by default.** Each integration has a `config/<name>.yaml` with `enabled: false`. Flip to `true` + set credentials to activate. Server never errors on startup if an integration is disabled.

**Provider routing is profile-driven.** The active profile's `routing_mode` (quality_first / balanced / budget_first) selects the provider priority order from `config/providers.yaml`. Providers are tried in order; first success wins. The local Ollama provider (Milestone 15.5) is opt-in (`enabled: false` by default), runs an active ~1s health check in `is_available()`, and joins only the `budget_first` tier or runs as an explicit `preferred_provider` — it never auto-tops `balanced` or `quality_first`. Since M26.2, `list_providers()` reports each provider's **effective** transport (e.g. Grok's resolved `cli`/`api`) rather than the static `providers.yaml` `type`, so the Providers tab and `--list-providers` are truthful; availability stays config-based (no network probe). The app/release version is a single FastAPI source (logs, UI, `/health`), kept distinct from the profile's schema version.

**Memory auto-extraction is cautious.** All auto-extracted candidates go to a pending review queue. Nothing is saved directly — the user approves or discards via the UI or API.

**Saved items reuse existing engines.** Saved searches and saved actions (Milestone 18) are per-profile YAML under `profiles/<name>/saved/`. Running a saved search executes a local file search via `FileManager` — v1 supports `target: files` only (no web-search backend exists yet); running a saved action sends its prompt through `ProviderRouter` (no auto-extraction). Both add storage plus thin endpoints, not new search or routing logic.

**The browser UI is vanilla JS with a reusable panel pattern.** The Memory panel (M4), the read-only Settings panel (M19), and the History & Attachments panel (M20) share the same structure: a header button toggles a hidden tabbed overlay whose tabs render from existing data/endpoints with XSS-safe DOM (`textContent`/`createElement`). No framework or build step; one overlay panel is open at a time. The History panel's Conversation tab reflects the current in-memory session (no persistence), and its Files tab is a read-only browse of allowlisted files (no uploads) that, since M26.3, hides internal/operational artifacts (logs, audit, staging, backups, `*.log`/`.gitkeep`/`*.pyc`) by default via a backend `exclude_internal` flag on `/files/search`, with an explicit "Show internal/ops files" toggle — a view-level filter that leaves the allowlist and FileManager security unchanged. Since M24, `/chat` also forwards the (content-free) M22 `RequestTrace` on `ChatResponse.diagnostics`, and the UI renders a one-line summary plus (M24.5) a compact proportional provider timeline and an expandable details view from it — reconstructed at completion.

**Responses stream (M30 — the 3.0.0 contract).** Adapters that can deliver incrementally (chatgpt, ollama, grok's api transport) implement `complete_stream()` — a generator of text chunks ending in the final `ProviderResponse`; CLI-transport adapters answer whole and advertise `supports_streaming() = False`. `ProviderRouter.route_stream()` shares the exact attempt loop with `route()` (extracted internals — the routing logic is not forked) and yields `("chunk", text)` events then exactly one `("done", response)`: zero-chunk failures fall through to the next provider like `route()`, failures after emitted text stop the request, and non-streaming adapters degrade to one buffered chunk. `POST /chat/stream` delivers those events as SSE with `/chat`'s exact semantics (conversation ids, history recording, memory extraction, `_ROUTE_TIMEOUT` budget — the sync generator is stepped via `asyncio.to_thread` so the loop stays responsive, M26.5); the web UI streams into a growing bubble and **falls back to the unchanged buffered `/chat`** on any failure before the first chunk; the CLI prints chunks live (`--no-stream` restores buffered output for strict scripting).

**Editable settings are narrow and validated (M26).** `PATCH /profile` makes three behaviour-affecting profile fields editable from the Settings panel — system prompt, routing mode, preferred provider. It validates before any write, persists to `profile.yaml` (key order preserved via `save_yaml(sort_keys=False)`; YAML comments are not preserved), and updates the in-memory `_profile_data` in place so the next `/chat` uses it without a restart; the next CLI run reloads the same file. Providers, integrations, credentials, and memory remain read-only.

**CardDAV merge is human-gated.** Duplicate detection runs locally. `stage_merge` saves a proposal to disk. `commit_merge` is the only write path and requires an explicit API call with a valid `staged_merge_id`.

## Runtime Directory Layout

```
logs/          Application logs (stdout + file)
audit/         Write audit trail (file operations)
data/          Local data storage
  carddav_staged/   Staged CardDAV merge proposals
profiles/<name>/memory/   Per-profile memory YAML files
```

All runtime directories are excluded from git and populated at first run.

## Upgrade Paths (Stubbed)

| Feature | Current | Upgrade path |
|---------|---------|-------------|
| STT | Web Speech API (browser) | faster-whisper (see voice/stubs.py) |
| TTS | SpeechSynthesis (browser) | piper-tts (see voice/stubs.py) |
| Local LLM | Ollama adapter (`providers/ollama.py`, opt-in) | Multi-model auto-select, embeddings, tool-calling (future) |
| Web search | SearXNG (local) + pluggable fallbacks | config/search.yaml |

## Raspberry Pi / Low-Power Notes

- Use `--workers 1` (already default in Dockerfile CMD).
- Disable unused integrations to reduce startup time.
- Web Speech API STT/TTS runs in the browser — zero server load.
- Memory and file operations are YAML reads/writes — negligible overhead.
- CalDAV/CardDAV/Nextcloud calls are synchronous HTTP — not a bottleneck at single-user scale.
