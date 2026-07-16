# Portable Profiles — carry Athena's identity to another instance

A **Portable Profile** is a host-agnostic, secret-free **identity bundle**:
the active profile's system prompt, memory, and portable preferences, packaged
so another Athena instance on another machine can be seeded with the same
"personality". It is built on the backup subsystem but is deliberately
narrower — see [BACKUP.md](BACKUP.md) for the full same-host backup/restore.

**It is a snapshot, not a sync.** Once a bundle is imported elsewhere, the two
identities **fork**: each instance's memory grows separately and nothing
reconciles them. If you want the "same" Athena in two places, expect them to
drift apart from the moment of import.

## What travels / what never does

Kept (the identity — built from an explicit allowlist):

- the system prompt and persona fields (name, description),
- saved **memory** entries (all categories; see the review step below),
- portable preferences: routing *mode*, preferred/fallback provider *names*,
  `allowed_tools` names, and the memory review policy.

Never travels (stripped or refused):

- credentials of every kind (`.env` is never read into a bundle, and the leak
  guard hard-fails if a live `.env` value or a credential-shaped string appears
  anywhere in the bundle),
- service endpoint URLs (CalDAV/CardDAV/Nextcloud — topology, not identity),
- file allowlists and absolute host paths (`memory.path` is dropped),
- `machine_overrides` (host-specific by definition),
- machine identifiers — this manifest has **no hostname**, unlike a backup's,
- diagnostics traces, audit logs, chat history,
- the pending-review memory queue and archive (not yet user-approved /
  operational history), staged/working data, and all of `config/`.

A striplist violation is a **hard failure** (HTTP 409): the bundle is not
written. URLs found in *memory entries* are the one soft case — they may be
legitimate user content, so they surface as warnings for the review step
rather than blocking the export.

## The review step (memory is kept-but-reviewed)

Memory is where personal detail accumulates, so the export is built for review:

1. `GET /portable/preview` — the sanitized profile fields plus every memory
   entry (`id`, category, key). Nothing is written.
2. Pick any entries to leave out.
3. `POST /portable/exports` with `{"exclude_ids": ["mem_…", …]}` — builds the
   bundle without them and reports how many were excluded.

```bash
curl -s localhost:8000/portable/preview | python3 -m json.tool
curl -s -X POST localhost:8000/portable/exports \
  -H 'Content-Type: application/json' \
  -d '{"exclude_ids": []}' | python3 -m json.tool
```

Bundles land in `data/exports/` as `<stamp>_athena_portable.zip` (listed by
`GET /portable/exports`, downloadable at `GET /portable/exports/<filename>`;
they do not appear in the full-backup listing, or vice versa).

## Bundle layout

```
athena_portable_manifest.json   type/version/profile name/memory counts + snapshot note
profile.yaml                    sanitized (allowlist-built) profile
memory/<category>.yaml          saved memory categories
```

## Import

On the receiving instance, place the bundle zip in `data/exports/` and:

```bash
curl -s -X POST localhost:8000/portable/import \
  -H 'Content-Type: application/json' \
  -d '{"zip_filename": "<stamp>_athena_portable.zip", "new_name": "athena-two"}' \
  | python3 -m json.tool
```

What import guarantees:

- **The allowlist and leak scan run again on the way in** (defense in depth):
  a hand-edited bundle with planted secrets or host data is rejected with 409
  and nothing is written; stray `machine_overrides`/`memory.path` are stripped.
- **Never overwrites.** If the target profile already exists you get a 409 —
  pass `new_name` to import alongside it. `.env`, `config/`, and `data/` are
  never touched.
- **Provider preferences degrade gracefully.** Names the new host can't
  resolve are kept (Athena's router skips unavailable providers at runtime)
  and reported as a warning — install/log in to the vendor CLIs or set API
  keys to activate them.
- **The fork warning is repeated**: from this moment the two instances' memory
  diverges. To *use* the imported identity, point `ACTIVE_PROFILE` at the new
  profile directory name and restart.
