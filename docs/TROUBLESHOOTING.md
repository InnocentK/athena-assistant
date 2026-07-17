# Troubleshooting

Common issues and fixes. See also [INSTALLATION.md](INSTALLATION.md) and
[CONFIGURATION.md](CONFIGURATION.md).

## CLI: `failed to load Athena modules: No module named '<package>'`

The `athena` command comes from an editable install (`pip install -e .`),
whose package mapping is a **snapshot from install time**. Two causes, most
common first:

1. **Your venv's install is stale or missing** (the usual case — observed in
   the wild right after 3.0.0 shipped). Installing `requirements.txt` alone
   does NOT install Athena itself, and an editable install made before a
   milestone that *added* a top-level package doesn't know about the new one.
   Fix — refresh the install:

   ```bash
   task install        # deps + editable install (M30.1), or manually:
   pip install -e .
   ```

2. **A stale package list in the repo** (maintainer error): every runtime
   package must be declared in `pyproject.toml` under
   `[tool.setuptools] packages` (the M26.4 invariant — this error on a FRESH
   `pip install -e .` means the list is missing one).

If you're working from a checkout, the no-install path `python -m cli "..."`
always works (it runs from the project directory and doesn't depend on
packaging).

## CLI: `athena: command not found`

`pip install -e .` puts the `athena` console script in a Python scripts
directory that may not be on your PATH (pip prints a warning like
`installed in '~/.local/bin' which is not on PATH`). Options:

- Add that directory to your PATH (e.g. `export PATH="$HOME/.local/bin:$PATH"`).
- Install inside an activated virtualenv (its `bin/` is on PATH while active).
- Use `python -m cli "..."` instead — no PATH changes needed.

## Answers sound like a coding agent for the directory I'm in (or are very slow there)

Seen on versions **before 3.0.2** when running `athena` from inside a project
directory: CLI provider subprocesses inherited your shell's cwd, and vendor
CLIs (claude, gemini, …) discover project agent config by walking up from it —
so the provider loaded that project's `CLAUDE.md`/hooks, ran any SessionStart
hook per message (this is the slowness), and answered in that project's agent
persona instead of as Athena.

Fixed in 3.0.2: adapter subprocesses run from a neutral directory (the system
temp dir). On older versions, run `athena` from a directory that isn't inside
a repo. Note the deliberate boundary: your user-global vendor config
(`~/.claude/` login/identity) still applies — that's how the CLI
authenticates, not project context.

## A provider shows "available" but answers fail (or vice versa)

Availability is a **config-based** check, not a guarantee of a working call:

- A `cli` provider is "available" when its binary is on PATH; the call can still
  fail (e.g. the CLI needs stdin, or isn't authenticated).
- An `api` provider is "available" when its key is configured (and the SDK is
  installed); the call can still fail on network/credentials.

Use `athena --list-providers` to see each provider's **effective transport** and
availability. For Grok, confirm the transport you expect: `GROK_TRANSPORT`
(env) → `providers.yaml` → default `cli`. If you set `XAI_API_KEY` but still see
`cli`, you haven't selected the `api` transport.

## Settings look read-only, or "Working…" never clears (after upgrading)

Almost always a **stale browser cache** of the old JS/CSS. Athena versions its
static asset URLs (`?v=<version>`) and sends a no-cache header, so this fixes
itself on the next load — but a tab opened before the upgrade may need one hard
refresh (Cmd/Ctrl-Shift-R).

## An integration endpoint returns 503

CalDAV / CardDAV / Nextcloud are **disabled by default**. While
`config/<name>.yaml` has `enabled: false`, their endpoints return `503` and no
connection is attempted. Set `enabled: true` and provide credentials in `.env`
to activate. See [CONFIGURATION.md](CONFIGURATION.md).

## The startup log shows a different version than I expected

The startup log reads `Profile loaded: <name> (app vX.Y.Z, profile schema vN)`.
The **app version** (also at `/health` and in Settings as "App version") is the
release version. The **profile schema version** is the profile file's format
version and is independent — they are not meant to match.

## `pip install` errors about system packages

On externally-managed Python environments, prefer a virtualenv. If you must
install into the system/user environment, pip may require
`--break-system-packages`. A virtualenv (`python3 -m venv .venv`) avoids this.

## The server starts but a profile won't load

Check `ACTIVE_PROFILE` matches a directory under `profiles/`, and that
`profiles/<name>/profile.yaml` exists and is valid YAML. `GET /health` reports
the active profile name.
