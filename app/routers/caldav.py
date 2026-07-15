"""
app/routers/caldav.py — caldav HTTP routes (M26.18, split from main.py).

Handlers reference app state/singletons/tunables through ``main.`` (module-level
``import main`` below). main.py reloads these router modules as it assembles the
app, so the reference always resolves to the live main — see app/__init__.py.
Do NOT convert ``main.X`` lookups into ``from main import X`` (that captures a
stale module across the test suite's per-test main re-import).
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from caldav_integration.client import (
    CalDAVConnectionError,
)
from dav_io.ics_io import import_ics, export_ics
from core.config import APP_ROOT
from core.logger import logger
from core.urlguard import ensure_same_origin

from app.models import (
    ConflictActionRequest,
    IcsImportRequest,
   
   
    TaskCreateRequest,
)

import main  # noqa: E402  — call-time-safe via reload in main.py; see docstring

router = APIRouter()


@router.get("/caldav/calendars", summary="List all calendars on the CalDAV server")
async def caldav_list_calendars() -> list[dict[str, Any]]:
    """
    Returns all calendars available to the configured CalDAV account.

    Each entry has: name, url, color, description.
    Requires CalDAV to be enabled in config/caldav.yaml.
    """
    client = main._require_caldav()
    try:
        # M26.5: remote read runs off the event loop with a bounded time.
        return await asyncio.wait_for(
            asyncio.to_thread(client.list_calendars),
            timeout=main._DAV_READ_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="CalDAV server did not respond in time.") from None
    except CalDAVConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/caldav/events", summary="Fetch upcoming events from a calendar")
async def caldav_list_events(
    calendar_url: str = Query(..., description="CalDAV calendar URL"),
    days_ahead: int = Query(default=30, ge=1, le=365, description="How many days ahead to fetch"),
) -> list[dict[str, Any]]:
    """
    Returns events from now to now + days_ahead days from the specified calendar.

    Each entry has: uid, summary, dtstart, dtend, location, description, all_day.
    Dates are ISO strings.  all_day is true when dtstart is a date (not datetime).
    """
    client = main._require_caldav()
    try:
        # M26.5: remote read runs off the event loop with a bounded time.
        return await asyncio.wait_for(
            asyncio.to_thread(client.list_events, calendar_url, days_ahead=days_ahead),
            timeout=main._DAV_READ_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="CalDAV server did not respond in time.") from None
    except CalDAVConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/caldav/tasks", summary="List VTODO tasks from a calendar")
async def caldav_list_tasks(
    calendar_url: str = Query(..., description="CalDAV calendar URL"),
) -> list[dict[str, Any]]:
    """
    Returns all VTODO items from the specified calendar.

    Each entry has: uid, summary, status, due, priority, description.
    """
    client = main._require_caldav()
    try:
        # M26.5: remote read runs off the event loop with a bounded time.
        return await asyncio.wait_for(
            asyncio.to_thread(client.list_tasks, calendar_url),
            timeout=main._DAV_READ_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="CalDAV server did not respond in time.") from None
    except CalDAVConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/caldav/tasks", summary="Create a new VTODO task on the CalDAV server")
async def caldav_create_task(body: TaskCreateRequest) -> dict[str, Any]:
    """
    Create a new task (VTODO) on the CalDAV server.  This is the only write operation.

    Body fields:
      - calendar_url: URL of the target calendar
      - summary: Task title (required)
      - due: ISO date string e.g. "2026-06-15" (optional)
      - priority: 1–9 per RFC 5545; 1 = highest (optional)
      - description: Free-text description (optional)

    Returns the created task dict.
    """
    client = main._require_caldav()
    try:
        # M26.5: remote write runs off the event loop with a bounded time.
        return await asyncio.wait_for(
            asyncio.to_thread(
                lambda: client.create_task(
                    calendar_url=body.calendar_url,
                    summary=body.summary,
                    due=body.due,
                    priority=body.priority,
                    description=body.description,
                )
            ),
            timeout=main._DAV_WRITE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="CalDAV server did not respond in time.") from None
    except CalDAVConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/caldav/import", summary="Import events/tasks from a .ics file (CalDAV)")
async def caldav_import(body: IcsImportRequest) -> dict[str, Any]:
    """
    Import iCalendar components from a .ics string into a CalDAV calendar.

    Safety rules:
      - Non-conflicting components are imported first
      - Conflicting components are queued for human review (default: skip-and-review)
      - CalDAV conflicts NEVER auto-merge — human review is always required
      - All import actions are audited

    Returns an ImportSummary with counts and conflict batch_id.
    Requires CalDAV to be enabled in config/caldav.yaml.
    """
    client = main._require_caldav()
    conflicts_dir = APP_ROOT / "data" / "import_conflicts"
    try:
        summary = await asyncio.wait_for(
            asyncio.to_thread(
                import_ics, body.ics_content, body.calendar_url, client, conflicts_dir
            ),
            timeout=30,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Operation timed out after 30s. The server may be busy or the remote service is not responding.",
        ) from None
    return summary.to_dict()


@router.get("/caldav/export", summary="Export calendar events and tasks as a .ics file")
async def caldav_export(
    calendar_url: str = Query(..., description="CalDAV calendar URL"),
    days_ahead: int = Query(default=365, ge=1, le=36500, description="Days ahead to include"),
) -> Response:
    """
    Export all events and tasks from a CalDAV calendar as a .ics download.

    Requires CalDAV to be enabled in config/caldav.yaml.
    """
    client = main._require_caldav()
    # M26.13: _gather deliberately swallows all errors (best-effort empty-file
    # contract), which would turn a rejected off-origin URL into a silent empty
    # export — validate here so it surfaces as a 400 instead.
    ensure_same_origin(calendar_url, client._url, "CalDAV")

    def _gather() -> list[dict]:
        # Best-effort: swallow per-source errors and return whatever was read.
        gathered: list[dict] = []
        try:
            gathered.extend(client.list_events(calendar_url, days_ahead=days_ahead))
        except Exception:  # noqa: BLE001
            pass
        try:
            gathered.extend(client.list_tasks(calendar_url))
        except Exception:  # noqa: BLE001
            pass
        return gathered

    # M26.5: both reads run off the loop. On timeout keep the endpoint's
    # existing best-effort contract (always returns a file) with an empty set.
    try:
        items: list[dict] = await asyncio.wait_for(
            asyncio.to_thread(_gather),
            timeout=main._DAV_READ_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("CalDAV export timed out after %ss — returning empty calendar", main._DAV_READ_TIMEOUT)
        items = []
    ics_content = export_ics(items, calendar_name="Athena Export")
    return Response(
        content=ics_content,
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="calendar.ics"'},
    )


@router.get("/caldav/conflicts", summary="List CalDAV import conflict queues")
async def caldav_list_conflicts() -> list[dict[str, Any]]:
    """
    List all pending CalDAV import conflict queues.

    Reads local conflict files only — does not require CalDAV to be enabled.
    Returns list of conflict queue summaries.
    """
    return main._list_conflict_files("_caldav")


@router.get("/caldav/conflicts/{batch_id}", summary="Get a CalDAV conflict queue by batch ID")
async def caldav_get_conflict(batch_id: str) -> dict[str, Any]:
    """
    Load and return the full conflict queue for a CalDAV import batch.

    Raises 404 if the batch is not found.
    """
    return main._load_conflict_file(batch_id, "_caldav")


@router.post("/caldav/conflicts/{batch_id}/{conflict_id}/resolve",
          summary="Resolve a single CalDAV import conflict")
async def caldav_resolve_conflict(
    batch_id: str,
    conflict_id: str,
    body: ConflictActionRequest,
) -> dict[str, Any]:
    """
    Resolve a single conflict in a CalDAV import conflict queue.

    Actions:
      - "skip": Mark the conflict as skipped in the JSON file and write an audit record.
      - "overwrite": Save the incoming ICS component to the server (requires CalDAV enabled).

    CalDAV default is skip-and-review — not auto-merge.
    All actions are auditable.
    """
    from datetime import datetime, timezone
    import caldav as caldav_lib
    data = main._load_conflict_file(batch_id, "_caldav")
    conflicts = data.get("conflicts", [])

    target = next((c for c in conflicts if c["conflict_id"] == conflict_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"conflict_id not found: {conflict_id}")

    action = body.action
    result: dict[str, Any] = {"resolved": True, "action": action, "conflict_id": conflict_id}

    if action == "skip":
        target["status"] = "skipped"
        target["resolved_at"] = datetime.now(timezone.utc).isoformat()
        main._save_conflict_file(batch_id, "_caldav", data)
        main._write_audit(
            f"CALDAV_CONFLICT_SKIP | batch_id={batch_id} | conflict_id={conflict_id}"
        )

    elif action == "overwrite":
        client = main._require_caldav()
        incoming = target.get("incoming", {})
        raw_component = incoming.get("raw_component", "")
        calendar_url = data.get("calendar_url", "")
        # M26.13: the stored batch URL was validated at import time, but this
        # push builds caldav.Calendar directly and the except below re-labels
        # everything as 502 — validate here so tampering surfaces as a 400.
        ensure_same_origin(calendar_url, client._url, "CalDAV")

        if not raw_component.strip().startswith("BEGIN:VCALENDAR"):
            raw_ical = (
                "BEGIN:VCALENDAR\r\n"
                "VERSION:2.0\r\n"
                "PRODID:-//Athena Assistant//CalDAV Conflict Overwrite//EN\r\n"
                + raw_component.strip()
                + "\r\nEND:VCALENDAR"
            )
        else:
            raw_ical = raw_component.strip()

        def _push_event() -> None:
            client._ensure_connected()
            cal_obj = caldav_lib.Calendar(client=client._client, url=calendar_url)
            cal_obj.add_event(raw_ical)

        try:
            # M26.5: connect + add_event are remote calls — run off the loop.
            await asyncio.wait_for(
                asyncio.to_thread(_push_event),
                timeout=main._DAV_WRITE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="CalDAV server did not respond in time.") from None
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        target["status"] = "overwritten"
        target["resolved_at"] = datetime.now(timezone.utc).isoformat()
        main._save_conflict_file(batch_id, "_caldav", data)
        main._write_audit(
            f"CALDAV_CONFLICT_OVERWRITE | batch_id={batch_id} | "
            f"conflict_id={conflict_id} | uid={incoming.get('uid', '?')}"
        )

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action: {action!r}. Use 'skip' or 'overwrite'."
        )

    return result

