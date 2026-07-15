# Installation & First-Run Setup

This guide gets Athena running locally — both the web server and the `athena`
CLI. For configuration details (providers, routing, integrations) see
[CONFIGURATION.md](CONFIGURATION.md); for common problems see
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Prerequisites

- Python 3.10 or later, and `pip`
- (Optional) Docker + Docker Compose for containerised runs
- (Optional) [Taskfile](https://taskfile.dev) as a task runner

## 1. Get the code and create a virtualenv

```bash
git clone <your-repo-url> athena-assistant
cd athena-assistant

python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows
```

## 2. Install dependencies

`requirements.txt` is the single source of truth for runtime dependencies:

```bash
pip install -r requirements.txt
```

## 3. Configure environment

```bash
cp .env.example .env
# Edit .env — at minimum:
#   APP_ENV=development
#   ACTIVE_PROFILE=athena
```

Provider credentials and transport selection also live in `.env`. See
[CONFIGURATION.md](CONFIGURATION.md).

## 4. Run the web server

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
# or, with Taskfile:
task run
```

Open `http://localhost:8000`. Interactive API docs are at `/docs`; a health
check is at `/health`.

## 5. Install the `athena` CLI (optional)

The one-shot CLI can be used with no install via `python -m cli "..."`. To get
an `athena` command on your PATH, do an editable install **after** installing
requirements:

```bash
pip install -r requirements.txt
pip install -e .
```

Verify (these are the exact commands the install is tested against):

```bash
athena --list-providers
athena "What's the status of X?"
athena ask "What's the status of X?"     # `ask` is an alias of the bare prompt
```

`athena --list-providers` prints the provider table and exits 0. A prompt with
no available providers exits 1 with a clean error on stderr (stdout stays the
answer only) — that still proves the install works.

> **If `athena` is "command not found":** pip installs console scripts into a
> Python scripts directory (e.g. `~/.local/bin`) that may not be on your PATH.
> Either add that directory to PATH or use the no-install equivalent
> `python -m cli "..."`. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Running with Docker

```bash
task up        # docker compose up --build -d
task down      # stop
```

The container runs `uvicorn` with a single worker by default (suitable for
Raspberry Pi / low-power hosts).

## Creating a second profile

Profiles live under `profiles/<name>/`. Copy the `athena` profile directory,
edit `profile.yaml`, and select it with `ACTIVE_PROFILE=<name>` (env) or the
CLI `--profile <name>` flag. See [CONFIGURATION.md](CONFIGURATION.md).

## Validate your setup

[VALIDATION.md](VALIDATION.md) has quick smoke checks for a running instance
(health, chat, providers, backup); `task test:run` is the authoritative
regression gate.
