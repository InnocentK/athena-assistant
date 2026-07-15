"""
dav_io/ics_io.py — ICS (iCalendar) import and export utilities.

Import flow:
  1. Parse all VEVENT/VTODO components from the .ics input
  2. Check each against existing events/tasks for conflicts (same UID)
  3. Import non-conflicting components
  4. Queue conflicts in data/import_conflicts/<batch_id>_caldav.json
  5. Return an ImportSummary (same dataclass as vcf_io)

Export flow:
  - Accepts a list of event/task dicts (from CalDAVClient)
  - Returns a single .ics string (VCALENDAR wrapping all components)

Safety rules:
  - Non-conflicting records are imported first
  - Conflicting records are NEVER silently merged, overwritten, or deleted
  - CalDAV default is skip-and-review, not auto-merge
  - All import actions are audited
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import vobject

from core.urlguard import ensure_same_origin
from dav_io.vcf_io import ImportSummary


# ---------------------------------------------------------------------------
# ICS value formatting (M26.9)
# ---------------------------------------------------------------------------


def escape_ics_text(value: str) -> str:
    """
    Escape a text value per RFC 5545 §3.3.11 (TEXT).

    Escapes backslash, semicolon, comma, and newlines so a SUMMARY/DESCRIPTION/
    LOCATION containing those characters cannot inject new content lines or
    produce a malformed component. Backslash MUST be escaped first.
    """
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\r", "\\n")
        .replace("\n", "\\n")
    )


def _format_ics_datetime(value: str) -> str:
    """
    Format an ISO datetime string as an iCalendar DATE-TIME value (M26.9).

    - Offset-aware (incl. a trailing 'Z') → converted to UTC, emitted as
      ``YYYYMMDDTHHMMSSZ``.
    - Naive (no offset) → emitted as floating local time ``YYYYMMDDTHHMMSS``
      WITHOUT a 'Z', so a naive time is never falsely declared UTC.
    - Unparseable → a best-effort floating stamp (punctuation stripped, no 'Z'),
      degraded but never time-shifted.

    Fixes the prior string-munge that discarded the offset and always appended
    'Z' (shifting offset times and mis-stamping naive/negative-offset values).
    """
    raw = value.strip()
    # Normalise a trailing 'Z' to an explicit offset so fromisoformat accepts it
    # on Python 3.10 as well as 3.11+.
    normalised = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
    try:
        dt = datetime.fromisoformat(normalised)
    except ValueError:
        digits = raw.replace("-", "").replace(":", "").split("+")[0].split(".")[0]
        return digits  # floating fallback — do not assert a UTC we can't verify
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return dt.strftime("%Y%m%dT%H%M%S")


# ---------------------------------------------------------------------------
# ICS parsing
# ---------------------------------------------------------------------------


def _component_to_dict(comp) -> dict | None:
    """Extract a dict from a vobject component (VEVENT or VTODO).

    Returns None for unsupported component types.
    """
    name = comp.name.upper() if hasattr(comp, "name") else ""

    if name == "VEVENT":
        entry: dict = {"type": "VEVENT"}
        entry["uid"] = _get_val(comp, "uid")
        entry["summary"] = _get_val(comp, "summary")
        entry["dtstart"] = _get_dt(comp, "dtstart")
        entry["dtend"] = _get_dt(comp, "dtend")
        entry["location"] = _get_val(comp, "location")
        entry["description"] = _get_val(comp, "description")
        # all_day: dtstart has no time component
        try:
            ds = comp.dtstart.value
            entry["all_day"] = not hasattr(ds, "hour")
        except Exception:
            entry["all_day"] = False
        try:
            entry["raw_component"] = comp.serialize()
        except Exception:
            entry["raw_component"] = ""
        return entry

    elif name == "VTODO":
        entry = {"type": "VTODO"}
        entry["uid"] = _get_val(comp, "uid")
        entry["summary"] = _get_val(comp, "summary")
        entry["status"] = _get_val(comp, "status")
        entry["due"] = _get_dt(comp, "due")
        entry["priority"] = _get_val(comp, "priority")
        entry["description"] = _get_val(comp, "description")
        try:
            entry["raw_component"] = comp.serialize()
        except Exception:
            entry["raw_component"] = ""
        return entry

    return None


def _get_val(comp, attr: str) -> str:
    """Safely get a string value from a vobject component attribute."""
    try:
        if hasattr(comp, attr):
            return str(getattr(comp, attr).value).strip()
    except Exception:
        pass
    return ""


def _get_dt(comp, attr: str) -> str:
    """Safely get a datetime value as ISO string from a vobject component attribute."""
    try:
        if hasattr(comp, attr):
            val = getattr(comp, attr).value
            if hasattr(val, "isoformat"):
                return val.isoformat()
            return str(val)
    except Exception:
        pass
    return ""


def parse_ics_string(ics_str: str) -> tuple[list[dict], list[str]]:
    """Parse a VCALENDAR string into a list of VEVENT/VTODO component dicts.

    Uses vobject to parse the iCalendar data.

    Returns:
        (parsed_list, error_list)
    """
    parsed: list[dict] = []
    errors: list[str] = []

    if not ics_str or not ics_str.strip():
        return parsed, errors

    try:
        # Try parsing as a full VCALENDAR
        cal = vobject.readOne(ics_str)
        components = list(cal.components())
    except Exception as exc:
        # If that fails, try readComponents (handles multiple calendars or bare components)
        try:
            components = []
            for obj in vobject.readComponents(ics_str):
                if hasattr(obj, "name") and obj.name.upper() == "VCALENDAR":
                    components.extend(list(obj.components()))
                else:
                    components.append(obj)
        except Exception as exc2:
            errors.append(f"Failed to parse ICS string: {exc!s}; fallback also failed: {exc2!s}")
            return parsed, errors

    for comp in components:
        try:
            entry = _component_to_dict(comp)
            if entry is not None:
                parsed.append(entry)
            # Skip VTIMEZONE and other non-VEVENT/VTODO components silently
        except Exception as exc:
            errors.append(f"Failed to process component {getattr(comp, 'name', '?')}: {exc!s}")

    if not parsed and not errors:
        # Parsed successfully but found no VEVENT/VTODO
        pass  # Return empty list without error (calendar might only have VTIMEZONE etc.)

    return parsed, errors


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


def detect_ics_conflict(candidate: dict, existing_items: list[dict]) -> dict | None:
    """Return the first existing item that conflicts with the candidate, or None.

    Conflict rule: same UID (non-empty, case-insensitive).
    """
    cand_uid = (candidate.get("uid") or "").strip().lower()
    if not cand_uid:
        return None

    for existing in existing_items:
        ex_uid = (existing.get("uid") or "").strip().lower()
        if ex_uid and cand_uid == ex_uid:
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


def import_ics(
    ics_str: str,
    calendar_url: str,
    caldav_client,
    conflicts_dir: Path,
) -> ImportSummary:
    """Import iCalendar components from an ICS string into a CalDAV calendar.

    Safety rules:
      - Non-conflicting components are imported first
      - Conflicting components are queued for human review (default: skip-and-review)
      - All actions are audited

    Args:
        ics_str:        Raw .ics content
        calendar_url:   CalDAV calendar URL
        caldav_client:  An initialised CalDAVClient instance
        conflicts_dir:  Directory to write conflict queue JSON files

    Returns:
        ImportSummary with counts and conflict_ids
    """
    # M26.13 SSRF guard — fail fast BEFORE any network step. Steps 1–3 below
    # warn-and-continue on errors and step 4 builds caldav.Calendar directly
    # (bypassing the client's own guard), so entry is the only reliable spot.
    ensure_same_origin(calendar_url, getattr(caldav_client, "_url", ""), "CalDAV")

    batch_id = uuid.uuid4().hex
    summary = ImportSummary(batch_id=batch_id)

    # 1. Parse
    parsed, parse_errors = parse_ics_string(ics_str)
    summary.errors.extend(parse_errors)
    summary.invalid += len(parse_errors)
    summary.total = len(parsed) + len(parse_errors)

    if not parsed and not parse_errors:
        _append_audit(
            f"{datetime.now(timezone.utc).isoformat()} | CALDAV_IMPORT | "
            f"batch_id={batch_id} | total=0 imported=0 conflicts=0 invalid=0 failed=0"
        )
        return summary

    # 2. Fetch existing items (events + tasks) — wrap in try/except per spec
    existing_items: list[dict] = []
    try:
        events = caldav_client.list_events(calendar_url, days_ahead=3650)
        existing_items.extend(events)
    except Exception as exc:
        summary.errors.append(f"Warning: could not fetch existing events: {exc!s}")

    try:
        tasks = caldav_client.list_tasks(calendar_url)
        existing_items.extend(tasks)
    except Exception as exc:
        summary.errors.append(f"Warning: could not fetch existing tasks: {exc!s}")

    # 3. Ensure connected
    try:
        caldav_client._ensure_connected()
    except Exception as exc:
        summary.errors.append(f"Warning: could not ensure CalDAV connection: {exc!s}")

    # 4. Import via caldav library
    import caldav as caldav_lib

    try:
        cal_obj = caldav_lib.Calendar(client=caldav_client._client, url=calendar_url)
    except Exception as exc:
        summary.errors.append(f"Could not create caldav.Calendar object: {exc!s}")
        cal_obj = None

    # 5. Process each parsed component
    conflicts: list[dict] = []

    for comp in parsed:
        conflicting = detect_ics_conflict(comp, existing_items)

        if conflicting is not None:
            # CalDAV default: skip-and-review, not auto-merge
            conflict_id = uuid.uuid4().hex
            conflicts.append({
                "conflict_id": conflict_id,
                "reason": "uid_match",
                "incoming": {
                    k: v for k, v in comp.items()
                },
                "existing": {
                    k: v for k, v in conflicting.items()
                },
            })
            summary.skipped_conflicts += 1
            summary.conflict_ids.append(conflict_id)
        else:
            # Non-conflicting: import to server
            raw_component = comp.get("raw_component", "")

            if not raw_component:
                # Reconstruct a minimal VCALENDAR-wrapped component for add_event
                raw_component = _reconstruct_component(comp)

            # Wrap in VCALENDAR if not already wrapped
            if not raw_component.strip().startswith("BEGIN:VCALENDAR"):
                raw_ical = (
                    "BEGIN:VCALENDAR\r\n"
                    "VERSION:2.0\r\n"
                    "PRODID:-//Athena Assistant//CalDAV Import//EN\r\n"
                    + raw_component.strip()
                    + "\r\nEND:VCALENDAR"
                )
            else:
                raw_ical = raw_component.strip()

            if cal_obj is not None:
                try:
                    cal_obj.add_event(raw_ical)
                    summary.imported += 1
                except Exception as exc:
                    summary.failed += 1
                    summary.errors.append(f"add_event failed for UID {comp.get('uid', '?')}: {exc!s}")
            else:
                summary.failed += 1
                summary.errors.append(
                    f"No CalDAV calendar object available for UID {comp.get('uid', '?')}"
                )

    # 6. Save conflict queue
    if conflicts:
        conflicts_dir.mkdir(parents=True, exist_ok=True)
        conflict_file = conflicts_dir / f"{batch_id}_caldav.json"
        conflict_data = {
            "batch_id": batch_id,
            "calendar_url": calendar_url,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
            "conflicts": conflicts,
        }
        try:
            conflict_file.write_text(json.dumps(conflict_data, indent=2), encoding="utf-8")
        except Exception as exc:
            summary.errors.append(f"Failed to write conflict file: {exc!s}")

    # 7. Audit
    _append_audit(
        f"{datetime.now(timezone.utc).isoformat()} | CALDAV_IMPORT | "
        f"batch_id={batch_id} | "
        f"total={summary.total} imported={summary.imported} "
        f"conflicts={summary.skipped_conflicts} invalid={summary.invalid} failed={summary.failed}"
    )

    return summary


def _reconstruct_component(comp: dict) -> str:
    """Reconstruct a minimal VEVENT or VTODO string from a dict."""
    comp_type = comp.get("type", "VEVENT")
    uid = comp.get("uid") or uuid.uuid4().hex
    summary_val = comp.get("summary", "Imported Event")

    lines = [f"BEGIN:{comp_type}"]
    lines.append(f"UID:{uid}")
    lines.append(f"SUMMARY:{escape_ics_text(summary_val)}")

    if comp_type == "VEVENT":
        dtstart = comp.get("dtstart", "")
        dtend = comp.get("dtend", "")
        if dtstart:
            lines.append(f"DTSTART:{_format_ics_datetime(dtstart)}" if "T" in dtstart else f"DTSTART;VALUE=DATE:{dtstart[:10].replace('-', '')}")
        if dtend:
            lines.append(f"DTEND:{_format_ics_datetime(dtend)}" if "T" in dtend else f"DTEND;VALUE=DATE:{dtend[:10].replace('-', '')}")
        if comp.get("location"):
            lines.append(f"LOCATION:{escape_ics_text(comp['location'])}")
        if comp.get("description"):
            lines.append(f"DESCRIPTION:{escape_ics_text(comp['description'])}")
    elif comp_type == "VTODO":
        if comp.get("status"):
            lines.append(f"STATUS:{comp['status']}")
        if comp.get("due"):
            due = comp["due"]
            lines.append(f"DUE:{_format_ics_datetime(due)}" if "T" in due else f"DUE;VALUE=DATE:{due[:10].replace('-', '')}")
        if comp.get("priority"):
            lines.append(f"PRIORITY:{comp['priority']}")
        if comp.get("description"):
            lines.append(f"DESCRIPTION:{escape_ics_text(comp['description'])}")

    lines.append(f"END:{comp_type}")
    return "\r\n".join(lines)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_ics(items: list[dict], calendar_name: str = "Athena Export") -> str:
    """Export a list of event/task dicts to a VCALENDAR string.

    Args:
        items:          List of event/task dicts (may have raw_component)
        calendar_name:  Name for the X-WR-CALNAME header

    Returns:
        Full .ics string with VCALENDAR wrapper
    """
    header_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Athena Assistant//CalDAV Export//EN",
        f"X-WR-CALNAME:{calendar_name}",
    ]

    component_lines: list[str] = []

    for item in items:
        raw = item.get("raw_component", "")
        if raw and raw.strip():
            # Strip any VCALENDAR wrapper if embedded
            stripped = raw.strip()
            if stripped.startswith("BEGIN:VCALENDAR"):
                # Extract inner components
                inner = _strip_vcalendar_wrapper(stripped)
                if inner:
                    component_lines.append(inner)
                else:
                    component_lines.append(stripped)
            else:
                component_lines.append(stripped)
        else:
            # Reconstruct from dict
            reconstructed = _reconstruct_component(item)
            if reconstructed:
                component_lines.append(reconstructed)

    footer_lines = ["END:VCALENDAR"]

    all_lines = header_lines + component_lines + footer_lines
    return "\r\n".join(all_lines)


def _strip_vcalendar_wrapper(ics_str: str) -> str:
    """Extract inner components from a VCALENDAR-wrapped string."""
    lines = ics_str.splitlines()
    inner: list[str] = []
    for line in lines:
        upper = line.strip().upper()
        if upper in ("BEGIN:VCALENDAR", "END:VCALENDAR"):
            continue
        if upper.startswith("VERSION:") or upper.startswith("PRODID:") or upper.startswith("X-WR-"):
            continue
        inner.append(line)
    return "\r\n".join(inner)
