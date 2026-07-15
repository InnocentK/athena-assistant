"""
nextcloud_integration/client.py — Read-only Nextcloud integration.

Uses Nextcloud WebDAV (files) and OCS API (notes, activity, user info).
ALL operations are read-only. No uploads, no modifications, no deletes.

Environment variables:
  NEXTCLOUD_URL      — Base URL, e.g. https://cloud.example.com or http://192.168.1.10
  NEXTCLOUD_USERNAME — Nextcloud username
  NEXTCLOUD_PASSWORD — App password (recommended) or account password
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from urllib.parse import unquote
from xml.sax.saxutils import escape as _xml_escape
import xml.etree.ElementTree as ET

import requests
# M26.15: server-controlled XML is parsed with defusedxml (entity expansion /
# external refs rejected). Stdlib ET stays for Element construction only.
from defusedxml.ElementTree import fromstring as _safe_fromstring

# M26.15: use the shared app logger (was logging.getLogger(__name__), whose
# records skipped Athena's handler/formatter).
from core.logger import logger
from dav_status.store import get_status_store


class NextcloudConfigError(RuntimeError):
    pass


class NextcloudConnectionError(RuntimeError):
    pass



def _parse_multistatus(content: bytes):
    """Parse a WebDAV multistatus body with defusedxml (M26.15).

    Malformed or entity-defining XML from the server raises
    NextcloudConnectionError instead of propagating a parser internal.
    """
    try:
        return _safe_fromstring(content)
    except Exception as exc:  # noqa: BLE001 — any parse/defense failure
        raise NextcloudConnectionError(
            f"Server returned unparseable XML: {exc}"
        ) from exc


class NextcloudClient:
    """Read-only client for Nextcloud WebDAV and OCS APIs."""

    def __init__(self) -> None:
        url = os.environ.get("NEXTCLOUD_URL", "")
        username = os.environ.get("NEXTCLOUD_USERNAME", "")
        password = os.environ.get("NEXTCLOUD_PASSWORD", "")

        missing = [
            name
            for name, val in [
                ("NEXTCLOUD_URL", url),
                ("NEXTCLOUD_USERNAME", username),
                ("NEXTCLOUD_PASSWORD", password),
            ]
            if not val
        ]
        if missing:
            raise NextcloudConfigError(
                f"Missing required environment variables: {', '.join(missing)}"
            )

        self._base = url.rstrip("/")
        self._auth = (username, password)
        self._username = username
        # Do NOT connect at init

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, **kwargs) -> requests.Response:
        """Issue a GET request; raise NextcloudConnectionError on failure."""
        try:
            resp = requests.get(
                self._base + path,
                auth=self._auth,
                timeout=15,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise NextcloudConnectionError(f"GET {path} failed: {exc}") from exc

        if not resp.ok:
            raise NextcloudConnectionError(
                f"GET {path} returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        return resp

    def _propfind(self, path: str, depth: int = 1, body: bytes | None = None) -> requests.Response:
        """Issue a PROPFIND request; raise NextcloudConnectionError on non-207."""
        try:
            resp = requests.request(
                "PROPFIND",
                self._base + path,
                auth=self._auth,
                headers={
                    "Depth": str(depth),
                    "Content-Type": "application/xml",
                },
                data=body,
                timeout=15,
            )
        except requests.RequestException as exc:
            raise NextcloudConnectionError(f"PROPFIND {path} failed: {exc}") from exc

        if resp.status_code != 207:
            raise NextcloudConnectionError(
                f"PROPFIND {path} returned HTTP {resp.status_code} (expected 207): {resp.text[:200]}"
            )
        return resp

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_connection(self) -> dict:
        """Attempt a lightweight connection check using ping().

        Returns {"reachable": bool, "version": str, "error": str|None}.
        Updates the status store.
        """
        store = get_status_store()
        try:
            result = self.ping()
            if result.get("reachable"):
                store.record_success("nextcloud", item_counts={})
                return {"reachable": True, "version": result.get("version", ""), "error": None}
            else:
                err_msg = result.get("error", "Nextcloud not reachable")
                store.record_error("nextcloud", err_msg)
                return {"reachable": False, "version": "", "error": store.humanise_error(err_msg)}
        except Exception as exc:
            store.record_error("nextcloud", exc)
            return {"reachable": False, "version": "", "error": store.humanise_error(exc)}

    def ping(self) -> dict:
        """Check reachability by querying Nextcloud capabilities."""
        try:
            resp = self._get(
                "/ocs/v1.php/cloud/capabilities?format=json",
                headers={"OCS-APIREQUEST": "true"},
            )
            data = resp.json()
            version = (
                data.get("ocs", {})
                .get("data", {})
                .get("version", {})
                .get("string", "")
            )
            get_status_store().record_success("nextcloud")
            return {"reachable": True, "version": version}
        except Exception as exc:  # noqa: BLE001
            get_status_store().record_error("nextcloud", exc)
            return {"reachable": False, "error": str(exc)}

    def get_user_info(self) -> dict:
        """Return info about the authenticated user."""
        resp = self._get(
            "/ocs/v1.php/cloud/user?format=json",
            headers={"OCS-APIREQUEST": "true"},
        )
        data = resp.json().get("ocs", {}).get("data", {})
        quota = data.get("quota", {}) or {}
        return {
            "id": data.get("id", ""),
            "display_name": data.get("display-name") or data.get("displayname", ""),
            "email": data.get("email", ""),
            "quota_used": int(quota.get("used", 0) or 0),
            "quota_total": int(quota.get("total", 0) or 0),
        }

    def list_files(self, path: str = "/") -> list[dict]:
        """List files and folders via WebDAV PROPFIND."""
        try:
            return self._list_files_impl(path)
        except NextcloudConnectionError as exc:
            get_status_store().record_error("nextcloud", exc)
            raise
        except Exception as exc:
            get_status_store().record_error("nextcloud", exc)
            raise

    def _list_files_impl(self, path: str = "/") -> list[dict]:
        """Internal implementation of list_files."""
        dav_path = f"/remote.php/dav/files/{self._username}{path}"
        resp = self._propfind(dav_path, depth=1)

        ns = {"d": "DAV:"}
        root = _parse_multistatus(resp.content)
        responses = root.findall("d:response", ns)

        results = []
        for i, response in enumerate(responses):
            if i == 0:
                # Skip the first element — it's the directory itself
                continue

            href_el = response.find("d:href", ns)
            href = href_el.text if href_el is not None else ""
            decoded_href = unquote(href)

            # Name is the last segment of the URL
            name = decoded_href.rstrip("/").rsplit("/", 1)[-1]

            propstat = response.find("d:propstat/d:prop", ns)
            if propstat is None:
                propstat = ET.Element("prop")

            # Resource type
            resource_type = propstat.find("d:resourcetype", ns)
            is_collection = (
                resource_type is not None
                and resource_type.find("d:collection", ns) is not None
            )
            file_type = "folder" if is_collection else "file"

            # Size
            size_el = propstat.find("d:getcontentlength", ns)
            size = int(size_el.text) if size_el is not None and size_el.text else 0

            # Last modified
            lm_el = propstat.find("d:getlastmodified", ns)
            last_modified = lm_el.text if lm_el is not None else ""

            # Content type
            ct_el = propstat.find("d:getcontenttype", ns)
            content_type = ct_el.text if ct_el is not None else ""

            results.append(
                {
                    "name": name,
                    "path": decoded_href,
                    "type": file_type,
                    "size": size,
                    "last_modified": last_modified,
                    "content_type": content_type or "",
                }
            )

        get_status_store().record_success("nextcloud", item_counts={"files": len(results)})
        return results

    def read_file(self, path: str) -> dict:
        """Read the content of a file (text only, ≤2MB)."""
        dav_path = f"/remote.php/dav/files/{self._username}{path}"

        # M26.9: stream the body and enforce the size cap WHILE reading, so an
        # oversized remote file is never fully buffered into memory first.
        max_bytes = 2 * 1024 * 1024
        try:
            with requests.get(
                self._base + dav_path,
                auth=self._auth,
                timeout=15,
                stream=True,
            ) as resp:
                if not resp.ok:
                    raise NextcloudConnectionError(
                        f"read_file {path} returned HTTP {resp.status_code}"
                    )
                ct = resp.headers.get("Content-Type", "")
                chunks: list[bytes] = []
                size = 0
                too_large = False
                for chunk in resp.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > max_bytes:
                        too_large = True
                        break
                    chunks.append(chunk)
        except NextcloudConnectionError:
            raise
        except requests.RequestException as exc:
            raise NextcloudConnectionError(f"read_file {path} failed: {exc}") from exc

        if too_large:
            return {"path": path, "content": None, "note": "file too large (>2MB)"}

        content_bytes = b"".join(chunks)

        # Decide if text-decodable
        ct_lower = ct.split(";")[0].strip().lower()
        is_text = (
            ct_lower.startswith("text/")
            or ct_lower in ("application/json", "application/xml")
        )

        if is_text:
            text = content_bytes.decode("utf-8", errors="replace")
            return {
                "path": path,
                "content": text,
                "content_type": ct,
                "size": size,
            }
        else:
            return {
                "path": path,
                "content": None,
                "content_type": ct,
                "size": size,
                "note": "binary file — content omitted",
            }

    def search_files(self, query: str, path: str = "/") -> list[dict]:
        """Search files by name using DASL; fall back to local filtering."""
        # M26.15: escape interpolations — an unescaped &/<​/> made the body
        # malformed XML, silently degrading to the local-filter fallback.
        dav_root = _xml_escape(f"/remote.php/dav/files/{self._username}{path}")
        query = _xml_escape(query)
        body = f"""<?xml version="1.0" encoding="UTF-8"?>
<d:searchrequest xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">
  <d:basicsearch>
    <d:select><d:prop><d:displayname/><d:getcontentlength/><d:getlastmodified/><d:getcontenttype/></d:prop></d:select>
    <d:from><d:scope><d:href>{dav_root}</d:href><d:depth>infinity</d:depth></d:scope></d:from>
    <d:where><d:like><d:prop><d:displayname/></d:prop><d:literal>%{query}%</d:literal></d:like></d:where>
    <d:limit><d:nresults>50</d:nresults></d:limit>
  </d:basicsearch>
</d:searchrequest>""".encode("utf-8")

        try:
            resp = requests.request(
                "SEARCH",
                self._base + "/remote.php/dav/",
                auth=self._auth,
                headers={"Content-Type": "application/xml"},
                data=body,
                timeout=15,
            )
        except requests.RequestException as exc:
            logger.warning("DASL SEARCH failed (%s); falling back to local filter.", exc)
            resp = None

        if resp is None or resp.status_code != 207:
            logger.warning(
                "DASL SEARCH returned %s; falling back to list_files filter.",
                resp.status_code if resp is not None else "error",
            )
            all_files = self.list_files(path)
            return [f for f in all_files if query.lower() in f["name"].lower()]

        # Parse 207 multistatus — same logic as list_files
        ns = {"d": "DAV:"}
        root = _parse_multistatus(resp.content)
        responses = root.findall("d:response", ns)

        results = []
        for response in responses:
            href_el = response.find("d:href", ns)
            href = href_el.text if href_el is not None else ""
            decoded_href = unquote(href)
            name = decoded_href.rstrip("/").rsplit("/", 1)[-1]

            propstat = response.find("d:propstat/d:prop", ns)
            if propstat is None:
                propstat = ET.Element("prop")

            resource_type = propstat.find("d:resourcetype", ns)
            is_collection = (
                resource_type is not None
                and resource_type.find("d:collection", ns) is not None
            )
            file_type = "folder" if is_collection else "file"

            size_el = propstat.find("d:getcontentlength", ns)
            size = int(size_el.text) if size_el is not None and size_el.text else 0

            lm_el = propstat.find("d:getlastmodified", ns)
            last_modified = lm_el.text if lm_el is not None else ""

            ct_el = propstat.find("d:getcontenttype", ns)
            content_type = ct_el.text if ct_el is not None else ""

            results.append(
                {
                    "name": name,
                    "path": decoded_href,
                    "type": file_type,
                    "size": size,
                    "last_modified": last_modified,
                    "content_type": content_type or "",
                }
            )

        return results

    def list_notes(self) -> list[dict]:
        """List Nextcloud Notes (requires Notes app). Returns [] if not installed."""
        try:
            resp = self._get(
                "/index.php/apps/notes/api/v1/notes?exclude=content",
                headers={"OCS-APIREQUEST": "true"},
            )
        except NextcloudConnectionError as exc:
            # 404 means Notes app is not installed
            if "404" in str(exc):
                logger.warning("Nextcloud Notes app not installed (404). Returning empty list.")
                return []
            raise

        notes = resp.json()
        if not isinstance(notes, list):
            return []

        return [
            {
                "id": n.get("id"),
                "title": n.get("title", ""),
                "category": n.get("category", ""),
                "modified": n.get("modified"),
                "favorite": n.get("favorite", False),
            }
            for n in notes
        ]

    def get_note(self, note_id: int) -> dict:
        """Retrieve a single note by ID."""
        resp = self._get(f"/index.php/apps/notes/api/v1/notes/{note_id}")
        n = resp.json()
        return {
            "id": n.get("id"),
            "title": n.get("title", ""),
            "category": n.get("category", ""),
            "content": n.get("content", ""),
            "modified": n.get("modified"),
            "favorite": n.get("favorite", False),
        }

    def list_recent_activity(self, limit: int = 20) -> list[dict]:
        """Return recent activity entries. Returns [] if Activity app not available."""
        try:
            resp = self._get(
                f"/ocs/v1.php/apps/activity/api/v2/activity/all?limit={limit}&format=json",
                headers={"OCS-APIREQUEST": "true"},
            )
        except NextcloudConnectionError as exc:
            logger.warning(
                "Nextcloud Activity app not available (%s). Returning empty list.", exc
            )
            return []

        try:
            items = resp.json().get("ocs", {}).get("data", [])
        except Exception:  # noqa: BLE001
            return []

        if not isinstance(items, list):
            return []

        results = []
        for item in items:
            # Convert Unix timestamp to ISO string
            ts = item.get("datetime") or item.get("timestamp")
            if isinstance(ts, int):
                ts_iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            else:
                ts_iso = str(ts) if ts else ""

            results.append(
                {
                    "activity_id": item.get("activity_id"),
                    "type": item.get("type", ""),
                    "subject": item.get("subject", ""),
                    "message": item.get("message", ""),
                    "object_type": item.get("object_type", ""),
                    "object_name": item.get("object_name", ""),
                    "timestamp": ts_iso,
                }
            )

        return results
