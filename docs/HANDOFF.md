# Operator Orientation

New to this deployment? Read these in order — each links onward:

1. **[../README.md](../README.md)** — what Athena is, at a glance.
2. **[INSTALLATION.md](INSTALLATION.md)** — get it running (local or Docker) and
   install the `athena` CLI.
3. **[CONFIGURATION.md](CONFIGURATION.md)** — providers, routing, profiles, the
   file allowlist, and enabling integrations.
4. **[ARCHITECTURE.md](ARCHITECTURE.md)** — how it fits together and the key
   design decisions.

Then keep these handy:

- **[RUNBOOK.md](RUNBOOK.md)** — day-to-day operational procedures.
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** — common problems and fixes.
- **[BACKUP.md](BACKUP.md)** — backup / restore.
- **[SECURITY.md](SECURITY.md)** — what Athena protects and how.
- **[VALIDATION.md](VALIDATION.md)** — quick smoke checks for a running instance.

The full doc index is in **[README.md](README.md)** (this `docs/` folder).

## Key facts

- **State is plain files.** Config in `config/*.yaml`, memory in
  `profiles/<name>/memory/*.yaml`, staged merges in `data/carddav_staged/`. No
  database.
- **Secrets live only in `.env`** (never in YAML, never in backups).
- **Integrations are disabled by default** — flip `enabled: true` in
  `config/<name>.yaml` and add credentials to `.env`.
- **Version** is reported by `GET /health` and the startup log — it is not
  hardcoded in these docs (so it can't drift). Contributors: see
  **[../CLAUDE.md](../CLAUDE.md)** and **[INVARIANTS.md](INVARIANTS.md)**.

### What git tracks vs. what to back up separately

- **Versioned:** source, config YAML, `profile.yaml`, templates, static assets.
- **Not versioned (back up separately):** `.env` (credentials),
  `profiles/*/memory/` (personal data), `logs/`, `audit/*.log`, `data/` (runtime
  output). Use the built-in backup ([BACKUP.md](BACKUP.md)) for
  profiles+config.
