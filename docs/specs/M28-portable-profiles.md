# M28 — Portable Profiles — SPEC (epic: M28.0, M28.1)

**Status: specced, awaiting go-ahead. Do NOT implement without explicit
approval. Two sub-milestones, shipped back-to-back and independently testable.**

## What & why

A **Portable Profile** is a host-agnostic, secret-free **identity bundle** —
Athena's "who I am" (system prompt + memory + portable preferences) packaged so
it can be carried to another Athena instance on another machine. It answers the
user's portability goal ("run Athena on a variety of platforms, carry its
personality and memory") for the *identity* half, which is the safe and
achievable half. (The *access* half — reaching a running instance remotely — is
the deliberately-deferred remote-access problem and stays docs-only via
Tailscale/VPN. This milestone does not touch it.)

**Snapshot, not sync.** Per the design decision, a Portable Profile is a
point-in-time **snapshot**, not a live sync. Once imported on a second instance,
the two identities **fork** — memory diverges thereafter, with no reconciliation.
This aligns with how Athena was designed (file-backed, single-user, no central
store) and must be **stated plainly** to the user at both export and import time.
We are not building sync, CRDTs, or conflict resolution.

**Builds on the backup subsystem.** `backup/manager.py` already exports a
zip+manifest of profiles (incl. per-profile `memory/`) + config and already
excludes `.env`. Portable Profiles is a *narrower, harder-scrubbed sibling* of
that: where backup is "everything to restore *this* instance on *this* box,"
portable is "just the identity, scrubbed of anything host-specific or secret, to
seed a *different* box." Reuse the backup module's zip/manifest plumbing; do not
build a second archiver.

Version mapping (milestone == version when it bumps): **M28.0 → 2.8.0**,
**M28.1 → 2.8.1**.

---

## The striplist (the core correctness contract)

Governing principle: **keep identity; strip anything host-specific, operational,
or secret.** A Portable Profile that leaks a credential or a private endpoint is
a security failure, not a feature. The export MUST enforce this allowlist-style —
build the bundle from an explicit *keep* set, don't try to blacklist fields off a
full copy (new sensitive fields would silently leak).

**KEEP (this is the identity — the whole point):**
- The profile **system prompt** and persona fields (`name`, `description`).
- **Memory** entries (the accumulated identity) — but see the review step below.
- **Portable preferences**: routing *mode* / *fallback order by provider name*,
  `allowed_tools` (tool *names* are portable), memory review policy
  (`require_review_for`). These are provider/tool *names*, not endpoints or keys.

**STRIP (never travels):**
- **Credentials of every kind** — API keys, DAV/Nextcloud passwords, tokens.
  (Already outside the profile — in `.env` — but the export must *verify* none
  leaked in, not assume.)
- **Service endpoint URLs** — CalDAV / CardDAV / Nextcloud base URLs. These leak
  network topology, not just secrets. Strip even though they aren't "secret."
- **File allowlists and any absolute host paths** — the readable/writable path
  set, `memory.path`, log/data/audit dirs, anything rooted at a host filesystem.
- **`machine_overrides`** — per-machine settings; host-specific by definition.
- **Network / bind config** — ports, host interfaces, anything about how this box
  serves.
- **Machine identifiers** — hostname or anything tying the bundle to one box.
- **Diagnostics / trace records** — operational metadata (content-free but
  host-referencing); not identity.
- **Audit logs** — operational + sensitive.
- **Transient / working data** — `data/carddav_staged/`, `data/import_conflicts/`,
  restore staging, `saved/` items (that's data, not identity). Exclude.
- **Chat history / conversation logs** — sensitive; explicitly not part of the
  identity bundle.

**KEEP-BUT-REVIEW (don't auto-strip, don't blindly export):**
- **Memory is kept** (auto-stripping it defeats the feature) **but** memory is
  exactly where personal/sensitive content accumulates. Export therefore includes
  a **review/redaction step**: it reports "this bundle contains N memory entries;
  review before sharing" and lets the user **exclude specific entries** before the
  bundle is finalized. The tool surfaces the decision; it does not silently decide
  for the user in either direction.

**Import-side degradation:**
- Provider *preferences* are kept, but a CLI-transport choice (e.g. `claude`,
  `gemini`) may not resolve on a host lacking that vendor CLI. Import must
  **degrade gracefully** — warn and fall back, never assume the named CLI exists
  or hard-fail because it doesn't.

---

## M28.0 — Export  (→ 2.8.0)

### Goal
Produce a Portable Profile bundle (zip + manifest) from a chosen profile,
enforcing the striplist and running the memory-review step.

### Scope
1. New export path (reuse `backup/manager.py` zip/manifest plumbing) that builds
   the bundle from the **explicit keep-set** above — allowlist construction, not
   blacklist filtering.
2. **Striplist enforcement + a self-check**: after building, scan the bundle for
   anything on the strip list (a key-shaped string, a URL, an absolute path,
   `.env` content) and **refuse to emit** if found — a leak is a hard failure, not
   a warning. This guard is the milestone's most important test.
3. **Memory review**: surface the entry count and allow per-entry exclusion
   before finalizing. (Surface via an endpoint / CLI flag consistent with the
   existing backup UX — decide at implementation.)
4. **Manifest**: records source version (`core/version.py`), a
   `portable-profile` type marker, the profile name, memory-entry count, and a
   **snapshot timestamp** with an explicit "snapshot — forks on import" note.
5. Tests (fully mocked): a profile carrying seeded secrets/URLs/paths exports to
   a bundle that (a) contains the identity, (b) contains **none** of the
   striplist items, (c) triggers the leak-guard hard-fail when a secret is
   planted where the allowlist would catch it, (d) honors a memory-exclusion
   selection.

### Version: **2.8.0**. CHANGELOG + `docs/BACKUP.md` (or a new
`docs/PORTABLE-PROFILES.md`) + INVARIANTS ("portable export is allowlist-built
and leak-guarded; a strip-list hit is a hard failure").

---

## M28.1 — Import  (→ 2.8.1)

### Goal
Consume a Portable Profile bundle on another instance, creating/seeding a profile
from the identity, with graceful degradation and a clear fork warning.

### Scope
1. Import path that validates the manifest (type marker, version compatibility),
   then materializes a profile from the **kept** identity fields only.
2. **Never import a striplist item** even if a malformed/hand-edited bundle
   contains one — the import side re-enforces the allowlist (defense in depth;
   don't trust the bundle was made by our own exporter).
3. **Graceful provider degradation** (see above): unknown/unavailable
   CLI-transport preferences warn + fall back rather than breaking routing.
4. **Fork warning**: on import, state plainly that this is a snapshot and the two
   instances' memory now diverge.
5. **No clobber**: importing must not silently overwrite an existing profile,
   `.env`, or local `data/` — new profile name or explicit confirm.
6. Tests (fully mocked): round-trip (export→import) preserves identity; a bundle
   with a planted secret is **rejected on import**; an unresolvable provider pref
   degrades without breaking; import doesn't overwrite an existing profile.

### Version: **2.8.1**. CHANGELOG + docs + INVARIANTS ("import re-enforces the
strip allowlist and never clobbers existing profile/.env/data").

---

## Self-review notes (epic-wide)
- **Allowlist on BOTH sides.** Export builds from a keep-set *and* import accepts
  only the keep-set. Blacklisting is fragile; a new sensitive field must fail
  closed (absent from the bundle) rather than fail open (copied through).
- **The leak-guard test is the milestone.** If nothing else, the "planted secret
  never appears in the bundle / is rejected on import" tests are what make this
  safe to ship.
- **Snapshot honesty.** Every surface (manifest, export message, import message,
  docs) repeats "snapshot, forks on import" — no user should believe this syncs.
- Reuse backup plumbing; **no second archiver**, no heavyweight deps.

## Out of scope
- Live sync / reconciliation / merge of two forked identities.
- Migrating secrets or endpoints (by design they never travel — the user
  re-enters them on the new host).
- Cross-version schema migration of profiles beyond a simple compatibility check.
