# Backup & Restore

Athena has a built-in backup subsystem: it produces a **zip + manifest** of your
profiles and config, supports a **dry-run diff** before restoring, and stages
originals before overwriting so a restore is reversible. Restore is
**safety-gated** — a confirmed restore requires a single-use token obtained from
a dry-run diff of the *same* backup.

All backup files live in `data/exports/`. `.env` is **never** included (store
credentials separately).

## What's in a backup

- `profiles/` (including per-profile memory) and `config/*.yaml` by default.
- Optionally `audit/` and `data/` (via `include_audit` / `include_data`).
- A `athena_backup_manifest.json` recording the app version, timestamp, and file
  list.

## Create an export

```bash
task backup            # profiles + config
# or via the API:
curl -s -X POST http://localhost:8000/backup/exports \
  -H 'Content-Type: application/json' \
  -d '{"include_audit":false,"include_data":false}' | python3 -m json.tool
```

## List / inspect / download / delete

```bash
task backup:list                                             # list exports
curl -s http://localhost:8000/backup/exports/<file>/inspect  # manifest only
curl -s -OJ http://localhost:8000/backup/exports/<file>      # download the zip
curl -s -X DELETE http://localhost:8000/backup/exports/<file>
```

## Restore (two-step, gated)

Restore always **stages** the files it would overwrite into
`data/restore_staging/<timestamp>/` first, then extracts. The confirmed restore
requires a `diff_token` from a prior dry-run diff of the same file:

```bash
# 1. Dry-run diff — shows would_add / would_overwrite / rejected, returns a token.
task restore:diff ZIP=<file>
#    (or) curl -s http://localhost:8000/backup/exports/<file>/diff

# 2. Confirm with the token (single-use, 5-min TTL, bound to THIS filename).
curl -s -X POST http://localhost:8000/backup/restore \
  -H 'Content-Type: application/json' \
  -d '{"zip_filename":"<file>","confirm":true,"diff_token":"<token>"}' | python3 -m json.tool
```

Safety properties (see [SECURITY.md](SECURITY.md) / [INVARIANTS.md](INVARIANTS.md)):

- `confirm:false` (or omitting it) returns the diff only — **no writes**.
- The `diff_token` is **bound to the filename** it was issued for — a token from
  backup A can't restore backup B (returns `409`).
- Zip members that would escape the app root (`../…` or absolute paths) are
  **rejected**, never written (Zip-Slip guard); they appear under `rejected`.
- Backup filenames are validated against traversal (`../`/absolute → `400`).

## Manual fallback

If the server isn't running, a plain archive of the state dirs still works:

```bash
tar czf athena-backup-$(date +%Y%m%d).tar.gz config/ profiles/ data/ audit/
# restore: tar xzf athena-backup-<date>.tar.gz
```
