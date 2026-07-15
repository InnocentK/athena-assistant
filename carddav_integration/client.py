"""
carddav_integration/client.py — CardDAV client for Mailbox.org (or any CardDAV server).

Credentials (same as CalDAV, or separate set):
  CARDDAV_URL      — CardDAV base URL, e.g. https://dav.mailbox.org
  CARDDAV_USERNAME — Username (email address)
  CARDDAV_PASSWORD — App password or account password

SAFETY RULE: Duplicate detection runs locally and never writes to the server.
Write-back (commit_merge, delete_contact) requires explicit human API calls.
Staged merges are stored in data/carddav_staged/ as JSON files pending approval.
"""

from __future__ import annotations

import json
import os
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests
# M26.15: server-controlled multistatus XML parses via defusedxml (entity
# expansion / external refs rejected). Stdlib ET stays for namespaces only.
from defusedxml.ElementTree import fromstring as _safe_fromstring

from carddav_integration.vcard_helpers import build_vcard, parse_vcard
from core.config import APP_ROOT
from core.logger import logger
from core.urlguard import DAVSecurityError, ensure_same_origin
from dav_status.store import get_status_store

# M26.12: every outbound HTTP call sets an explicit socket timeout so a hung
# server can't pin a to_thread worker forever (asyncio.wait_for bounds the
# route, not the thread). Matches nextcloud_integration's established value.
_HTTP_TIMEOUT = 15

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class CardDAVConfigError(RuntimeError):
    pass


class CardDAVConnectionError(RuntimeError):
    pass


class StagedMergeNotFoundError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# XML namespace map
# ---------------------------------------------------------------------------
_NS = {
    "d": "DAV:",
    "card": "urn:ietf:params:xml:ns:carddav",
}

# Register namespaces to avoid ns0/ns1 prefixes in output
ET.register_namespace("d", "DAV:")
ET.register_namespace("card", "urn:ietf:params:xml:ns:carddav")


# ---------------------------------------------------------------------------
# CardDAVClient
# ---------------------------------------------------------------------------


class CardDAVClient:
    """CardDAV client with safe merge workflow.

    Read operations (list, search, detect_duplicates) are always safe.
    Write operations (commit_merge, delete_contact) require explicit human API calls.
    Staged merges are stored locally in data/carddav_staged/.
    """

    def __init__(self) -> None:
        self._url = os.environ.get("CARDDAV_URL", "").rstrip("/")
        self._username = os.environ.get("CARDDAV_USERNAME", "")
        self._password = os.environ.get("CARDDAV_PASSWORD", "")

        missing = [
            name
            for name, val in (
                ("CARDDAV_URL", self._url),
                ("CARDDAV_USERNAME", self._username),
                ("CARDDAV_PASSWORD", self._password),
            )
            if not val
        ]
        if missing:
            raise CardDAVConfigError(
                f"Missing required environment variable(s): {', '.join(missing)}"
            )

        self._staged_dir = APP_ROOT / "data" / "carddav_staged"

    def _ensure_staged_dir(self) -> None:
        """Create the staged merges directory if it doesn't exist."""
        self._staged_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Connection check
    # ------------------------------------------------------------------

    def check_connection(self) -> dict:
        """Attempt a lightweight connection check.

        Returns {"reachable": bool, "address_book_count": int, "error": str|None}.
        Updates the status store.
        """
        store = get_status_store()
        try:
            books = self.list_address_books()
            store.record_success("carddav", item_counts={"address_books": len(books)})
            return {"reachable": True, "address_book_count": len(books), "error": None}
        except Exception as exc:
            store.record_error("carddav", exc)
            return {"reachable": False, "address_book_count": 0, "error": store.humanise_error(exc)}

    def _request(
        self, method: str, url: str, check: bool = True, **kwargs
    ) -> requests.Response:
        """Internal helper: perform an authenticated HTTP request.

        Every outbound CardDAV request flows through here (single chokepoint).
        A default socket timeout is always applied (M26.12); callers may
        override via ``timeout=``.

        Raises CardDAVConnectionError on network error. With ``check=True``
        (default) a non-2xx response also raises; with ``check=False`` the
        response is returned for the caller to inspect.

        Raises DAVSecurityError (→ HTTP 400) if ``url`` targets a different
        origin than the configured CARDDAV_URL (M26.13 SSRF guard).
        """
        ensure_same_origin(url, self._url, "CardDAV")
        kwargs.setdefault("timeout", _HTTP_TIMEOUT)
        try:
            response = requests.request(
                method,
                url,
                auth=(self._username, self._password),
                **kwargs,
            )
        except requests.RequestException as exc:
            raise CardDAVConnectionError(
                f"Network error during {method} {url}: {exc}"
            ) from exc

        if check and not response.ok:
            raise CardDAVConnectionError(
                f"CardDAV server returned {response.status_code} for {method} {url}: {response.text[:200]}"
            )
        return response

    # ------------------------------------------------------------------
    # Address book discovery
    # ------------------------------------------------------------------

    def list_address_books(self) -> list[dict]:
        """PROPFIND the CardDAV base URL to discover address books.

        Returns list of {name, url, description}.
        """
        body = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">
  <d:prop>
    <d:displayname/>
    <d:resourcetype/>
    <d:current-user-principal/>
  </d:prop>
</d:propfind>"""

        try:
            response = self._request(
                "PROPFIND",
                self._url,
                headers={
                    "Depth": "1",
                    "Content-Type": "application/xml",
                },
                data=body.encode("utf-8"),
            )

            root = _safe_fromstring(response.text)
            address_books: list[dict] = []

            for response_el in root.findall("d:response", _NS):
                # Check if resourcetype contains addressbook
                resourcetype = response_el.find(".//d:resourcetype", _NS)
                if resourcetype is None:
                    continue
                if resourcetype.find("card:addressbook", _NS) is None:
                    continue

                href_el = response_el.find("d:href", _NS)
                href = href_el.text.strip() if href_el is not None else ""

                displayname_el = response_el.find(".//d:displayname", _NS)
                name = displayname_el.text.strip() if (displayname_el is not None and displayname_el.text) else ""

                # Build full URL from href
                if href.startswith("http"):
                    full_url = href
                else:
                    from urllib.parse import urljoin
                    full_url = urljoin(self._url + "/", href.lstrip("/"))

                address_books.append({
                    "name": name,
                    "url": full_url,
                    "description": "",
                })

            get_status_store().record_success("carddav", item_counts={"address_books": len(address_books)})
            return address_books
        except (CardDAVConnectionError, DAVSecurityError) as exc:
            get_status_store().record_error("carddav", exc)
            raise
        except Exception as exc:
            logger.error("list_address_books failed: %s", exc)
            get_status_store().record_error("carddav", exc)
            raise CardDAVConnectionError(f"list_address_books failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Contact listing and search
    # ------------------------------------------------------------------

    def list_contacts(self, address_book_url: str) -> list[dict]:
        """Fetch all contacts from an address book using REPORT.

        Returns list of {uid, href, etag, fn, email, phone, org, note}.
        """
        body = """<?xml version="1.0" encoding="utf-8"?>
<card:addressbook-query xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">
  <d:prop>
    <d:getetag/>
    <card:address-data/>
  </d:prop>
</card:addressbook-query>"""

        try:
            response = self._request(
                "REPORT",
                address_book_url,
                headers={
                    "Depth": "1",
                    "Content-Type": "application/xml",
                },
                data=body.encode("utf-8"),
            )

            root = _safe_fromstring(response.text)
            contacts: list[dict] = []

            for response_el in root.findall("d:response", _NS):
                href_el = response_el.find("d:href", _NS)
                href = href_el.text.strip() if href_el is not None else ""

                etag_el = response_el.find(".//d:getetag", _NS)
                etag = etag_el.text.strip() if (etag_el is not None and etag_el.text) else ""

                address_data_el = response_el.find(".//card:address-data", _NS)
                if address_data_el is None or not address_data_el.text:
                    continue

                vcard_str = address_data_el.text
                parsed = parse_vcard(vcard_str)

                contacts.append({
                    "uid": parsed["uid"],
                    "href": href,
                    "etag": etag,
                    "fn": parsed["fn"],
                    "email": parsed["email"],
                    "phone": parsed["phone"],
                    "org": parsed["org"],
                    "note": parsed["note"],
                })

            get_status_store().record_success(
                "carddav",
                item_counts={"contacts": len(contacts)},
                etags={address_book_url: ""},
            )
            return contacts
        except (CardDAVConnectionError, DAVSecurityError) as exc:
            get_status_store().record_error("carddav", exc)
            raise
        except Exception as exc:
            logger.error("list_contacts failed: %s", exc)
            get_status_store().record_error("carddav", exc)
            raise CardDAVConnectionError(f"list_contacts failed: {exc}") from exc

    def search_contacts(self, address_book_url: str, query: str) -> list[dict]:
        """Search contacts locally by name, email, or org (case-insensitive).

        Calls list_contacts() and filters results. No server-side filtering.
        """
        all_contacts = self.list_contacts(address_book_url)
        q = query.lower()
        return [
            c for c in all_contacts
            if q in c["fn"].lower()
            or q in c["email"].lower()
            or q in c["org"].lower()
        ]

    # ------------------------------------------------------------------
    # Duplicate detection (read-only, no server writes)
    # ------------------------------------------------------------------

    def detect_duplicates(self, address_book_url: str) -> list[dict]:
        """Detect duplicate contacts locally.

        Groups by normalised name AND by email (if present).
        Returns list of duplicate groups: [{reason, contacts: [...]}].
        Only groups with 2+ contacts are returned.
        A group appears once even if matched by both name and email.

        SAFETY: This method NEVER writes to the server.
        """
        contacts = self.list_contacts(address_book_url)

        # Group by normalised name
        name_groups: dict[str, list[dict]] = {}
        for contact in contacts:
            key = contact["fn"].lower().strip()
            if key:
                name_groups.setdefault(key, []).append(contact)

        # Group by email
        email_groups: dict[str, list[dict]] = {}
        for contact in contacts:
            email = contact["email"].lower().strip()
            if email:
                email_groups.setdefault(email, []).append(contact)

        # Collect duplicate groups — track already-included href sets to avoid repeats
        seen_href_sets: list[frozenset] = []
        result: list[dict] = []

        def _add_group(reason: str, group: list[dict]) -> None:
            if len(group) < 2:
                return
            hrefs = frozenset(c["href"] for c in group)
            # Avoid duplicate groups
            for seen in seen_href_sets:
                if hrefs == seen:
                    return
            seen_href_sets.append(hrefs)
            result.append({"reason": reason, "contacts": group})

        for group in name_groups.values():
            _add_group("name_match", group)

        for group in email_groups.values():
            _add_group("email_match", group)

        return result

    # ------------------------------------------------------------------
    # Staged merge workflow
    # ------------------------------------------------------------------

    def _fetch_vcard_str(self, href: str) -> str:
        """Fetch the raw vCard string for a given href."""
        # Build full URL if href is relative
        if href.startswith("http"):
            url = href
        else:
            from urllib.parse import urljoin
            url = urljoin(self._url + "/", href.lstrip("/"))

        response = self._request("GET", url)
        return response.text

    def stage_merge(
        self,
        address_book_url: str,
        contact_hrefs: list[str],
        merged_data: dict,
    ) -> dict:
        """Build a proposed merged vCard and save it locally for human approval.

        SAFETY: This method never writes to the server.

        Args:
            address_book_url: URL of the address book containing the contacts.
            contact_hrefs: List of href strings identifying contacts to merge (must be 2+).
            merged_data: Partial override dict with keys: fn, email, phone, org, note.

        Returns:
            Staging record (metadata + summary, without full vcard string).
        """
        if len(contact_hrefs) < 2:
            raise ValueError("stage_merge requires at least 2 contact_hrefs to merge")

        # Fetch source vCards
        source_vcards: list[dict] = []
        for href in contact_hrefs:
            vcard_str = self._fetch_vcard_str(href)
            parsed = parse_vcard(vcard_str)
            source_vcards.append(parsed)

        # Build merged fields
        # FN
        fn = merged_data.get("fn", "")
        if not fn:
            fn = next((c["fn"] for c in source_vcards if c["fn"]), "")

        # EMAIL: use override or collect all unique emails
        if "email" in merged_data and merged_data["email"]:
            emails = [merged_data["email"]]
        else:
            seen: set[str] = set()
            emails = []
            for c in source_vcards:
                e = c["email"].strip()
                if e and e not in seen:
                    seen.add(e)
                    emails.append(e)

        # PHONE: use override or collect all unique phones
        if "phone" in merged_data and merged_data["phone"]:
            phones = [merged_data["phone"]]
        else:
            seen_phones: set[str] = set()
            phones = []
            for c in source_vcards:
                p = c["phone"].strip()
                if p and p not in seen_phones:
                    seen_phones.add(p)
                    phones.append(p)

        # ORG
        org = merged_data.get("org", "")
        if not org:
            org = next((c["org"] for c in source_vcards if c["org"]), "")

        # NOTE
        note = merged_data.get("note", "")
        if not note:
            notes = [c["note"] for c in source_vcards if c["note"]]
            note = "\n---\n".join(notes) if notes else ""

        # New UID
        new_uid = str(uuid.uuid4())

        # REV timestamp
        rev = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        # Build vCard string
        merged_vcard = build_vcard(
            uid=new_uid,
            fn=fn,
            emails=emails,
            phones=phones,
            org=org,
            note=note,
            rev=rev,
        )

        # Build staging record
        staged_merge_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()

        merged_summary = {
            "fn": fn,
            "email": emails[0] if emails else "",
            "phone": phones[0] if phones else "",
            "org": org,
            "note": note,
        }

        staging_record = {
            "staged_merge_id": staged_merge_id,
            "address_book_url": address_book_url,
            "source_hrefs": contact_hrefs,
            "merged_vcard": merged_vcard,
            "merged_summary": merged_summary,
            "created_at": now_iso,
            "status": "pending",
        }

        # Save to disk
        self._ensure_staged_dir()
        staging_file = self._staged_dir / f"{staged_merge_id}.json"
        staging_file.write_text(json.dumps(staging_record, indent=2), encoding="utf-8")

        logger.info("Staged merge %s created (%d sources)", staged_merge_id, len(contact_hrefs))

        # Return metadata + summary (without full vcard string)
        return {
            "staged_merge_id": staged_merge_id,
            "address_book_url": address_book_url,
            "source_hrefs": contact_hrefs,
            "merged_summary": merged_summary,
            "created_at": now_iso,
            "status": "pending",
        }

    def list_staged_merges(self) -> list[dict]:
        """List all staged merge proposals (without merged_vcard field)."""
        self._ensure_staged_dir()
        results: list[dict] = []
        for f in sorted(self._staged_dir.glob("*.json")):
            try:
                record = json.loads(f.read_text(encoding="utf-8"))
                # Omit the large vcard string from the list response
                record.pop("merged_vcard", None)
                results.append(record)
            except Exception as exc:
                logger.warning("Failed to read staged merge file %s: %s", f, exc)
        return results

    def get_staged_merge(self, staged_merge_id: str) -> dict:
        """Get the full staging record including merged_vcard.

        Raises StagedMergeNotFoundError if not found.
        """
        self._ensure_staged_dir()
        staging_file = self._staged_dir / f"{staged_merge_id}.json"
        if not staging_file.exists():
            raise StagedMergeNotFoundError(
                f"Staged merge not found: {staged_merge_id!r}"
            )
        return json.loads(staging_file.read_text(encoding="utf-8"))

    def commit_merge(self, staged_merge_id: str) -> dict:
        """Write the merged vCard to the server and delete source contacts.

        THIS IS THE ONLY WRITE OPERATION FOR CONTACTS.
        Requires a staged_merge_id from a prior stage_merge() call.

        Steps:
          1. Load the staging record
          2. PUT merged_vcard to address_book_url/<new_uid>.vcf
          3. DELETE each source contact (one at a time, 404 ignored)
          4. Mark staging file as "committed"

        Returns: {committed, staged_merge_id, new_href}
        """
        record = self.get_staged_merge(staged_merge_id)

        if record.get("status") == "committed":
            raise ValueError(f"Staged merge {staged_merge_id!r} is already committed")
        if record.get("status") == "discarded":
            raise ValueError(f"Staged merge {staged_merge_id!r} has been discarded")

        merged_vcard = record["merged_vcard"]
        address_book_url = record["address_book_url"]
        source_hrefs = record["source_hrefs"]

        # Extract UID from the vcard string
        new_uid = None
        try:
            import vobject as _vobject
            parsed = _vobject.readOne(merged_vcard)
            if hasattr(parsed, "uid"):
                new_uid = str(parsed.uid.value).strip()
        except Exception:
            pass
        if not new_uid:
            new_uid = str(uuid.uuid4())

        # Build the PUT URL
        ab_url = address_book_url.rstrip("/")
        new_vcf_path = f"{new_uid}.vcf"
        new_href = f"{ab_url}/{new_vcf_path}"

        logger.info(
            "commit_merge: PUT merged vCard to %s (staged_merge_id=%s)",
            new_href,
            staged_merge_id,
        )

        # PUT the merged vCard
        self._request(
            "PUT",
            new_href,
            headers={"Content-Type": "text/vcard"},
            data=merged_vcard.encode("utf-8"),
        )

        # DELETE source contacts (one at a time, ignore 404)
        for href in source_hrefs:
            if href.startswith("http"):
                del_url = href
            else:
                from urllib.parse import urljoin
                del_url = urljoin(self._url + "/", href.lstrip("/"))

            try:
                resp = self._request("DELETE", del_url, check=False)
                if resp.status_code == 404:
                    logger.info("DELETE %s → 404 (already gone), skipping", del_url)
                elif not resp.ok:
                    logger.warning(
                        "DELETE %s → %s (ignored)", del_url, resp.status_code
                    )
                else:
                    logger.info("Deleted source contact %s", del_url)
            except CardDAVConnectionError as exc:
                logger.warning("Failed to delete source contact %s: %s", del_url, exc)

        # Mark staging file as committed
        record["status"] = "committed"
        staging_file = self._staged_dir / f"{staged_merge_id}.json"
        staging_file.write_text(json.dumps(record, indent=2), encoding="utf-8")

        logger.info(
            "commit_merge complete: staged_merge_id=%s, new_href=%s",
            staged_merge_id,
            new_href,
        )

        return {
            "committed": True,
            "staged_merge_id": staged_merge_id,
            "new_href": new_href,
        }

    def discard_staged_merge(self, staged_merge_id: str) -> bool:
        """Mark a staged merge as discarded (no server writes).

        Returns True; raises StagedMergeNotFoundError if not found.
        """
        record = self.get_staged_merge(staged_merge_id)
        record["status"] = "discarded"
        staging_file = self._staged_dir / f"{staged_merge_id}.json"
        staging_file.write_text(json.dumps(record, indent=2), encoding="utf-8")
        logger.info("Staged merge %s discarded", staged_merge_id)
        return True

    # ------------------------------------------------------------------
    # Contact deletion (human-initiated only)
    # ------------------------------------------------------------------

    def delete_contact(self, address_book_url: str, href: str) -> bool:
        """Delete a single contact by href.

        THIS IS A WRITE OPERATION — only call when explicitly requested by a human.

        Returns True on success (200 or 204).
        Raises CardDAVConnectionError on failure.
        """
        if href.startswith("http"):
            del_url = href
        else:
            from urllib.parse import urljoin
            del_url = urljoin(self._url + "/", href.lstrip("/"))

        logger.info("delete_contact: DELETE %s", del_url)

        # Network errors raise CardDAVConnectionError inside _request;
        # status handling (200/204/other) stays here.
        resp = self._request("DELETE", del_url, check=False)

        if resp.status_code in (200, 204):
            logger.info("Deleted contact %s → %s", del_url, resp.status_code)
            return True

        raise CardDAVConnectionError(
            f"Failed to delete contact {del_url}: HTTP {resp.status_code}"
        )
