"""
dav_io/vcf_io.py — VCF (vCard) import and export utilities.

Import flow:
  1. Parse all vCards from the input string
  2. For each vCard, check for conflicts (same UID or same FN+email) against existing contacts
  3. Import non-conflicting records immediately
  4. Queue conflicting records in data/import_conflicts/<batch_id>_carddav.json
  5. Return an ImportSummary

Export flow:
  - Accepts a list of contact dicts (from CardDAVClient.list_contacts())
  - Fetches full vCard data for each contact (or reconstructs from dict)
  - Returns a single .vcf string (multi-card VCF)

Safety rules:
  - Non-conflicting records are imported first
  - Conflicting records are NEVER silently merged, overwritten, or deleted
  - All conflicts are queued for human review
  - CardDAV merge always requires preview and explicit confirmation before write-back
  - All import actions are audited
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import vobject

from core.urlguard import ensure_same_origin


# ---------------------------------------------------------------------------
# ImportSummary dataclass
# ---------------------------------------------------------------------------


@dataclass
class ImportSummary:
    batch_id: str
    total: int = 0
    imported: int = 0
    skipped_conflicts: int = 0
    invalid: int = 0
    failed: int = 0
    conflict_ids: list[str] = field(default_factory=list)   # staged conflict entry IDs
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "total": self.total,
            "imported": self.imported,
            "skipped_conflicts": self.skipped_conflicts,
            "invalid": self.invalid,
            "failed": self.failed,
            "conflict_ids": self.conflict_ids,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# VCF parsing
# ---------------------------------------------------------------------------


def parse_vcf_string(vcf_str: str) -> tuple[list[dict], list[str]]:
    """Parse a multi-card VCF string into a list of contact dicts.

    Splits on END:VCARD boundary, parses each block with vobject.

    Returns:
        (parsed_list, error_list)
        parsed_list: list of dicts with keys {raw_vcard, uid, fn, email, phone, org, note}
        error_list:  list of error strings for blocks that could not be parsed
    """
    parsed: list[dict] = []
    errors: list[str] = []

    if not vcf_str or not vcf_str.strip():
        return parsed, errors

    # Split on END:VCARD (case-insensitive), keeping the delimiter
    import re
    blocks = re.split(r'(?i)(END:VCARD)', vcf_str)

    # Reassemble blocks: each valid vCard consists of the text before END:VCARD + END:VCARD itself
    raw_blocks: list[str] = []
    i = 0
    current = ""
    while i < len(blocks):
        part = blocks[i]
        if re.match(r'(?i)^END:VCARD$', part.strip()):
            current += part
            raw_blocks.append(current.strip())
            current = ""
        else:
            current += part
        i += 1

    # Any remaining text that doesn't have END:VCARD
    if current.strip():
        # Only add if it looks like a vCard start
        if re.search(r'(?i)BEGIN:VCARD', current):
            raw_blocks.append(current.strip())

    # If there's non-whitespace input but no raw_blocks were found, it's all invalid
    if not raw_blocks and vcf_str.strip():
        errors.append(f"No valid vCard blocks found in input (missing BEGIN:VCARD/END:VCARD): {vcf_str[:80]!r}")
        return parsed, errors

    for block in raw_blocks:
        block = block.strip()
        if not block:
            continue
        # Must contain both BEGIN:VCARD and END:VCARD
        if not (re.search(r'(?i)BEGIN:VCARD', block) and re.search(r'(?i)END:VCARD', block)):
            errors.append(f"Block missing BEGIN/END:VCARD markers: {block[:80]!r}")
            continue
        try:
            card = vobject.readOne(block)
        except Exception as exc:
            errors.append(f"Failed to parse vCard block: {exc!s} — block starts with: {block[:80]!r}")
            continue

        entry: dict = {
            "raw_vcard": block,
            "uid": "",
            "fn": "",
            "email": "",
            "phone": "",
            "emails": [],
            "phones": [],
            "org": "",
            "note": "",
        }
        try:
            if hasattr(card, "uid"):
                entry["uid"] = str(card.uid.value).strip()
        except Exception:
            pass
        try:
            if hasattr(card, "fn"):
                entry["fn"] = str(card.fn.value).strip()
        except Exception:
            pass
        # M26.9: capture ALL emails/phones (a contact may have several). The
        # singular email/phone keep the first value for backward compatibility
        # (conflict detection + the API summary); the lists preserve the rest so
        # export's reconstruct path no longer silently drops them.
        try:
            emails = [str(e.value).strip() for e in card.contents.get("email", []) if str(e.value).strip()]
            entry["emails"] = emails
            entry["email"] = emails[0] if emails else ""
        except Exception:
            pass
        try:
            phones = [str(t.value).strip() for t in card.contents.get("tel", []) if str(t.value).strip()]
            entry["phones"] = phones
            entry["phone"] = phones[0] if phones else ""
        except Exception:
            pass
        try:
            if hasattr(card, "org"):
                org_val = card.org.value
                if isinstance(org_val, (list, tuple)):
                    entry["org"] = " ".join(str(p) for p in org_val if p).strip()
                else:
                    entry["org"] = str(org_val).strip()
        except Exception:
            pass
        try:
            if hasattr(card, "note"):
                entry["note"] = str(card.note.value).strip()
        except Exception:
            pass

        parsed.append(entry)

    return parsed, errors


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


def detect_vcf_conflict(candidate: dict, existing_contacts: list[dict]) -> dict | None:
    """Return the first existing contact that conflicts with the candidate, or None.

    Conflict rules (either is sufficient):
      - Same UID (non-empty, case-insensitive)
      - Same FN AND same email (both non-empty, case-insensitive)
    """
    cand_uid = (candidate.get("uid") or "").strip().lower()
    cand_fn = (candidate.get("fn") or "").strip().lower()
    cand_email = (candidate.get("email") or "").strip().lower()

    for existing in existing_contacts:
        ex_uid = (existing.get("uid") or "").strip().lower()
        ex_fn = (existing.get("fn") or "").strip().lower()
        ex_email = (existing.get("email") or "").strip().lower()

        # Rule 1: same UID (non-empty)
        if cand_uid and ex_uid and cand_uid == ex_uid:
            return existing

        # Rule 2: same FN AND same email (both non-empty)
        if (cand_fn and ex_fn and cand_fn == ex_fn
                and cand_email and ex_email and cand_email == ex_email):
            return existing

    return None


# ---------------------------------------------------------------------------
# Audit helper
# ---------------------------------------------------------------------------


def _append_audit(record: str) -> None:
    """Append an audit record to today's audit log file."""
    try:
        from core.config import APP_ROOT
        audit_dir = APP_ROOT / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        audit_file = audit_dir / f"{date_str}_import_audit.log"
        with audit_file.open("a", encoding="utf-8") as f:
            f.write(record + "\n")
    except Exception:
        pass  # Audit failure must not break import


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def import_vcf(
    vcf_str: str,
    address_book_url: str,
    carddav_client,
    conflicts_dir: Path,
) -> ImportSummary:
    """Import vCards from a VCF string into a CardDAV address book.

    Safety rules:
      - Non-conflicting records are imported first
      - Conflicting records are queued for human review (NEVER silently overwritten)
      - All actions are audited

    Args:
        vcf_str:           Raw .vcf content
        address_book_url:  CardDAV address book URL
        carddav_client:    An initialised CardDAVClient instance
        conflicts_dir:     Directory to write conflict queue JSON files

    Returns:
        ImportSummary with counts and conflict_ids
    """
    batch_id = uuid.uuid4().hex
    summary = ImportSummary(batch_id=batch_id)

    # 1. Parse
    parsed, parse_errors = parse_vcf_string(vcf_str)
    summary.errors.extend(parse_errors)
    summary.invalid += len(parse_errors)
    summary.total = len(parsed) + len(parse_errors)

    if not parsed and not parse_errors:
        # Empty input — nothing to do
        _append_audit(
            f"{datetime.now(timezone.utc).isoformat()} | CARDDAV_IMPORT | "
            f"batch_id={batch_id} | total=0 imported=0 conflicts=0 invalid=0 failed=0"
        )
        return summary

    # M26.13 SSRF guard — fail fast with a clean 400 instead of per-card
    # "failed" entries. (Egress is independently blocked by the client's
    # _request chokepoint; this is the user-facing front door.)
    ensure_same_origin(address_book_url, getattr(carddav_client, "_url", ""), "CardDAV")

    # 2. Fetch existing contacts
    try:
        existing_contacts = carddav_client.list_contacts(address_book_url)
    except Exception as exc:
        existing_contacts = []
        summary.errors.append(f"Could not fetch existing contacts (proceeding with empty list): {exc!s}")

    # 3. Process each parsed vCard
    conflicts: list[dict] = []

    for card in parsed:
        # Detect conflict
        conflicting = detect_vcf_conflict(card, existing_contacts)

        if conflicting is not None:
            # Queue for human review — NEVER overwrite
            conflict_id = uuid.uuid4().hex
            reason = "uid_match" if (
                (card.get("uid") or "").strip().lower()
                == (conflicting.get("uid") or "").strip().lower()
                and card.get("uid")
            ) else "fn_email_match"
            conflicts.append({
                "conflict_id": conflict_id,
                "reason": reason,
                "incoming": {
                    "uid": card.get("uid", ""),
                    "fn": card.get("fn", ""),
                    "email": card.get("email", ""),
                    "phone": card.get("phone", ""),
                    "org": card.get("org", ""),
                    "note": card.get("note", ""),
                    "raw_vcard": card.get("raw_vcard", ""),
                },
                "existing": {
                    "uid": conflicting.get("uid", ""),
                    "fn": conflicting.get("fn", ""),
                    "email": conflicting.get("email", ""),
                    "phone": conflicting.get("phone", ""),
                    "org": conflicting.get("org", ""),
                    "note": conflicting.get("note", ""),
                    "href": conflicting.get("href", ""),
                },
            })
            summary.skipped_conflicts += 1
            summary.conflict_ids.append(conflict_id)
        else:
            # Non-conflicting: PUT to server
            uid = card.get("uid") or uuid.uuid4().hex
            url = address_book_url.rstrip("/") + "/" + uid + ".vcf"
            raw_vcard = card.get("raw_vcard", "")
            try:
                resp = carddav_client._request(
                    "PUT",
                    url,
                    data=raw_vcard,
                    headers={"Content-Type": "text/vcard; charset=utf-8"},
                )
                if resp.ok:
                    summary.imported += 1
                else:
                    summary.failed += 1
                    summary.errors.append(
                        f"PUT {url} returned HTTP {resp.status_code}: {resp.text[:200]}"
                    )
            except Exception as exc:
                summary.failed += 1
                summary.errors.append(f"PUT {url} raised exception: {exc!s}")

    # 4. Save conflict queue
    if conflicts:
        conflicts_dir.mkdir(parents=True, exist_ok=True)
        conflict_file = conflicts_dir / f"{batch_id}_carddav.json"
        conflict_data = {
            "batch_id": batch_id,
            "address_book_url": address_book_url,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
            "conflicts": conflicts,
        }
        try:
            conflict_file.write_text(json.dumps(conflict_data, indent=2), encoding="utf-8")
        except Exception as exc:
            summary.errors.append(f"Failed to write conflict file: {exc!s}")

    # 5. Audit
    _append_audit(
        f"{datetime.now(timezone.utc).isoformat()} | CARDDAV_IMPORT | "
        f"batch_id={batch_id} | "
        f"total={summary.total} imported={summary.imported} "
        f"conflicts={summary.skipped_conflicts} invalid={summary.invalid} failed={summary.failed}"
    )

    return summary


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_vcf(contacts: list[dict], carddav_client=None) -> str:
    """Export a list of contacts to a multi-card VCF string.

    Args:
        contacts:        List of contact dicts with keys {href, fn, email, phone, org, note, uid}
        carddav_client:  If provided, fetch full vCard via GET on each href

    Returns:
        Concatenated .vcf string (all cards joined with CRLF)
    """
    from carddav_integration.vcard_helpers import build_vcard

    vcards: list[str] = []

    for contact in contacts:
        raw = None

        # Try fetching full vCard from server
        if carddav_client is not None:
            href = contact.get("href", "")
            if href:
                try:
                    resp = carddav_client._request("GET", href)
                    if resp.ok:
                        raw = resp.text
                except Exception:
                    raw = None

        # Reconstruct from dict if no raw vCard available
        if not raw:
            uid = contact.get("uid") or uuid.uuid4().hex
            fn = contact.get("fn", "") or "Unknown"
            # M26.9: prefer the full lists (all values); fall back to the
            # singular field so single-value/legacy dicts still work.
            emails = [e for e in (contact.get("emails") or [contact.get("email", "")]) if e]
            phones = [p for p in (contact.get("phones") or [contact.get("phone", "")]) if p]
            org = contact.get("org", "") or ""
            note = contact.get("note", "") or ""
            try:
                raw = build_vcard(
                    uid=uid,
                    fn=fn,
                    emails=emails,
                    phones=phones,
                    org=org,
                    note=note,
                )
            except Exception:
                continue

        if raw:
            vcards.append(raw.strip())

    return "\r\n".join(vcards)
