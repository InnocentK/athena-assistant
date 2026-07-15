# Athena Assistant — Runbook

Operational procedures for common tasks.

---

## Start / Stop

### Local

```bash
bash run.sh                   # starts on port 8000
bash run.sh --port 9000       # custom port
PORT=9000 bash run.sh         # or via env var
```

### Docker

```bash
docker compose up --build -d  # build and start detached
docker compose down           # stop and remove containers
docker compose restart athena # restart service without rebuild
```

---

## Health Check

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
# or: task health
```

Expected: `{"status":"ok","profile":"<name>","version":"<app version>"}`. The
`version` field is the single source of truth for the running release.

---

## View Logs

### Local

```bash
tail -f logs/app.log
```

### Docker

```bash
docker compose logs -f athena
```

---

## Enable an Integration

All integrations follow the same pattern:

1. Add credentials to `.env` (see `.env.example` for variable names).
2. Set `enabled: true` in the relevant `config/<integration>.yaml`.
3. Restart the server (or `docker compose restart athena`).
4. Confirm startup log shows `<Integration>Client initialised successfully.`

Integrations: `caldav`, `carddav`, `nextcloud`.

---

## Add a New Assistant Profile

```bash
cp -r profiles/athena profiles/<new-name>
# Edit profiles/<new-name>/profile.yaml
# Set ACTIVE_PROFILE=<new-name> in .env
# Restart the server
```

---

## Edit the File Allowlist

1. Edit `config/files.yaml` — add or remove entries.
2. Call `PATCH /files/allowlist/reload` (no restart needed):
   ```bash
   curl -X PATCH http://localhost:8000/files/allowlist/reload
   ```

---

## View the Audit Trail

All file write operations are logged to dated files in `audit/`:

```bash
ls audit/
cat audit/2026-06-03_file_audit.log
```

Format: `ISO_TIMESTAMP | WRITE | <path> | <bytes> bytes`

---

## Review Pending Memory

Memory auto-extraction places candidates in a review queue. Review and approve or discard via the UI sidebar, or via curl:

```bash
# List pending
curl http://localhost:8000/memory/pending

# Approve
curl -X POST http://localhost:8000/memory/pending/<id>/approve

# Discard
curl -X DELETE http://localhost:8000/memory/pending/<id>
```

---

## Stage and Commit a Contact Merge

```bash
# Detect duplicates (read-only)
curl "http://localhost:8000/carddav/duplicates?address_book_url=<url>"

# Stage a merge (no server write)
curl -X POST http://localhost:8000/carddav/merges \
  -H "Content-Type: application/json" \
  -d '{"address_book_url":"<url>","contact_hrefs":["/a.vcf","/b.vcf"],"merged_data":{"fn":"Full Name"}}'

# Review staged merges
curl http://localhost:8000/carddav/merges

# Commit (writes to server — human-initiated only)
curl -X POST http://localhost:8000/carddav/merges/<staged_merge_id>/commit

# Or discard
curl -X DELETE http://localhost:8000/carddav/merges/<staged_merge_id>
```

---

## Backup

Athena has a **built-in backup/restore feature** (zip + manifest, dry-run diff,
staged restore). Prefer it over a manual archive. See **[BACKUP.md](BACKUP.md)**
for the full flow; the essentials:

```bash
# Create an export (profiles + config), then list exports
task backup
task backup:list
# or via the API:
curl -s -X POST http://localhost:8000/backup/exports \
  -H 'Content-Type: application/json' -d '{"include_audit":false,"include_data":false}'

# Restore is a two-step, safety-gated flow: review a dry-run diff to get a
# single-use diff_token, then confirm the restore with it.
task restore:diff ZIP=<export-filename>        # dry-run; returns a diff_token
curl -s -X POST http://localhost:8000/backup/restore \
  -H 'Content-Type: application/json' \
  -d '{"zip_filename":"<export-filename>","confirm":true,"diff_token":"<token>"}'
```

Exports land in `data/exports/`. `.env` is never included — store credentials
separately. A manual `tar czf backup.tgz config/ profiles/` still works as a
fallback if the server isn't running.

---

## Upgrade Dependencies

```bash
source .venv/bin/activate
pip install --upgrade -r requirements.txt
# Restart the server
```

---

## Reset Memory for a Profile

```bash
# Clear all memory files (irreversible)
rm profiles/<name>/memory/*.yaml
# Restart server — memory files will be recreated empty on next write
```

---

## Proxmox / Docker Notes

- The Docker image runs as a non-root user (`athena`).
- Named volumes (`athena-logs`, `athena-audit`, `athena-data`) persist across `docker compose down`.
- `config/` and `profiles/` are bind-mounted — edit them on the host, changes take effect immediately for YAML-hot-reloaded configs (files allowlist), or after restart for everything else.
- The port is configurable via `ATHENA_PORT` env var in `.env` (default: 8000).
