"""
backup/portable.py — Portable Profiles: host-agnostic, secret-free identity
bundles (M28).

A Portable Profile is a **snapshot** of Athena's identity — system prompt +
memory + portable preferences — packaged to seed a *different* Athena instance.
It is the narrower, harder-scrubbed sibling of the full backup
(`backup/manager.py`): where backup captures everything needed to restore THIS
instance on THIS box, portable captures ONLY identity, scrubbed of anything
host-specific, operational, or secret.

Design contract (see docs/specs/M28-portable-profiles.md):

* **Allowlist-built.** The bundle is constructed from an explicit KEEP set
  (`_sanitize_profile`), never by deleting fields from a full copy — a new
  sensitive field fails closed (absent) rather than failing open (leaked).
* **Leak-guarded.** After building, the bundle content is scanned for secrets
  (live ``.env`` values, credential-shaped strings) and, in config-derived
  fields, URLs/absolute paths. A hit is a **hard failure** (PortableExportError)
  — never a warning.
* **Snapshot, not sync.** Once imported elsewhere, the two identities fork;
  memory diverges with no reconciliation. Stated in the manifest and by every
  surface.
* **Memory is kept but reviewed** (M28.0): `preview()` reports the entries so
  the user can exclude specific ones (`exclude_ids`) before export. The
  pending-review queue and archive are never exported (they haven't passed the
  user's own review gate / are operational history).

Never exported: credentials of any kind, service endpoint URLs, file
allowlists, absolute host paths (``memory.path``), ``machine_overrides``,
network/bind config, machine identifiers (no ``hostname`` in this manifest —
unlike the backup manifest), diagnostics/audit, staged/working data, chat
history, ``config/``.
"""

from __future__ import annotations

import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from memory.manager import CATEGORIES

PORTABLE_MANIFEST_FILENAME = "athena_portable_manifest.json"
PORTABLE_TYPE = "athena-portable-profile"
PORTABLE_VERSION = "1"
SNAPSHOT_NOTE = (
    "This bundle is a point-in-time snapshot. Once imported on another "
    "instance, the two identities fork: memory diverges and is not reconciled."
)

# Credential-shaped tokens (provider API keys, GitHub/AWS-style). Deliberately
# conservative: long random-ish tails so ordinary prose can't false-positive.
_CREDENTIAL_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),      # OpenAI-style
    re.compile(r"\bxai-[A-Za-z0-9_-]{16,}"),     # xAI-style
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),       # GitHub PAT
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),         # AWS access key id
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
_URL_PATTERN = re.compile(r"\bhttps?://\S+", re.IGNORECASE)
# Absolute host paths in config-derived fields (macOS/Linux/Windows roots).
_HOST_PATH_PATTERN = re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\\\?Users)")


class PortableExportError(Exception):
    """A striplist/leak-guard violation — the bundle must not be emitted."""


class PortableImportError(Exception):
    """An invalid/unsafe bundle or a clobber attempt — nothing is written."""


def _slugify(name: str) -> str:
    """Directory-safe profile slug: lowercase alnum plus - and _ (no paths)."""
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower()).strip("-_")
    return cleaned or "imported"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class PortableProfileManager:
    """Build (and later import — M28.1) portable identity bundles."""

    def __init__(self, app_root: Path, profile_dir: Path, app_version: str = "0.0.0") -> None:
        self._root = app_root
        self._profile_dir = profile_dir
        self._app_version = app_version

    # ------------------------------------------------------------------
    # Sanitize — the KEEP allowlist (the core of the milestone)
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_profile(raw: dict[str, Any]) -> dict[str, Any]:
        """
        Build the portable profile from an explicit KEEP set.

        Anything not listed here does NOT travel — including (deliberately):
        ``memory.path`` (host path), ``machine_overrides`` (host-specific by
        definition), and any field added to profile.yaml in the future until
        it is consciously added to this allowlist.
        """
        routing_in = raw.get("routing") or {}
        memory_in = raw.get("memory") or {}
        out: dict[str, Any] = {
            "name": raw.get("name", "Athena"),
            "description": raw.get("description", ""),
            "version": raw.get("version", "1.0.0"),
            "system_prompt": raw.get("system_prompt", ""),
            "routing": {
                # provider NAMES are portable; endpoints/keys are not (and are
                # not in profile.yaml to begin with — enforced by the leak scan).
                "mode": routing_in.get("mode", "balanced"),
                "preferred_provider": routing_in.get("preferred_provider"),
                "fallback_order": list(routing_in.get("fallback_order") or []),
            },
            "allowed_tools": list(raw.get("allowed_tools") or []),
            "memory": {
                # memory.path (a host path) is deliberately absent → default.
                "auto_save_threshold": memory_in.get("auto_save_threshold", "low"),
                "require_review_for": list(memory_in.get("require_review_for") or []),
            },
            # machine_overrides: stripped — always empty in a portable bundle.
            "machine_overrides": {},
        }
        return out

    # ------------------------------------------------------------------
    # Leak guard
    # ------------------------------------------------------------------

    def _env_secret_values(self) -> list[str]:
        """Values from the live .env (len>=8) — none may appear in a bundle."""
        env_path = self._root / ".env"
        secrets: list[str] = []
        if not env_path.exists():
            return secrets
        try:
            for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                value = line.split("=", 1)[1].strip().strip("'\"")
                if len(value) >= 8:
                    secrets.append(value)
        except Exception:  # noqa: BLE001 — unreadable .env = nothing to leak-match
            pass
        return secrets

    def _leak_scan(self, profile_text: str, memory_text: str) -> list[str]:
        """
        Return warnings; raise PortableExportError on a hard violation.

        Hard failures (anywhere in the bundle): a live .env value; a
        credential-shaped string. Hard failures in CONFIG-DERIVED text (the
        sanitized profile): URLs and absolute host paths — those are topology/
        host data and have no business in an identity bundle. In MEMORY text a
        URL may be legitimate user content → surfaced as a warning for the
        review step instead.
        """
        combined = profile_text + "\n" + memory_text
        for value in self._env_secret_values():
            if value in combined:
                raise PortableExportError(
                    "Refusing to export: a value from the live .env appears in the bundle."
                )
        for pat in _CREDENTIAL_PATTERNS:
            if pat.search(combined):
                raise PortableExportError(
                    "Refusing to export: a credential-shaped string appears in the bundle."
                )
        if _URL_PATTERN.search(profile_text) or _HOST_PATH_PATTERN.search(profile_text):
            raise PortableExportError(
                "Refusing to export: a URL or absolute host path appears in the "
                "portable profile fields."
            )
        warnings: list[str] = []
        if _URL_PATTERN.search(memory_text):
            warnings.append(
                "Memory entries contain URL(s). Review before sharing this bundle."
            )
        if _HOST_PATH_PATTERN.search(memory_text):
            warnings.append(
                "Memory entries contain absolute host path(s). Review before sharing."
            )
        return warnings

    # ------------------------------------------------------------------
    # Memory collection (KEEP set: saved categories only)
    # ------------------------------------------------------------------

    def _collect_memory(
        self, exclude_ids: set[str] | None = None
    ) -> tuple[dict[str, list[dict[str, Any]]], int, int]:
        """
        Load the saved memory categories (never pending_review, never archive),
        dropping entries whose ``id`` is in *exclude_ids*.

        Returns (by_category, kept_count, excluded_count).
        """
        exclude_ids = exclude_ids or set()
        by_cat: dict[str, list[dict[str, Any]]] = {}
        kept = 0
        excluded = 0
        mem_dir = self._profile_dir / "memory"
        for cat in CATEGORIES:
            path = mem_dir / f"{cat}.yaml"
            entries: list[dict[str, Any]] = []
            if path.exists():
                try:
                    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                    raw = data.get(cat, [])
                    if isinstance(raw, list):
                        entries = [e for e in raw if isinstance(e, dict)]
                except Exception:  # noqa: BLE001 — an unreadable category exports empty
                    entries = []
            kept_entries = []
            for e in entries:
                if str(e.get("id")) in exclude_ids:
                    excluded += 1
                else:
                    kept_entries.append(e)
            kept += len(kept_entries)
            by_cat[cat] = kept_entries
        return by_cat, kept, excluded

    # ------------------------------------------------------------------
    # Public API — M28.0 export
    # ------------------------------------------------------------------

    def preview(self) -> dict[str, Any]:
        """
        The review step: what WOULD be exported. Reports the sanitized profile
        fields and every memory entry (id/category/key) so the caller can pick
        ``exclude_ids`` before exporting. No files are written.
        """
        raw = self._load_profile_yaml()
        portable = self._sanitize_profile(raw)
        by_cat, kept, _ = self._collect_memory()
        entries = [
            {"id": e.get("id"), "category": cat, "key": e.get("key")}
            for cat, items in by_cat.items()
            for e in items
        ]
        return {
            "profile_name": portable["name"],
            "portable_profile": portable,
            "memory_entry_count": kept,
            "memory_entries": entries,
            "snapshot_note": SNAPSHOT_NOTE,
        }

    def create_export(self, exclude_ids: set[str] | None = None) -> tuple[Path, dict[str, Any]]:
        """
        Build the portable bundle zip under data/exports/ and return
        (zip_path, manifest). Raises PortableExportError on any leak-guard hit.
        """
        raw = self._load_profile_yaml()
        portable = self._sanitize_profile(raw)
        by_cat, kept, excluded = self._collect_memory(exclude_ids)

        profile_text = yaml.safe_dump(portable, sort_keys=False)
        memory_texts: dict[str, str] = {
            cat: yaml.safe_dump({cat: items}, sort_keys=False)
            for cat, items in by_cat.items()
        }
        warnings = self._leak_scan(profile_text, "\n".join(memory_texts.values()))

        manifest: dict[str, Any] = {
            "type": PORTABLE_TYPE,
            "portable_version": PORTABLE_VERSION,
            "app_version": self._app_version,
            "created_at": _now_iso(),
            # NO hostname here — machine identifiers do not travel (unlike the
            # full-backup manifest, which is same-host restore tooling).
            "profile_name": portable["name"],
            "memory_entry_count": kept,
            "memory_entries_excluded": excluded,
            "memory_categories": {cat: len(items) for cat, items in by_cat.items()},
            "warnings": warnings,
            "snapshot_note": SNAPSHOT_NOTE,
        }

        exports_dir = self._root / "data" / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        zip_path = exports_dir / f"{_now_stamp()}_athena_portable.zip"

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(PORTABLE_MANIFEST_FILENAME, json.dumps(manifest, indent=2))
            zf.writestr("profile.yaml", profile_text)
            for cat, text in memory_texts.items():
                zf.writestr(f"memory/{cat}.yaml", text)

        return zip_path, manifest

    def list_exports(self) -> list[dict[str, Any]]:
        """Portable bundles in data/exports/ (skips non-portable zips)."""
        exports_dir = self._root / "data" / "exports"
        if not exports_dir.exists():
            return []
        results: list[dict[str, Any]] = []
        for zip_path in sorted(exports_dir.glob("*.zip")):
            manifest = self.inspect(zip_path)
            if manifest.get("type") != PORTABLE_TYPE:
                continue
            results.append(
                {
                    "filename": zip_path.name,
                    "profile_name": manifest.get("profile_name"),
                    "created_at": manifest.get("created_at"),
                    "memory_entry_count": manifest.get("memory_entry_count"),
                    "app_version": manifest.get("app_version"),
                }
            )
        return results

    def inspect(self, zip_path: Path) -> dict[str, Any]:
        """Read a bundle's manifest; {"valid": False, ...} when unreadable."""
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                manifest = json.loads(zf.read(PORTABLE_MANIFEST_FILENAME))
            manifest["valid"] = True
            return manifest
        except Exception as exc:  # noqa: BLE001
            return {"valid": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Public API — M28.1 import
    # ------------------------------------------------------------------

    def import_bundle(
        self, zip_path: Path, new_name: str | None = None
    ) -> dict[str, Any]:
        """
        Materialize a NEW profile from a portable bundle. Defense in depth: the
        incoming content is re-run through the same allowlist + leak scan as
        export — a hand-edited bundle with planted secrets or host data is
        rejected (PortableImportError), whoever claims to have made it.

        Never clobbers: if the target profile directory exists, this raises —
        pass ``new_name`` to import under a different name. Never touches
        ``.env``, ``config/``, or ``data/``. Reads only fixed member names from
        the zip (no member-derived write paths → no Zip-Slip surface).
        """
        manifest = self.inspect(zip_path)
        if not manifest.get("valid"):
            raise PortableImportError(
                f"Not a readable portable bundle: {manifest.get('error', 'unknown')}"
            )
        if manifest.get("type") != PORTABLE_TYPE:
            raise PortableImportError(
                "Not a portable-profile bundle (wrong or missing type marker)."
            )
        warnings: list[str] = []
        if str(manifest.get("portable_version")) != PORTABLE_VERSION:
            warnings.append(
                f"Bundle portable_version={manifest.get('portable_version')!r} differs "
                f"from this app's {PORTABLE_VERSION!r} — importing best-effort."
            )

        # ---- read fixed members, re-sanitize (allowlist enforced on import too)
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = set(zf.namelist())
            if "profile.yaml" not in names:
                raise PortableImportError("Bundle has no profile.yaml.")
            raw_profile = yaml.safe_load(zf.read("profile.yaml")) or {}
            if not isinstance(raw_profile, dict):
                raise PortableImportError("Bundle profile.yaml is not a mapping.")
            portable = self._sanitize_profile(raw_profile)
            by_cat: dict[str, list[dict[str, Any]]] = {}
            for cat in CATEGORIES:
                member = f"memory/{cat}.yaml"
                entries: list[dict[str, Any]] = []
                if member in names:
                    data = yaml.safe_load(zf.read(member)) or {}
                    raw = data.get(cat, [])
                    if isinstance(raw, list):
                        entries = [e for e in raw if isinstance(e, dict)]
                by_cat[cat] = entries

        # ---- leak scan the incoming content (same hard-fail contract)
        profile_text = yaml.safe_dump(portable, sort_keys=False)
        memory_text = "\n".join(
            yaml.safe_dump({cat: items}, sort_keys=False) for cat, items in by_cat.items()
        )
        try:
            warnings += self._leak_scan(profile_text, memory_text)
        except PortableExportError as exc:
            raise PortableImportError(f"Rejected bundle: {exc}") from None

        # ---- provider degradation: warn on names this host can't resolve
        try:
            from providers.router import _ADAPTER_REGISTRY  # noqa: PLC0415

            known = set(_ADAPTER_REGISTRY)
            routing = portable.get("routing", {})
            named = [routing.get("preferred_provider")] + list(
                routing.get("fallback_order") or []
            )
            unknown = sorted({n for n in named if n and n not in known})
            if unknown:
                warnings.append(
                    "Provider preference(s) not available on this host (kept; the "
                    "router will skip them at runtime): " + ", ".join(unknown)
                )
        except Exception:  # noqa: BLE001 — a registry hiccup must not block import
            pass

        # ---- no-clobber target
        slug = _slugify(new_name or str(portable.get("name", "imported")))
        target_dir = self._root / "profiles" / slug
        if target_dir.exists():
            raise PortableImportError(
                f"Profile '{slug}' already exists — pass a new_name to import "
                "alongside it (import never overwrites)."
            )

        # ---- write the new profile
        mem_dir = target_dir / "memory"
        mem_dir.mkdir(parents=True)
        (target_dir / "profile.yaml").write_text(profile_text, encoding="utf-8")
        count = 0
        for cat, items in by_cat.items():
            (mem_dir / f"{cat}.yaml").write_text(
                yaml.safe_dump({cat: items}, sort_keys=False), encoding="utf-8"
            )
            count += len(items)
        (mem_dir / "pending_review.yaml").write_text(
            yaml.safe_dump({"pending": []}), encoding="utf-8"
        )

        return {
            "imported": True,
            "profile_slug": slug,
            "profile_name": portable.get("name"),
            "profile_dir": str(target_dir.relative_to(self._root)),
            "memory_entry_count": count,
            "warnings": warnings,
            "fork_warning": SNAPSHOT_NOTE,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_profile_yaml(self) -> dict[str, Any]:
        path = self._profile_dir / "profile.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise PortableExportError("profile.yaml did not contain a mapping.")
        return data
