"""
app/routers/carddav.py — carddav HTTP routes (M26.18, split from main.py).

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

from carddav_integration.client import (
    CardDAVConnectionError,
    StagedMergeNotFoundError,
)
from dav_io.vcf_io import import_vcf, export_vcf
from core.config import APP_ROOT

from app.models import (
    ConflictActionRequest,


    StageMergeRequest,
    VcfImportRequest,
)

import main  # noqa: E402  — call-time-safe via reload in main.py; see docstring

router = APIRouter()


@router.get("/carddav/addressbooks", summary="List all address books on the CardDAV server")
async def carddav_list_address_books() -> list[dict[str, Any]]:
    """
    Discover and list all address books available to the configured CardDAV account.

    Returns list of {name, url, description}.
    Requires CardDAV to be enabled in config/carddav.yaml.
    """
    client = main._require_carddav()
    try:
        # M26.5: remote read runs off the event loop with a bounded time.
        return await asyncio.wait_for(
            asyncio.to_thread(client.list_address_books),
            timeout=main._DAV_READ_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="CardDAV server did not respond in time.") from None
    except CardDAVConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/carddav/contacts", summary="List all contacts from a CardDAV address book")
async def carddav_list_contacts(
    address_book_url: str = Query(..., description="CardDAV address book URL"),
) -> list[dict[str, Any]]:
    """
    Fetch all contacts from the specified address book.

    Returns list of {uid, href, etag, fn, email, phone, org, note}.
    This is a read-only operation.
    """
    client = main._require_carddav()
    try:
        # M26.5: remote read runs off the event loop with a bounded time.
        return await asyncio.wait_for(
            asyncio.to_thread(client.list_contacts, address_book_url),
            timeout=main._DAV_READ_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="CardDAV server did not respond in time.") from None
    except CardDAVConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/carddav/contacts/search", summary="Search contacts by name, email, or org")
async def carddav_search_contacts(
    address_book_url: str = Query(..., description="CardDAV address book URL"),
    q: str = Query(..., description="Search query (matches name, email, or org)"),
) -> list[dict[str, Any]]:
    """
    Search contacts in an address book by name, email, or organisation (case-insensitive).

    Filtering is done locally — no server-side search. Read-only.
    """
    client = main._require_carddav()
    try:
        # M26.5: remote read runs off the event loop with a bounded time.
        return await asyncio.wait_for(
            asyncio.to_thread(client.search_contacts, address_book_url, q),
            timeout=main._DAV_READ_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="CardDAV server did not respond in time.") from None
    except CardDAVConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/carddav/duplicates", summary="Detect duplicate contacts (read-only)")
async def carddav_detect_duplicates(
    address_book_url: str = Query(..., description="CardDAV address book URL"),
) -> list[dict[str, Any]]:
    """
    Detect duplicate contacts in an address book by normalised name or shared email.

    Returns list of duplicate groups: [{reason, contacts: [...]}].
    SAFETY: This endpoint is read-only and never writes to the server.
    """
    client = main._require_carddav()
    try:
        # M26.5: remote read runs off the event loop with a bounded time.
        return await asyncio.wait_for(
            asyncio.to_thread(client.detect_duplicates, address_book_url),
            timeout=main._DAV_READ_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="CardDAV server did not respond in time.") from None
    except CardDAVConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/carddav/merges", summary="Stage a contact merge proposal (no server write)", status_code=201)
async def carddav_stage_merge(body: StageMergeRequest) -> dict[str, Any]:
    """
    Build a proposed merged vCard from 2+ source contacts and save it locally for human approval.

    SAFETY: This endpoint never writes to the CardDAV server.
    The staged merge must be explicitly committed via POST /carddav/merges/{id}/commit.

    Body fields:
      - address_book_url: URL of the address book
      - contact_hrefs: List of 2+ href strings identifying contacts to merge
      - merged_data: Optional partial override dict (fn, email, phone, org, note)

    Returns staging metadata (without the full vCard string).
    """
    client = main._require_carddav()
    try:
        # M26.5: stage_merge performs remote reads — run off the loop.
        return await asyncio.wait_for(
            asyncio.to_thread(
                lambda: client.stage_merge(
                    address_book_url=body.address_book_url,
                    contact_hrefs=body.contact_hrefs,
                    merged_data=body.merged_data,
                )
            ),
            timeout=main._DAV_WRITE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="CardDAV server did not respond in time.") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CardDAVConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/carddav/merges", summary="List all staged merge proposals")
async def carddav_list_staged_merges() -> list[dict[str, Any]]:
    """
    List all staged merge proposals (pending, committed, and discarded).

    The merged_vcard field is omitted from the list for brevity.
    Use GET /carddav/merges/{id} to retrieve the full record including the vCard.
    """
    client = main._require_carddav()
    return client.list_staged_merges()


@router.get("/carddav/merges/{staged_merge_id}", summary="Get a staged merge proposal (includes vCard)")
async def carddav_get_staged_merge(staged_merge_id: str) -> dict[str, Any]:
    """
    Retrieve the full staging record for a merge proposal, including the proposed vCard string.

    Raises 404 if not found.
    """
    client = main._require_carddav()
    try:
        return client.get_staged_merge(staged_merge_id)
    except StagedMergeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/carddav/merges/{staged_merge_id}/commit", summary="Commit a staged merge to the CardDAV server")
async def carddav_commit_merge(staged_merge_id: str) -> dict[str, Any]:
    """
    Write the staged merged vCard to the CardDAV server and delete the source contacts.

    SAFETY RULE: This is a write operation and must ONLY be called by an explicit human request.
    Duplicate detection and staging are automatic; this commit step is intentionally manual.

    Steps performed:
      1. PUT the merged vCard to address_book_url/<new_uid>.vcf
      2. DELETE each source contact (404s are silently ignored)
      3. Mark the staging file as "committed"

    Returns {committed, staged_merge_id, new_href}.
    Raises 404 if the staged merge is not found.
    """
    client = main._require_carddav()
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(client.commit_merge, staged_merge_id),
            timeout=30,
        )
        main.write_ops_event(
            event="commit_merge",
            outcome="success",
            detail={"staged_merge_id": staged_merge_id},
        )
        return result
    except asyncio.TimeoutError:
        main.write_ops_event(
            event="commit_merge",
            outcome="failure",
            detail={"staged_merge_id": staged_merge_id, "error": "timed out after 30s"},
        )
        raise HTTPException(
            status_code=504,
            detail="Operation timed out after 30s. The server may be busy or the remote service is not responding.",
        ) from None
    except StagedMergeNotFoundError as exc:
        main.write_ops_event(
            event="commit_merge",
            outcome="failure",
            detail={"staged_merge_id": staged_merge_id, "error": str(exc)},
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        main.write_ops_event(
            event="commit_merge",
            outcome="failure",
            detail={"staged_merge_id": staged_merge_id, "error": str(exc)},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CardDAVConnectionError as exc:
        main.write_ops_event(
            event="commit_merge",
            outcome="failure",
            detail={"staged_merge_id": staged_merge_id, "error": str(exc)},
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.delete("/carddav/merges/{staged_merge_id}", summary="Discard a staged merge proposal")
async def carddav_discard_staged_merge(staged_merge_id: str) -> dict[str, Any]:
    """
    Mark a staged merge proposal as discarded.

    No server writes are performed. The staging file is updated locally.
    Raises 404 if not found.
    """
    client = main._require_carddav()
    try:
        client.discard_staged_merge(staged_merge_id)
        return {"discarded": True, "staged_merge_id": staged_merge_id}
    except StagedMergeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/carddav/contacts", summary="Delete a single contact (human-initiated only)")
async def carddav_delete_contact(
    address_book_url: str = Query(..., description="CardDAV address book URL"),
    href: str = Query(..., description="href of the contact to delete"),
) -> dict[str, Any]:
    """
    Delete a single contact from the CardDAV server.

    SAFETY RULE: This is a write operation and must ONLY be called by an explicit human request.
    Returns {deleted: True, href} on success.
    """
    client = main._require_carddav()
    try:
        # M26.5: remote write runs off the event loop with a bounded time.
        await asyncio.wait_for(
            asyncio.to_thread(client.delete_contact, address_book_url, href),
            timeout=main._DAV_WRITE_TIMEOUT,
        )
        return {"deleted": True, "href": href}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="CardDAV server did not respond in time.") from None
    except CardDAVConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/carddav/import", summary="Import contacts from a .vcf file (CardDAV)")
async def carddav_import(body: VcfImportRequest) -> dict[str, Any]:
    """
    Import vCards from a .vcf string into a CardDAV address book.

    Safety rules:
      - Non-conflicting records are imported first
      - Conflicting records are NEVER silently merged, overwritten, or deleted
      - All conflicts are queued in data/import_conflicts/<batch_id>_carddav.json
      - All import actions are audited

    Returns an ImportSummary with counts and conflict batch_id.
    Requires CardDAV to be enabled in config/carddav.yaml.
    """
    client = main._require_carddav()
    conflicts_dir = APP_ROOT / "data" / "import_conflicts"
    try:
        summary = await asyncio.wait_for(
            asyncio.to_thread(
                import_vcf, body.vcf_content, body.address_book_url, client, conflicts_dir
            ),
            timeout=30,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Operation timed out after 30s. The server may be busy or the remote service is not responding.",
        ) from None
    return summary.to_dict()


@router.get("/carddav/export", summary="Export all contacts as a .vcf file (CardDAV)")
async def carddav_export(
    address_book_url: str = Query(..., description="CardDAV address book URL"),
) -> Response:
    """
    Export all contacts from a CardDAV address book as a .vcf download.

    Requires CardDAV to be enabled in config/carddav.yaml.
    """
    client = main._require_carddav()

    def _build_vcf() -> str:
        # list_contacts + export_vcf both hit the server (export fetches each
        # contact's raw vCard), so run the whole export off the loop (M26.5).
        contacts = client.list_contacts(address_book_url)
        return export_vcf(contacts, client)

    try:
        vcf_content = await asyncio.wait_for(
            asyncio.to_thread(_build_vcf),
            timeout=main._DAV_READ_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="CardDAV server did not respond in time.") from None
    except CardDAVConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(
        content=vcf_content,
        media_type="text/vcard",
        headers={"Content-Disposition": 'attachment; filename="contacts.vcf"'},
    )


@router.get("/carddav/conflicts", summary="List CardDAV import conflict queues")
async def carddav_list_conflicts() -> list[dict[str, Any]]:
    """
    List all pending CardDAV import conflict queues.

    Reads local conflict files only — does not require CardDAV to be enabled.
    Returns list of conflict queue summaries (without full raw_vcard fields).
    """
    return main._list_conflict_files("_carddav")


@router.get("/carddav/conflicts/{batch_id}", summary="Get a CardDAV conflict queue by batch ID")
async def carddav_get_conflict(batch_id: str) -> dict[str, Any]:
    """
    Load and return the full conflict queue for a CardDAV import batch.

    Raises 404 if the batch is not found.
    """
    return main._load_conflict_file(batch_id, "_carddav")


@router.post("/carddav/conflicts/{batch_id}/{conflict_id}/resolve",
          summary="Resolve a single CardDAV import conflict")
async def carddav_resolve_conflict(
    batch_id: str,
    conflict_id: str,
    body: ConflictActionRequest,
) -> dict[str, Any]:
    """
    Resolve a single conflict in a CardDAV import conflict queue.

    Actions:
      - "skip": Mark the conflict as skipped in the JSON file and write an audit record.
      - "overwrite": PUT the incoming vCard to the server (requires CardDAV enabled).
      - "merge_staged": Call stage_merge with the incoming data (requires CardDAV enabled).

    CardDAV merge ALWAYS requires preview and explicit confirmation before write-back.
    All actions are auditable.
    """
    from datetime import datetime, timezone
    data = main._load_conflict_file(batch_id, "_carddav")
    conflicts = data.get("conflicts", [])

    # Find the conflict
    target = next((c for c in conflicts if c["conflict_id"] == conflict_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"conflict_id not found: {conflict_id}")

    action = body.action
    result: dict[str, Any] = {"resolved": True, "action": action, "conflict_id": conflict_id}

    if action == "skip":
        target["status"] = "skipped"
        target["resolved_at"] = datetime.now(timezone.utc).isoformat()
        main._save_conflict_file(batch_id, "_carddav", data)
        main._write_audit(
            f"CARDDAV_CONFLICT_SKIP | batch_id={batch_id} | conflict_id={conflict_id}"
        )

    elif action == "overwrite":
        client = main._require_carddav()
        incoming = target.get("incoming", {})
        raw_vcard = incoming.get("raw_vcard", "")
        uid = incoming.get("uid") or __import__("uuid").uuid4().hex
        address_book_url = data.get("address_book_url", "")
        url = address_book_url.rstrip("/") + "/" + uid + ".vcf"
        try:
            # M26.5: remote PUT runs off the event loop with a bounded time.
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    client._request,
                    "PUT", url, data=raw_vcard,
                    headers={"Content-Type": "text/vcard; charset=utf-8"},
                ),
                timeout=main._DAV_WRITE_TIMEOUT,
            )
            if not resp.ok:
                raise HTTPException(
                    status_code=502,
                    detail=f"PUT failed: HTTP {resp.status_code}: {resp.text[:200]}"
                )
        except HTTPException:
            raise
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="CardDAV server did not respond in time.") from None
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        target["status"] = "overwritten"
        target["resolved_at"] = datetime.now(timezone.utc).isoformat()
        main._save_conflict_file(batch_id, "_carddav", data)
        main._write_audit(
            f"CARDDAV_CONFLICT_OVERWRITE | batch_id={batch_id} | conflict_id={conflict_id} | uid={uid}"
        )
        result["href"] = url

    elif action == "merge_staged":
        client = main._require_carddav()
        incoming = target.get("incoming", {})
        existing = target.get("existing", {})
        address_book_url = data.get("address_book_url", "")
        merged_data = body.merged_data
        try:
            # M26.5: stage_merge performs remote reads — run off the loop.
            staged = await asyncio.wait_for(
                asyncio.to_thread(
                    lambda: client.stage_merge(
                        address_book_url=address_book_url,
                        contact_hrefs=[existing.get("href", "")],
                        merged_data=merged_data or {
                            "fn": incoming.get("fn", ""),
                            "email": incoming.get("email", ""),
                            "phone": incoming.get("phone", ""),
                            "org": incoming.get("org", ""),
                            "note": incoming.get("note", ""),
                        },
                    )
                ),
                timeout=main._DAV_WRITE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="CardDAV server did not respond in time.") from None
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        target["status"] = "merge_staged"
        target["resolved_at"] = datetime.now(timezone.utc).isoformat()
        target["staged_merge_id"] = staged.get("staged_merge_id", "")
        main._save_conflict_file(batch_id, "_carddav", data)
        main._write_audit(
            f"CARDDAV_CONFLICT_MERGE_STAGED | batch_id={batch_id} | "
            f"conflict_id={conflict_id} | staged_merge_id={staged.get('staged_merge_id', '')}"
        )
        result["staged_merge_id"] = staged.get("staged_merge_id", "")

    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action!r}. Use 'skip', 'overwrite', or 'merge_staged'.")

    return result
