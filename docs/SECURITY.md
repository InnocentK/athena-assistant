# Security

Athena is a **single-user, local-first** app with **no authentication layer** —
it assumes the host and network are trusted (localhost, or behind your own
reverse proxy / VPN). Do not expose it directly to the public internet without
putting your own auth in front of it.

This page summarizes what Athena deliberately protects. The enforcing mechanisms
(and their tests) are catalogued in [INVARIANTS.md](INVARIANTS.md).

## Credentials

- **All secrets live only in `.env`** — provider API keys and integration
  credentials. They are never written to YAML and never included in backups.
- Integration credentials are read from the environment at init; a missing
  credential yields a clear error, not a silent failure.

## Filesystem safety

- **File allowlist.** The assistant may only `search`/`read`/`write` paths
  permitted by `config/files.yaml`. Path resolution is contained to the
  allowlisted roots (via `.resolve()` + `relative_to`), so `../` traversal and
  symlink escapes are rejected. All writes are audited.
- **Memory category allowlist.** Memory writes can only target the known
  category files — a crafted `category` (e.g. `"../evil"`) is rejected (`400`),
  so nothing can be written outside the profile's memory directory.
- **Backup restore is Zip-Slip-safe.** Every zip member is contained to the app
  root before extraction; members that would escape (`../…` or absolute) are
  rejected and counted, never written. Restore also stages originals first and
  is gated by a filename-bound, single-use `diff_token`. See
  [BACKUP.md](BACKUP.md).
- **Export filenames are traversal-guarded** (`../`/absolute → `400`).

## Network egress

- **DAV requests only ever go to the configured server.** Endpoints that accept
  a calendar/address-book URL or href validate it against the configured
  `CALDAV_URL`/`CARDDAV_URL` origin (scheme+host+port) and reject anything else
  with `400` — a crafted URL can't point the stored DAV credentials at another
  host (SSRF / credential exfiltration). Nextcloud always appends paths to its
  fixed base, so its host can't be changed at all.

## Data-integrity gates

- **CardDAV writes are human-gated.** Duplicate detection and merge staging are
  read-only/local; the only server write path (`commit_merge`) requires an
  explicit call with a valid `staged_merge_id`. Nothing is auto-committed.
- **Memory auto-extraction never auto-saves.** Candidates go to a pending review
  queue for explicit approval.
- **Integrations are disabled by default** and return `503` until you enable
  them; no outbound connection is attempted while disabled.

## Robustness (denial-of-service resistance)

- Provider and DAV calls run off the event loop with **bounded timeouts**, so a
  slow/hung upstream can't freeze the server or pin a worker indefinitely. As of
  M26.12 this is enforced at the **transport level** too: every outbound
  CalDAV/CardDAV/Nextcloud HTTP call sets an explicit socket timeout (a route
  timeout alone can't cancel the worker thread).
- Remote reads (e.g. Nextcloud `read_file`) are **size-capped while streaming**,
  so an oversized remote file can't exhaust memory.

## Error handling

- A global handler returns a **sanitized 500** (no raw traceback) for unexpected
  errors; expected errors return specific 4xx/5xx codes.

## Reporting an issue

This is a personal project; if you find a security problem, note it in the
project's issue tracker (or your own notes) with reproduction steps. When adding
code, keep the guarantees above intact — [INVARIANTS.md](INVARIANTS.md) lists
each mechanism and the test that enforces it.
