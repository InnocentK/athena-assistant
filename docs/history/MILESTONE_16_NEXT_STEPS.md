# Milestone 16 — Athena CLI MVP: Implementation Brief

**Status:** Design only. Not yet implemented.
**Version target:** 1.5.0 → 1.6.0

---

## Goal

Add a text-only CLI entry point that lets a user chat with Athena directly in
a terminal, without starting the FastAPI server. The CLI reuses existing
orchestration (ProviderRouter, MemoryManager, profile loading) and adds no
duplicate business logic.

---

## Smallest Viable MVP Scope

1. `task cli` (or `python -m athena_cli`) starts an interactive text chat loop.
2. User can specify a profile and routing mode as CLI flags.
3. Each turn: read user input → call `ProviderRouter.route()` → print response.
4. `auto_extract` runs after each turn (same as the HTTP chat handler).
5. `Ctrl-C` or typing `exit`/`quit` ends the session cleanly.
6. Basic status output on startup: active profile, routing mode, available providers.
7. `--list-providers` flag prints provider availability and exits.

That is the full MVP. Everything else is deferred.

---

## Proposed CLI Architecture

### Entry point location

```
athena-assistant/
└── cli/
    ├── __init__.py
    └── main.py          ← CLI entry point
```

`cli/main.py` is the only new file with real logic. It is intentionally thin:
load config and profile, instantiate `ProviderRouter` and `MemoryManager`
(exactly as `main.py` does in the lifespan handler), then run a REPL loop.

### How it calls existing services

```
cli/main.py
  → core.config          (APP_ROOT, get_settings, active_profile_dir)
  → core.loader          (load_yaml)
  → core.logger          (logger)
  → providers.router     (ProviderRouter)   ← no changes needed
  → providers.base       (Message)          ← no changes needed
  → memory.manager       (MemoryManager)    ← no changes needed
  → audit.ops_audit      (write_ops_event)  ← optional, for session-start event
```

No HTTP layer is involved. No FastAPI imports. The CLI talks to service
classes directly.

### No refactor required

`ProviderRouter`, `MemoryManager`, and `core/config.py` are already
independent of FastAPI. They can be imported and used directly.
The only thing to verify before implementing: confirm that `ProviderRouter.__init__`
and `MemoryManager.__init__` have no side effects that assume a running ASGI app.
(Based on current code, they do not — both are plain Python classes.)

---

## Proposed Command Structure (MVP only)

```
python -m athena_cli [OPTIONS]

Options:
  --profile TEXT        Profile name to load (default: value of ACTIVE_PROFILE env var / "athena")
  --mode TEXT           Routing mode override: quality-first | balanced | budget-first
  --provider TEXT       Preferred provider override (passed into profile_config at runtime)
  --list-providers      Print provider availability table and exit
  --no-memory           Disable auto_extract for this session (memory reads still work)
  --help                Show help and exit

Interactive commands (typed during the chat loop):
  exit / quit / Ctrl-C  End the session
  /status               Print current profile, routing mode, last provider used
  /providers            Print provider availability (same as --list-providers)
  /memory               List all saved memories (brief)
```

Slash-commands are a simple `if user_input.startswith("/"):` check in the loop — no
framework needed.

### Taskfile task

```yaml
  cli:
    desc: "Start Athena CLI chat session (no server required)"
    cmds:
      - "{{.PYTHON}} -m athena_cli {{.CLI_ARGS}}"
```

### Optional: pyproject.toml entry point

If a `pyproject.toml` is added later, wire up:
```toml
[project.scripts]
athena = "athena_cli.main:main"
```
This is deferred — not required for the MVP.

---

## Key Integration Points

| Concern | How the CLI handles it |
|---|---|
| Profile loading | Same as `main.py` lifespan: `load_yaml(active_profile_dir() / "profile.yaml")` |
| Profile override | `--profile` flag sets `ACTIVE_PROFILE` env var before `get_settings()` is called (or pass profile name directly to path helpers) |
| Routing mode override | Patch `profile_config["routing"]["mode"]` in memory before calling `router.route()` |
| Provider override | Patch `profile_config["routing"]["preferred_provider"]` in memory |
| MemoryManager init | `MemoryManager(active_profile_dir(), profile_config)` — identical to HTTP startup |
| auto_extract | Call `memory.auto_extract(user_input, response.content)` after each turn |
| Conversation history | Maintain a local `list[Message]` in the REPL loop; pass full history to `router.route()` on each turn |
| System prompt | Read from `profile_config["system_prompt"]` — identical to HTTP handler |

---

## Required Refactors or Separations

**None required.** All needed classes are already importable without FastAPI.

One minor thing to watch: `core/logger.py` currently configures the root logger
when imported. In CLI mode this is fine — it will log to stderr by default.
If the CLI should be quieter by default, add a `--quiet` flag that sets
`LOG_LEVEL=WARNING` before logger init. This is not a refactor, just a flag.

---

## Risks and Open Questions

1. **Multi-turn context size** — The REPL accumulates the full conversation as a
   `list[Message]`. For very long sessions this grows unboundedly. For the MVP,
   this is acceptable. A `max_history_turns` config field can be added later.

2. **Blocking providers in a terminal** — `ProviderRouter.route()` is synchronous
   and may block for several seconds. In the terminal this is fine (single-threaded
   REPL). No async needed for MVP.

3. **Provider availability on first run** — If no providers are configured/available,
   the CLI should print a clear message and exit rather than entering the loop.
   Add a `router.list_providers()` check before starting the REPL.

4. **`get_settings()` is `@lru_cache`** — Overriding `ACTIVE_PROFILE` via `--profile`
   must happen before the first call to `get_settings()`. Set `os.environ["ACTIVE_PROFILE"]`
   at the top of `cli/main.py:main()` before any imports that trigger the cache.
   Alternatively, pass the profile name directly to `active_profile_dir()` via a
   small helper — avoids the env var mutation entirely and is cleaner.

5. **Windows compatibility** — The REPL uses `input()` which works on Windows.
   `Ctrl-C` raises `KeyboardInterrupt` which is caught. Should be fine.

---

## Recommended Implementation Order

1. Create `cli/__init__.py` (empty) and `cli/main.py` with argument parsing only
   (argparse or sys.argv — no new dependency).
2. Add profile + router + memory init (copy the pattern from `main.py` lifespan).
3. Add `--list-providers` flag and exit path.
4. Add the REPL loop: `input()` → `router.route()` → `print()`.
5. Wire `auto_extract` after each successful turn.
6. Add `/status` and `/providers` slash-commands.
7. Add `task cli` to `Taskfile.yml`.
8. Add tests: at minimum, test arg parsing, `--list-providers` output, and that
   the REPL calls `router.route()` with the correct message list.
9. Update `README.md` and `docs/RUN_AND_VALIDATE.md`.

---

## Explicitly Out of Scope for CLI v1

- Voice input/output (no push-to-talk, no TTS playback)
- TUI frameworks (no `textual`, `curses`, `rich` — plain `print()` only)
- Web UI parity (no file browser, no DAV status, no memory sidebar)
- Streaming responses (print full response after completion)
- Session persistence across runs (memory is persisted via MemoryManager, but
  conversation history is in-process only)
- Multi-profile switching mid-session
- Plugin/tool calling from the CLI (web search, calendar, etc.)
- Packaging as a standalone binary
- Docker-specific CLI entrypoint changes
