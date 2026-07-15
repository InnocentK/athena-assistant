# Athena Assistant

A **local-first AI assistant**. Athena runs as a self-hosted FastAPI web app
(dark-theme chat UI) and as a one-shot CLI (`athena "..."`), routing your
prompts through configurable AI providers (CLI- and API-backed). All config,
memory, and profile data live in plain local files — no cloud database, no auth
layer. Designed to run in Docker on modest hardware.

Features include multi-profile support, a YAML-backed memory system with a
review queue, an allowlisted file browser, optional CalDAV / CardDAV / Nextcloud
integrations (read-mostly, disabled by default), provider latency diagnostics,
and editable settings.

## Quick start

```bash
# 1. Code + virtualenv
git clone <your-repo-url> athena-assistant && cd athena-assistant
python3 -m venv .venv && source .venv/bin/activate

# 2. Dependencies
pip install -r requirements.txt

# 3. Environment (set APP_ENV and ACTIVE_PROFILE at minimum)
cp .env.example .env

# 4. Run the web app at http://localhost:8000
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Full setup (Docker, profiles, validation) is in
[docs/INSTALLATION.md](docs/INSTALLATION.md).

## CLI

Use the CLI with no install:

```bash
python -m cli "What's the status of X?"
```

Or install the `athena` command (after installing requirements):

```bash
pip install -e .

athena "What's the status of X?"
athena ask "What's the status of X?"     # `ask` is an alias of the bare prompt
athena --list-providers                  # provider availability + effective transport
```

Useful flags: `--profile`, `--mode`, `--provider`, `--no-memory`,
`--diagnostics` (per-provider timing on stderr), `-q`/`--quiet`. Stdout is the
answer only, so it pipes cleanly; status and diagnostics go to stderr.

> If `athena` is "command not found" after install, its scripts directory
> (e.g. `~/.local/bin`) may not be on your PATH — add it, or use
> `python -m cli`. See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Documentation

Full index: [docs/README.md](docs/README.md). Highlights:

| Doc | What's in it |
|---|---|
| [docs/INSTALLATION.md](docs/INSTALLATION.md) | First-run setup, Docker, profiles |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Env, `config/*.yaml`, profiles, routing, provider transports, integrations |
| [docs/VALIDATION.md](docs/VALIDATION.md) | Quick smoke checks for a running instance |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | CLI import/PATH errors, provider availability, disabled integrations |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Component map and design decisions |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) · [docs/BACKUP.md](docs/BACKUP.md) | Operations · backup/restore |
| [docs/SECURITY.md](docs/SECURITY.md) | What Athena protects and how |
| [docs/TESTING.md](docs/TESTING.md) · [docs/TASKFILE.md](docs/TASKFILE.md) | Test suite · `task` commands |
| [CHANGELOG.md](CHANGELOG.md) | Release / milestone history |
| [CLAUDE.md](CLAUDE.md) · [docs/INVARIANTS.md](docs/INVARIANTS.md) | Contributor/agent guide · do-not-break contract |

Interactive API reference is served at `/docs` (Swagger UI); `/health` reports
the running app version and active profile.

## Project layout

```
main.py                  FastAPI app, all routes, lifespan init
core/                    config, YAML loader, logger
providers/               ProviderRouter + adapters (claude, gemini, chatgpt, grok, ollama, hermes)
cli/                     one-shot CLI (python -m cli / athena)
memory/  saved/  files/  YAML memory, saved items, allowlisted file I/O
diagnostics/             provider latency trace (measure-only)
caldav_integration/  carddav_integration/  nextcloud_integration/  dav_io/  dav_status/
backup/  audit/          export/restore, JSON-lines ops audit
config/  profiles/        YAML config and per-profile data
templates/  static/       chat UI (Jinja2 + vanilla JS/CSS)
tests/                   pytest suite
```

## Testing

```bash
source .venv/bin/activate
pytest                 # or: task test:run
```

See [docs/TESTING.md](docs/TESTING.md). All provider/network calls are mocked —
no API keys needed to run the suite.

## Contributing

Athena is built milestone by milestone; see [CHANGELOG.md](CHANGELOG.md) for the
history and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design.
