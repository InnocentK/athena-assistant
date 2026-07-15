"""
main.py — Athena Assistant FastAPI application (assembly + state layer).

Since M26.18 the route handlers live in ``app/routers/<domain>.py`` (one
APIRouter per domain, included at the bottom of this file); this module keeps
the app state (managers, clients, profile data, timeout constants), the
``_require_*`` accessors, shared helpers, lifespan, exception handlers, the
static/template mounts, and the ``GET /`` index route.
Run it with:

    uvicorn main:app --reload --host 0.0.0.0 --port 8000   # or: task run

Interactive API docs at /docs; health (incl. version) at /health.

Orientation: docs/ARCHITECTURE.md (component map) · CLAUDE.md (agent workflow)
· docs/INVARIANTS.md (do-not-break rules) · CHANGELOG.md (per-release history
— do NOT re-add a milestone log to this docstring; it drifts).
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from caldav_integration.client import CalDAVClient
from carddav_integration.client import CardDAVClient
from backup.manager import BackupManager
from nextcloud_integration.client import NextcloudClient
from dav_status.store import get_status_store as _get_dav_status
# Re-exported for the routers: several handlers call ``main.write_ops_event``
# (audit logging) via the module. It looks unused *here* because the handlers
# live in app/routers/* now (M26.18), so ruff must be told to keep it.
from audit.ops_audit import write_ops_event  # noqa: F401  (router-facing re-export)
from core.config import APP_ROOT, active_profile_dir, get_settings
from core.loader import load_yaml, save_yaml
from core.logger import logger
from core.urlguard import DAVSecurityError
from core.version import __version__
from files.manager import FileManager
from memory.manager import MemoryManager
from saved.manager import SavedItemsManager
from providers.router import ProviderRouter

# ---------------------------------------------------------------------------
# Module-level state — populated during startup
# ---------------------------------------------------------------------------
_profile_data: dict[str, Any] = {}
_router: ProviderRouter | None = None
_memory: MemoryManager | None = None
_files: FileManager | None = None
_caldav: CalDAVClient | None = None
_carddav: CardDAVClient | None = None
_nextcloud: NextcloudClient | None = None
_backup: BackupManager | None = None
_saved: SavedItemsManager | None = None

# Restore diff tokens: token -> (zip_filename, expiry timestamp via time.monotonic()).
# M26.7: the token is bound to the filename its diff was issued for, so a token
# from one backup's diff cannot authorize restoring a different backup.
_restore_diff_tokens: dict[str, tuple[str, float]] = {}

# --- Concurrency timeouts (M26.5) -----------------------------------------
# Blocking provider/DAV work runs in a worker thread via
# ``asyncio.wait_for(asyncio.to_thread(...), timeout=...)`` so it never blocks
# the event loop. These caps also give each wrapped operation a bounded
# request time (an intentional M26.5 behaviour change for the routing paths).
#
# _ROUTE_TIMEOUT caps a single ProviderRouter.route() call. Each CLI adapter
# already self-limits at 120s (subprocess timeout); 130s leaves headroom for
# one attempt plus overhead. A full fallback chain of several attempts is still
# allowed to run its course inside the worker thread — the point is that the
# event loop stays free throughout, not to cap the whole chain.
_ROUTE_TIMEOUT = 130          # seconds — one route() call (chat, saved-action run)
_AUTO_EXTRACT_TIMEOUT = 10    # seconds — best-effort memory auto-extraction
_PROVIDERS_TIMEOUT = 15       # seconds — list_providers() availability probes
_DAV_READ_TIMEOUT = 30        # seconds — CalDAV/CardDAV read/list/search/export
_DAV_WRITE_TIMEOUT = 30       # seconds — CalDAV/CardDAV writes (create/merge/delete/resolve)


# ---------------------------------------------------------------------------
# Lifespan — runs on startup and shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """Load configuration, profile, provider router, memory manager, file manager, and CalDAV client on startup."""
    global _router, _memory, _files, _caldav, _carddav, _nextcloud, _backup, _saved

    settings = get_settings()

    logger.info("Athena Assistant starting up")
    logger.info("APP_ROOT: %s", APP_ROOT)
    logger.info("Active profile: %s", settings.active_profile)
    logger.info("Environment: %s", settings.app_env)

    # Load the active profile
    profile_path = active_profile_dir() / "profile.yaml"
    profile = load_yaml(profile_path)

    if not profile:
        logger.warning(
            "Profile file not found or empty: %s — using empty profile.", profile_path
        )

    _profile_data.update(profile)
    profile_name = _profile_data.get("name", settings.active_profile)

    # Initialise the provider router
    try:
        _router = ProviderRouter()
        logger.info("ProviderRouter initialised successfully.")
    except Exception as exc:  # noqa: BLE001
        logger.error("ProviderRouter failed to initialise: %s — /chat will be unavailable.", exc)
        _router = None

    # Initialise the memory manager
    try:
        _memory = MemoryManager(active_profile_dir(), _profile_data)
        logger.info("MemoryManager initialised successfully.")
    except Exception as exc:  # noqa: BLE001
        logger.error("MemoryManager failed to initialise: %s — memory endpoints will be unavailable.", exc)
        _memory = None

    # Initialise the saved-items manager (Milestone 18)
    try:
        _saved = SavedItemsManager(active_profile_dir())
        logger.info("SavedItemsManager initialised successfully.")
    except Exception as exc:  # noqa: BLE001
        logger.error("SavedItemsManager failed to initialise: %s — /saved endpoints will be unavailable.", exc)
        _saved = None

    # Initialise the file manager
    try:
        _files = FileManager()
        logger.info("FileManager initialised successfully.")
    except Exception as exc:  # noqa: BLE001
        logger.error("FileManager failed to initialise: %s — file endpoints will be unavailable.", exc)
        _files = None

    # Initialise CalDAV client (if enabled in config)
    try:
        _caldav_config = load_yaml(APP_ROOT / "config" / "caldav.yaml") or {}
        if _caldav_config.get("enabled", False):
            _caldav = CalDAVClient()
            logger.info("CalDAVClient initialised successfully.")
            _get_dav_status().set_enabled("caldav", True)
        else:
            logger.info("CalDAV integration disabled (config/caldav.yaml enabled: false).")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "CalDAVClient failed to initialise: %s — CalDAV endpoints will return 503.", exc
        )
        _caldav = None

    # Initialise CardDAV client (if enabled in config)
    try:
        _carddav_config = load_yaml(APP_ROOT / "config" / "carddav.yaml") or {}
        if _carddav_config.get("enabled", False):
            _carddav = CardDAVClient()
            logger.info("CardDAVClient initialised successfully.")
            _get_dav_status().set_enabled("carddav", True)
        else:
            logger.info("CardDAV integration disabled (config/carddav.yaml enabled: false).")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "CardDAVClient failed to initialise: %s — CardDAV endpoints will return 503.", exc
        )
        _carddav = None

    # Initialise Nextcloud client (if enabled in config)
    try:
        _nc_config = load_yaml(APP_ROOT / "config" / "nextcloud.yaml") or {}
        if _nc_config.get("enabled", False):
            _nextcloud = NextcloudClient()
            logger.info("NextcloudClient initialised successfully.")
            _get_dav_status().set_enabled("nextcloud", True)
        else:
            logger.info("Nextcloud integration disabled (config/nextcloud.yaml enabled: false).")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "NextcloudClient failed to initialise: %s — Nextcloud endpoints will return 503.", exc
        )
        _nextcloud = None

    # Initialise BackupManager
    try:
        _backup = BackupManager(APP_ROOT, app_version=app.version)
        logger.info("BackupManager initialised successfully.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("BackupManager failed to initialise: %s", exc)
        _backup = None

    # Console startup banner
    print(f"Athena Assistant running — profile: {profile_name}", flush=True)
    # App version (release) vs profile schema version are distinct (M26.2):
    # the app version is the single source of truth (app.version); the profile's
    # own `version` is its schema/format version, reported separately.
    logger.info(
        "Profile loaded: %s (app v%s, profile schema v%s)",
        profile_name,
        app.version,
        _profile_data.get("version", "?"),
    )

    yield  # Application runs here

    logger.info("Athena Assistant shutting down")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Athena Assistant",
    description="Local-first AI assistant platform",
    # M26.17: version comes from the single source core/version.py
    version=__version__,
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Global exception handler — bare unexpected exceptions only
# HTTPException and RequestValidationError are intentionally NOT caught here
# so FastAPI's default handling remains intact.
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled exception on %s %s: %s",
        request.method,
        request.url.path,
        exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred. Check server logs."},
    )


@app.exception_handler(DAVSecurityError)
async def dav_security_handler(request: Request, exc: DAVSecurityError) -> JSONResponse:
    """M26.13 SSRF guard: a caller-supplied DAV URL targeted a different origin
    than the configured server — reject with 400, never send credentials."""
    logger.warning("Rejected off-origin DAV URL on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=400, content={"detail": str(exc)})

# ---------------------------------------------------------------------------
# Static files and templates
# ---------------------------------------------------------------------------

class _RevalidateStaticFiles(StaticFiles):
    """
    Serve static assets with a conservative revalidation header (M26.1).

    Browsers re-check freshness on each load instead of heuristically caching
    JS/CSS. Combined with versioned ``?v=`` URLs in the template, this prevents
    stale cached assets after an upgrade (the cause of the M26 settings/status
    UI appearing not to update).
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


app.mount("/static", _RevalidateStaticFiles(directory=APP_ROOT / "static"), name="static")

_templates = Jinja2Templates(directory=str(APP_ROOT / "templates"))


# ---------------------------------------------------------------------------
# Browser UI route
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index(request: Request) -> HTMLResponse:
    """
    Serve the browser-based chat UI.
    Passes the assistant name from the active profile to the Jinja2 template.
    """
    assistant_name: str = _profile_data.get("name", "Athena") or "Athena"
    return _templates.TemplateResponse(
        request,
        "index.html",
        # asset_version busts the browser cache on every release so JS/CSS
        # changes actually reach users (M26.1).
        {"assistant_name": assistant_name, "asset_version": app.version},
    )


@app.get("/sw.js", include_in_schema=False)
async def service_worker() -> Response:
    """
    Serve the PWA service worker (M26.28) from the site root so its scope is the
    whole app ("/"). The running version is substituted into the worker's cache
    name (``__ATHENA_VERSION__``) so each release invalidates the previous shell
    cache on ``activate`` — the same anti-stale discipline as the ``?v=`` asset
    versioning (M26.1). ``no-cache`` lets browsers pick up an updated worker.

    The worker itself only registers in a secure context (HTTPS/localhost); over
    plain HTTP the client-side guard in ``pwa.js`` makes registration a no-op.
    """
    source = (APP_ROOT / "static" / "js" / "sw.js").read_text(encoding="utf-8")
    body = source.replace("__ATHENA_VERSION__", app.version)
    return Response(
        content=body,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


# ---------------------------------------------------------------------------
# Core endpoints
# ---------------------------------------------------------------------------





# --- M26: editable settings (narrow, behaviour-affecting profile fields) -----

EDITABLE_ROUTING_MODES = ("quality-first", "balanced", "budget-first")
_MAX_SYSTEM_PROMPT = 8000


def _validate_routing_mode(mode: str | None) -> None:
    """Raise 400 unless *mode* is one of the valid routing modes (M26.8).

    Accepts None (e.g. ``{"mode": null}``) and correctly rejects it — None is
    not in the allowed tuple, so it 400s like any other invalid mode.
    """
    if mode not in EDITABLE_ROUTING_MODES:
        raise HTTPException(
            status_code=400,
            detail="Invalid mode. Choose one of: " + ", ".join(EDITABLE_ROUTING_MODES) + ".",
        )


async def _known_provider_names() -> set:
    """
    Return the set of known provider names (empty if the router is unavailable).

    list_providers() probes adapters (Ollama does a network health check), so it
    runs off the event loop with a bounded time (M26.5). Shared by PATCH /profile
    and the saved-action validators (M26.8).
    """
    if _router is None:
        return set()
    try:
        rows = await asyncio.wait_for(
            asyncio.to_thread(_router.list_providers),
            timeout=_PROVIDERS_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=503, detail="Provider listing timed out.") from None
    return {row.get("name") for row in rows}


def _persist_profile_changes(changes: dict[str, Any]) -> None:
    """
    Read profile.yaml, apply the allowed changes, and write it back.

    Runs in a worker thread (blocking file IO). Only the editable keys are
    touched; every other profile key is preserved, and key order is kept
    (``sort_keys=False``). YAML comments are not preserved (safe_dump).
    """
    path = active_profile_dir() / "profile.yaml"
    data = load_yaml(path) or {}
    if "system_prompt" in changes:
        data["system_prompt"] = changes["system_prompt"]
    if "mode" in changes or "preferred_provider" in changes:
        routing = data.setdefault("routing", {})
        if "mode" in changes:
            routing["mode"] = changes["mode"]
        if "preferred_provider" in changes:
            routing["preferred_provider"] = changes["preferred_provider"]
    save_yaml(path, data, sort_keys=False)








# ---------------------------------------------------------------------------
# Memory endpoints
# ---------------------------------------------------------------------------

def _require_memory() -> MemoryManager:
    """Return the MemoryManager or raise 503 if not initialised."""
    if _memory is None:
        raise HTTPException(
            status_code=503,
            detail="MemoryManager is not available. Check startup logs.",
        )
    return _memory


















# ---------------------------------------------------------------------------
# Saved searches & saved actions (Milestone 18)
#
# v1 scope: saved SEARCHES run as local FILE searches only (target: "files",
# via FileManager + the existing allowlist). Other targets and web searches are
# NOT runnable in this milestone. Saved ACTIONS run a stored prompt through the
# existing ProviderRouter (no auto-extraction).
# ---------------------------------------------------------------------------


def _require_saved() -> SavedItemsManager:
    """Return the SavedItemsManager or raise 503 if not initialised."""
    if _saved is None:
        raise HTTPException(
            status_code=503,
            detail="SavedItemsManager is not available. Check startup logs.",
        )
    return _saved


























# ---------------------------------------------------------------------------
# Voice endpoints (Milestone 5) — stubs; browser fallback is active
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# File endpoints (Milestone 6)
# ---------------------------------------------------------------------------

def _require_files() -> FileManager:
    """Return the FileManager or raise 503 if not initialised."""
    if _files is None:
        raise HTTPException(
            status_code=503,
            detail="FileManager is not available. Check startup logs.",
        )
    return _files
















# ---------------------------------------------------------------------------
# CalDAV endpoints (Milestone 7)
# ---------------------------------------------------------------------------

def _require_caldav() -> CalDAVClient:
    """Return the CalDAVClient or raise 503 if not initialised."""
    if _caldav is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "CalDAV integration not available. "
                "Set CALDAV_URL/USERNAME/PASSWORD and enabled: true in config/caldav.yaml."
            ),
        )
    return _caldav









# ---------------------------------------------------------------------------
# CardDAV endpoints (Milestone 8)
# ---------------------------------------------------------------------------


def _require_carddav() -> CardDAVClient:
    """Return the CardDAVClient or raise 503 if not initialised."""
    if _carddav is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "CardDAV integration not available. "
                "Set CARDDAV_URL/USERNAME/PASSWORD and enabled: true in config/carddav.yaml."
            ),
        )
    return _carddav






















# ---------------------------------------------------------------------------
# Conflict queue helpers (Milestone 12) — shared by CardDAV and CalDAV
# ---------------------------------------------------------------------------

APP_CONFLICTS_DIR = APP_ROOT / "data" / "import_conflicts"


def _list_conflict_files(suffix: str) -> list[dict]:
    """List conflict queue summaries for a given suffix (_carddav or _caldav)."""
    APP_CONFLICTS_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for f in sorted(APP_CONFLICTS_DIR.glob(f"*{suffix}.json")):
        try:
            data = json.loads(f.read_text())
            # Return summary without raw_vcard fields
            summary: dict = {k: v for k, v in data.items() if k != "conflicts"}
            summary["conflict_count"] = len(data.get("conflicts", []))
            results.append(summary)
        except Exception:
            pass
    return results


def _load_conflict_file(batch_id: str, suffix: str) -> dict:
    """Load a full conflict queue file. Raises HTTPException 404 if not found."""
    path = APP_CONFLICTS_DIR / f"{batch_id}{suffix}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Conflict batch not found: {batch_id}")
    return json.loads(path.read_text())


def _save_conflict_file(batch_id: str, suffix: str, data: dict) -> None:
    path = APP_CONFLICTS_DIR / f"{batch_id}{suffix}.json"
    path.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# CardDAV import/export/conflict endpoints (Milestone 12)
# ---------------------------------------------------------------------------












# ---------------------------------------------------------------------------
# CalDAV import/export/conflict endpoints (Milestone 12)
# ---------------------------------------------------------------------------












def _write_audit(record: str) -> None:
    """Write a record to today's import audit log."""
    from datetime import datetime, timezone
    try:
        audit_dir = APP_ROOT / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        audit_file = audit_dir / f"{date_str}_import_audit.log"
        ts = datetime.now(timezone.utc).isoformat()
        with audit_file.open("a", encoding="utf-8") as f:
            f.write(f"{ts} | {record}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Nextcloud endpoints (Milestone 9) — read-only
# ---------------------------------------------------------------------------


def _require_nextcloud() -> NextcloudClient:
    """Return the NextcloudClient or raise 503 if not initialised."""
    if _nextcloud is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Nextcloud integration not available. "
                "Set NEXTCLOUD_URL/USERNAME/PASSWORD and enabled: true in config/nextcloud.yaml."
            ),
        )
    return _nextcloud


















# =============================================================================
# Backup / Export / Import endpoints  (Milestone 13)
# =============================================================================

def _require_backup() -> BackupManager:
    if _backup is None:
        raise HTTPException(status_code=503, detail="BackupManager not available.")
    return _backup


def _safe_export_path(filename: str) -> Path:
    """
    Resolve a backup filename to a path inside data/exports/, rejecting any
    traversal (``../``) or absolute path with a 400 (M26.7).

    Backup filenames never contain subdirectories, so a legitimate name resolves
    unchanged; the caller still does its own `.exists()` → 404 check afterwards.
    """
    exports = (APP_ROOT / "data" / "exports").resolve()
    candidate = (exports / filename).resolve()
    try:
        candidate.relative_to(exports)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid backup filename.") from None
    return candidate
















# ---------------------------------------------------------------------------
# Router assembly (M26.18) — routes live in app/routers/*.py
# ---------------------------------------------------------------------------
# Each router module does a module-level ``import main``; reloading here rebinds
# it to *this* main module object every time main is (re)imported, which keeps
# the app correct under the test suite's per-test main swap. Order preserved.
import importlib as _importlib  # noqa: E402

for _rname in (
    "core", "memory", "saved", "voice", "files",
    "caldav", "carddav", "nextcloud", "backup", "dav_status",
):
    _rmod = _importlib.import_module(f"app.routers.{_rname}")
    _rmod = _importlib.reload(_rmod)
    app.include_router(_rmod.router)
