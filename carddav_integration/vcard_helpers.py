"""vcard_helpers.py — Utilities for building and parsing vCard strings."""

from __future__ import annotations

from datetime import datetime, timezone

import vobject


def parse_vcard(vcard_str: str) -> dict:
    """Parse a vCard string with vobject, extract {uid, fn, email, phone, org, note}.

    All fields default to "".
    """
    result = {"uid": "", "fn": "", "email": "", "phone": "", "org": "", "note": ""}
    try:
        card = vobject.readOne(vcard_str)
        if hasattr(card, "uid"):
            result["uid"] = str(card.uid.value).strip()
        if hasattr(card, "fn"):
            result["fn"] = str(card.fn.value).strip()
        if hasattr(card, "email"):
            result["email"] = str(card.email.value).strip()
        if hasattr(card, "tel"):
            result["phone"] = str(card.tel.value).strip()
        if hasattr(card, "org"):
            org_val = card.org.value
            if isinstance(org_val, (list, tuple)):
                result["org"] = " ".join(str(p) for p in org_val if p).strip()
            else:
                result["org"] = str(org_val).strip()
        if hasattr(card, "note"):
            result["note"] = str(card.note.value).strip()
    except Exception:
        pass
    return result


def build_vcard(
    uid: str,
    fn: str,
    emails: list[str],
    phones: list[str],
    org: str,
    note: str,
    rev: str | None = None,
) -> str:
    """Build a minimal RFC 6350 vCard 3.0 string.

    Uses vobject to construct the card and returns the serialised string.
    """
    card = vobject.vCard()

    # VERSION is added by vobject automatically as 3.0 when using vCard()

    # UID
    card.add("uid").value = uid

    # FN (formatted name)
    fn_val = fn.strip() if fn else "Unknown"
    card.add("fn").value = fn_val

    # N (structured name — split FN on last space)
    n = card.add("n")
    parts = fn_val.rsplit(" ", 1)
    if len(parts) == 2:
        n.value = vobject.vcard.Name(family=parts[1], given=parts[0])
    else:
        n.value = vobject.vcard.Name(family=fn_val, given="")

    # EMAIL (one per unique address)
    seen_emails: set[str] = set()
    for email in emails:
        email = email.strip()
        if email and email not in seen_emails:
            seen_emails.add(email)
            card.add("email").value = email

    # TEL (one per unique number)
    seen_phones: set[str] = set()
    for phone in phones:
        phone = phone.strip()
        if phone and phone not in seen_phones:
            seen_phones.add(phone)
            card.add("tel").value = phone

    # ORG
    if org and org.strip():
        card.add("org").value = [org.strip()]

    # NOTE
    if note and note.strip():
        card.add("note").value = note.strip()

    # REV
    if rev:
        card.add("rev").value = rev
    else:
        card.add("rev").value = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    return card.serialize()
