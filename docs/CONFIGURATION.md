# Configuration

Athena is configured through a small set of plain files. No cloud database.

- **`.env`** — environment: app mode, active profile, and provider credentials.
- **`config/*.yaml`** — providers, integrations, file allowlist, diagnostics.
- **`profiles/<name>/profile.yaml`** — per-profile behaviour (prompt, routing, memory).

After editing `.env` or `config/*.yaml`, restart the server. Three profile
fields are also editable live from the Settings panel (see *Profiles* below).

## Environment (`.env`)

Copy `.env.example` to `.env`. Common keys:

| Key | Purpose |
|---|---|
| `APP_ENV` | `development` or `production` |
| `ACTIVE_PROFILE` | Which profile under `profiles/` to load (default `athena`) |
| `LOG_LEVEL` | `INFO`, `WARNING`, … |

Provider credentials/transports also live in `.env` (see *Providers*). Secrets
are only ever read from `.env`, never written to YAML, and `.env` is never
included in backups.

## Providers (`config/providers.yaml`)

Each provider adapter has a `type` (`cli` / `api` / `stub`), an `enabled` flag,
and a `cost_tier`. Routing **rankings** select the order per mode:

```yaml
providers:
  ranking:
    quality_first: [claude, gemini, chatgpt, grok]
    balanced:      [gemini, claude, chatgpt, grok]
    budget_first:  [ollama, grok, gemini, chatgpt, claude]
  diagnostics:
    enabled: true            # measure-only latency trace (M22)
    ring_buffer_size: 50
```

The Providers tab and `athena --list-providers` report each provider's
**effective** transport and a config-based availability check (no network
probe) — e.g. Grok shows `api` when the API transport is configured.

### Grok transport (CLI or API)

One logical `grok` provider, with the transport resolved highest-priority-first:

1. `GROK_TRANSPORT` env var (`cli` | `api`)
2. `providers.adapters.grok.transport` in `config/providers.yaml`
3. default `cli` (the API never silently replaces the CLI)

API parameters (env): `XAI_API_KEY` (required for `api`), `GROK_MODEL`
(default `grok-4.3`), `GROK_API_URL` (default `https://api.x.ai/v1`),
`GROK_TIMEOUT` (seconds).

### Local model (Ollama)

Opt-in and disabled by default. Set `OLLAMA_API_URL` and `OLLAMA_MODEL` (and
optionally `OLLAMA_API_KEY`), enable it in `providers.yaml`, and it participates
in `budget_first` or as an explicit `preferred_provider`. Availability uses an
active health check; it never auto-tops `balanced`/`quality_first`.

### Hermes

Opt-in, CLI-backed (`hermes chat -q`); `HERMES_BIN` / `HERMES_TIMEOUT` env.
Disabled by default and in no ranking — use `preferred_provider: hermes` or add
it to a ranking.

## Profiles (`profiles/<name>/profile.yaml`)

```yaml
name: "Athena"
version: "1.0.0"            # profile schema/format version — NOT the app version
system_prompt: |
  You are Athena, a direct, practical assistant.
routing:
  mode: balanced           # quality-first | balanced | budget-first
  preferred_provider: null # null = follow the mode; or a provider name
  fallback_order: [claude, gemini, chatgpt, grok]
memory:
  auto_save_threshold: low
```

**Editable live (M26):** `system_prompt`, `routing.mode`, and
`routing.preferred_provider` can be changed from Settings → Profile (or via
`PATCH /profile`). Changes are validated, persisted to `profile.yaml`, and
applied to the running server without a restart; the next CLI run reloads the
file. Everything else is edited in the file directly (restart to apply).

### Selecting the active profile (M28.5 resolution order)

The active profile resolves through four mechanisms — first match wins:

1. **`ATHENA_PROFILE_OVERRIDE`** env — process-scoped explicit override; the
   CLI's `--profile <name>` flag sets this, so the flag beats everything.
2. **`config/active_profile.yaml`** — the runtime-switch file, written ONLY
   by `POST /profiles/activate` (the Settings-panel "Active profile"
   dropdown, or the endpoint directly). It deliberately beats the environment
   so a UI switch survives restarts on default installs (where `.env` sets
   `ACTIVE_PROFILE`). Delete the file — or switch back — to return control to
   the environment. A broken file falls through harmlessly.
3. **`ACTIVE_PROFILE`** env (usually via `.env`).
4. The default, `athena`.

Switching at runtime (`POST /profiles/activate {"name": "..."}`) re-points the
live profile, memory, saved items, and conversation history without a restart;
in-flight requests finish on the previous profile. `GET /profiles` lists the
available profiles.

### App vs profile version

The **app/release version** is reported by `/health`, the startup log, and the
Settings panel ("App version"). The profile's own `version` is its
**schema/format** version ("Profile schema version") — they are independent.

## File allowlist (`config/files.yaml`)

Controls which paths the assistant may `search` / `read` / `write`. Path
traversal is blocked and writes are audited. The History → Files tab hides
internal/operational artifacts (logs, audit, staging, backups) by default; a
toggle reveals them. This is a view filter only — the allowlist is unchanged.

## Integrations (CalDAV / CardDAV / Nextcloud)

Each has a `config/<name>.yaml` with `enabled: false` by default; credentials go
in `.env`. While disabled, the integration endpoints return `503` and the server
never attempts a connection. Flip `enabled: true` and set credentials to
activate. CardDAV writes are human-gated (staged merges, never auto-committed).
