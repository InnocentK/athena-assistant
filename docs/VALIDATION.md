# Validation — quick smoke checks

The fast way to confirm a running Athena instance is healthy. For setup see
[INSTALLATION.md](INSTALLATION.md); for problems see
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

> The authoritative regression check is the automated test suite:
> `task test:run` (or `python -m pytest tests/ -q`). The historical,
> milestone-by-milestone validation recipes are archived under
> [`history/RUN_AND_VALIDATE-milestones.md`](history/RUN_AND_VALIDATE-milestones.md)
> — kept for the record, no longer the primary reference.

## 1. Lint + run the test suite

```bash
source .venv/bin/activate
task lint              # ruff correctness gate (M26.19) — sub-second
task typecheck         # mypy type gate (M26.21)
task test:run          # or: python -m pytest tests/ -q
```
Both should be clean. `task lint` (ruff) and `task typecheck` (mypy) are the fast correctness
gates; `task test:run` is the real regression gate. The
manual checks below just confirm a *running server* behaves.

## 2. Health & version

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```
Returns `{"status":"ok","profile":"<name>","version":"<app version>"}`. The
`version` is the single source of truth for the running release (don't compare it
against any number hardcoded in docs).

## 3. Providers

```bash
curl -s http://localhost:8000/providers | python3 -m json.tool
# CLI equivalent (shows each provider's effective transport):
athena --list-providers
```

## 4. Chat

```bash
curl -s -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"What is 2 + 2?","history":[]}' | python3 -m json.tool
```
Success → `{"response": "...", "provider": "<who answered>", "success": true, ...}`.
If no provider is installed/configured you'll get `success:false` with
`"All providers failed."` — expected, not a bug (install a CLI or set an API key).

## 5. Memory & files (read paths)

```bash
curl -s http://localhost:8000/memory | python3 -m json.tool
curl -s http://localhost:8000/memory/pending | python3 -m json.tool
curl -s -X POST http://localhost:8000/files/search \
  -H 'Content-Type: application/json' -d '{"pattern":"*","exclude_internal":true}'
```

## 6. Backup (built-in)

```bash
task backup            # create an export
task backup:list       # list exports
```
See [BACKUP.md](BACKUP.md) for the full export → diff → restore flow (restore is
gated by a single-use `diff_token`).

## 7. Browser UI

Open `http://localhost:8000`. The chat should load (dark theme), send a message,
show which provider answered, and the ⚙ Settings / 🕘 History / Memory panels
should open. Interactive API docs are at `/docs`.

---

**Integrations (CalDAV / CardDAV / Nextcloud)** are disabled by default and
return `503` until enabled in `config/<name>.yaml` + credentials in `.env`. See
[CONFIGURATION.md](CONFIGURATION.md).
