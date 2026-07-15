"""
caldav_integration/client.py — CalDAV client for Mailbox.org (or any CalDAV server).

Credentials are read from environment variables:
  CALDAV_URL      — CalDAV base URL, e.g. https://dav.mailbox.org
  CALDAV_USERNAME — Username (Mailbox.org email address)
  CALDAV_PASSWORD — App password or account password

The client is lazy: it connects only on first use and caches the
caldav.DAVClient + principal object.  Call .reset() to force reconnect.

All methods return plain Python dicts / lists — no caldav objects
are exposed outside this module.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from core.logger import logger
from core.urlguard import ensure_same_origin
from dav_io.ics_io import escape_ics_text
from dav_status.store import get_status_store

# M26.12: transport-level timeout passed to caldav.DAVClient (forwarded to its
# HTTP session). Matches the value used by the other integration clients.
_CONNECT_TIMEOUT = 15


class CalDAVConfigError(RuntimeError):
    pass


class CalDAVConnectionError(RuntimeError):
    pass


class CalDAVClient:
    """Lazy CalDAV client.  Connects on first use and caches the connection."""

    def __init__(self) -> None:
        self._url = os.environ.get("CALDAV_URL", "")
        self._username = os.environ.get("CALDAV_USERNAME", "")
        self._password = os.environ.get("CALDAV_PASSWORD", "")

        missing = [
            name
            for name, val in (
                ("CALDAV_URL", self._url),
                ("CALDAV_USERNAME", self._username),
                ("CALDAV_PASSWORD", self._password),
            )
            if not val
        ]
        if missing:
            raise CalDAVConfigError(
                f"Missing required environment variable(s): {', '.join(missing)}"
            )

        # Any: these hold caldav library objects once connected (the library
        # is untyped); annotated so mypy doesn't infer the None-only type.
        self._client: Any = None
        self._principal: Any = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        """Establish a CalDAV connection and cache the client + principal."""
        try:
            import caldav  # noqa: PLC0415

            client = caldav.DAVClient(
                url=self._url,
                username=self._username,
                password=self._password,
                # M26.12: explicit socket timeout — asyncio.wait_for bounds the
                # route but can't cancel the worker thread; without this a hung
                # server pins a to_thread executor slot forever.
                timeout=_CONNECT_TIMEOUT,
            )
            principal = client.principal()
            self._client = client
            self._principal = principal
            logger.info("CalDAV connected to %s", self._url)
        except Exception as exc:
            logger.error("CalDAV connection failed: %s", exc)
            raise CalDAVConnectionError(
                f"Failed to connect to CalDAV server at {self._url!r}: {exc}"
            ) from exc

    def _ensure_connected(self) -> None:
        """Connect only if not already connected."""
        if self._client is None or self._principal is None:
            self._connect()

    def _check_url(self, calendar_url: str) -> None:
        """M26.13 SSRF guard: reject calendar URLs on any other origin.

        Must run BEFORE the broad ``except Exception → CalDAVConnectionError``
        wrappers so DAVSecurityError survives to the app-level 400 handler.
        """
        ensure_same_origin(calendar_url, self._url, "CalDAV")

    def reset(self) -> None:
        """Clear cached connection, forcing reconnect on next call."""
        self._client = None
        self._principal = None

    # ------------------------------------------------------------------
    # Connection check
    # ------------------------------------------------------------------

    def check_connection(self) -> dict:
        """
        Attempt a lightweight connection check.
        Returns {"reachable": bool, "calendar_count": int, "error": str|None}
        Updates the status store.
        """
        store = get_status_store()
        try:
            self._ensure_connected()
            cals = self.list_calendars()
            store.record_success("caldav", item_counts={"calendars": len(cals)})
            return {"reachable": True, "calendar_count": len(cals), "error": None}
        except Exception as exc:
            store.record_error("caldav", exc)
            return {"reachable": False, "calendar_count": 0, "error": store.humanise_error(exc)}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_calendars(self) -> list[dict]:
        """Return a list of calendars on the CalDAV server.

        Each dict has keys: name, url, color, description.
        """
        try:
            self._ensure_connected()
            calendars = self._principal.calendars()
            result = []
            for cal in calendars:
                props = getattr(cal, "props", {}) or {}
                name = ""
                color = ""
                description = ""
                try:
                    name = str(cal.name) if cal.name else ""
                except Exception:  # noqa: BLE001
                    pass
                try:
                    color = str(props.get("{http://apple.com/ns/ical/}calendar-color", "")) or ""
                except Exception:  # noqa: BLE001
                    pass
                try:
                    description = str(cal.get_properties(["{DAV:}description"]).get("{DAV:}description", "")) or ""
                except Exception:  # noqa: BLE001
                    pass
                result.append(
                    {
                        "name": name,
                        "url": str(cal.url),
                        "color": color,
                        "description": description,
                    }
                )
            get_status_store().record_success("caldav", item_counts={"calendars": len(result)})
            return result
        except CalDAVConnectionError as exc:
            get_status_store().record_error("caldav", exc)
            raise
        except Exception as exc:
            logger.error("list_calendars failed: %s", exc)
            get_status_store().record_error("caldav", exc)
            raise CalDAVConnectionError(f"list_calendars failed: {exc}") from exc

    def list_events(self, calendar_url: str, days_ahead: int = 30) -> list[dict]:
        """Return upcoming events from now to now + days_ahead days.

        Each dict: {uid, summary, dtstart, dtend, location, description, all_day}
        """
        self._check_url(calendar_url)
        try:
            self._ensure_connected()
            import caldav  # noqa: PLC0415

            cal = caldav.Calendar(client=self._client, url=calendar_url)
            now = datetime.now(tz=timezone.utc)
            end = now + timedelta(days=days_ahead)
            events = cal.date_search(start=now, end=end, expand=True)

            result = []
            for event in events:
                try:
                    vevent = event.vobject_instance.vevent
                    uid = _get_str(vevent, "uid")
                    summary = _get_str(vevent, "summary")
                    location = _get_str(vevent, "location")
                    description = _get_str(vevent, "description")

                    dtstart_val = vevent.dtstart.value if hasattr(vevent, "dtstart") else None
                    dtend_val = vevent.dtend.value if hasattr(vevent, "dtend") else None

                    all_day = isinstance(dtstart_val, date) and not isinstance(dtstart_val, datetime)

                    result.append(
                        {
                            "uid": uid,
                            "summary": summary,
                            "dtstart": _serialise_date(dtstart_val),
                            "dtend": _serialise_date(dtend_val),
                            "location": location,
                            "description": description,
                            "all_day": all_day,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Skipping malformed event: %s", exc)

            # Try to get ETag for the calendar
            etag = ""
            try:
                import caldav as caldav_lib  # noqa: PLC0415
                cal_obj = caldav_lib.Calendar(client=self._client, url=calendar_url)
                props = cal_obj.get_properties([caldav_lib.dav.GetEtag()])
                etag = str(props.get("{DAV:}getetag", ""))
            except Exception:  # noqa: BLE001
                etag = ""

            get_status_store().record_success(
                "caldav",
                item_counts={"events": len(result)},
                etags={calendar_url: etag},
            )
            return result
        except CalDAVConnectionError as exc:
            get_status_store().record_error("caldav", exc)
            raise
        except Exception as exc:
            logger.error("list_events failed: %s", exc)
            get_status_store().record_error("caldav", exc)
            raise CalDAVConnectionError(f"list_events failed: {exc}") from exc

    def list_tasks(self, calendar_url: str) -> list[dict]:
        """Return all VTODO items from a calendar.

        Each dict: {uid, summary, status, due, priority, description}
        """
        self._check_url(calendar_url)
        try:
            self._ensure_connected()
            import caldav  # noqa: PLC0415

            cal = caldav.Calendar(client=self._client, url=calendar_url)
            todos = cal.todos()

            result = []
            for todo in todos:
                try:
                    vtodo = todo.vobject_instance.vtodo
                    uid = _get_str(vtodo, "uid")
                    summary = _get_str(vtodo, "summary")
                    status = _get_str(vtodo, "status")
                    description = _get_str(vtodo, "description")

                    due_val = vtodo.due.value if hasattr(vtodo, "due") else None
                    priority_val = None
                    if hasattr(vtodo, "priority"):
                        try:
                            priority_val = int(vtodo.priority.value)
                        except Exception:  # noqa: BLE001
                            pass

                    result.append(
                        {
                            "uid": uid,
                            "summary": summary,
                            "status": status,
                            "due": _serialise_date(due_val),
                            "priority": priority_val,
                            "description": description,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Skipping malformed task: %s", exc)

            get_status_store().record_success("caldav", item_counts={"tasks": len(result)})
            return result
        except CalDAVConnectionError as exc:
            get_status_store().record_error("caldav", exc)
            raise
        except Exception as exc:
            logger.error("list_tasks failed: %s", exc)
            get_status_store().record_error("caldav", exc)
            raise CalDAVConnectionError(f"list_tasks failed: {exc}") from exc

    def create_task(
        self,
        calendar_url: str,
        summary: str,
        due: str | None = None,
        priority: int | None = None,
        description: str = "",
    ) -> dict:
        """Create a VTODO on the CalDAV server and return it as a dict.

        This is the ONLY write operation in this integration.

        Args:
            calendar_url: URL of the target calendar.
            summary: Task title.
            due: ISO date string, e.g. "2026-06-15", or None.
            priority: RFC 5545 priority 1–9 (1 = highest), or None.
            description: Free-text description.

        Returns:
            The created task dict with keys: uid, summary, status, due, priority, description.
        """
        self._check_url(calendar_url)
        try:
            self._ensure_connected()
            import caldav  # noqa: PLC0415

            task_uid = str(uuid.uuid4())
            now_stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")

            lines = [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "PRODID:-//Athena Assistant//CalDAV Integration//EN",
                "BEGIN:VTODO",
                f"UID:{task_uid}",
                f"DTSTAMP:{now_stamp}",
                f"SUMMARY:{escape_ics_text(summary)}",  # M26.9: RFC 5545 escaping
                "STATUS:NEEDS-ACTION",
            ]
            if due:
                # due is expected as ISO date string YYYY-MM-DD
                due_formatted = due.replace("-", "")
                lines.append(f"DUE;VALUE=DATE:{due_formatted}")
            if priority is not None:
                lines.append(f"PRIORITY:{priority}")
            if description:
                lines.append(f"DESCRIPTION:{escape_ics_text(description)}")  # M26.9
            lines += ["END:VTODO", "END:VCALENDAR"]

            ical_data = "\r\n".join(lines) + "\r\n"

            cal = caldav.Calendar(client=self._client, url=calendar_url)
            cal.save_todo(ical_data)

            return {
                "uid": task_uid,
                "summary": summary,
                "status": "NEEDS-ACTION",
                "due": due or "",
                "priority": priority,
                "description": description,
            }
        except CalDAVConnectionError:
            raise
        except Exception as exc:
            logger.error("create_task failed: %s", exc)
            raise CalDAVConnectionError(f"create_task failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_str(component, attr: str) -> str:
    """Safely get a string value from a vobject component attribute."""
    try:
        val = getattr(component, attr, None)
        if val is None:
            return ""
        return str(val.value) if hasattr(val, "value") else str(val)
    except Exception:  # noqa: BLE001
        return ""


def _serialise_date(value) -> str:
    """Serialise a date or datetime to an ISO string, or return ''."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
