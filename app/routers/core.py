"""
app/routers/core.py — core HTTP routes (M26.18, split from main.py).

Handlers reference app state/singletons/tunables through ``main.`` (module-level
``import main`` below). main.py reloads these router modules as it assembles the
app, so the reference always resolves to the live main — see app/__init__.py.
Do NOT convert ``main.X`` lookups into ``from main import X`` (that captures a
stale module across the test suite's per-test main re-import).
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from core.config import get_settings
from core.logger import logger
from providers.base import Message

from app.models import (
    ChatRequest, ChatResponse,


    ProfileUpdate,
)

import main  # noqa: E402  — call-time-safe via reload in main.py; see docstring

router = APIRouter()


@router.get("/health", summary="Health check")
async def health() -> dict[str, str]:
    """
    Returns service status and the name of the currently active profile.
    """
    settings = get_settings()
    profile_name = main._profile_data.get("name", settings.active_profile)
    return {
        "status": "ok",
        "profile": profile_name,
        # Single source of truth: the FastAPI app version (M26.2).
        "version": main.app.version,
    }


@router.get("/profile", summary="Active profile config")
async def profile() -> dict[str, Any]:
    """
    Returns the full loaded profile configuration as JSON.
    Raises 404 if no profile has been loaded.
    """
    if not main._profile_data:
        raise HTTPException(status_code=404, detail="No profile loaded.")
    return main._profile_data


@router.patch("/profile", summary="Update editable profile settings (M26)")
async def update_profile(update: ProfileUpdate) -> dict[str, Any]:
    """
    Apply a narrow, validated set of editable profile settings — system prompt,
    routing mode, and preferred provider — then persist to ``profile.yaml`` and
    apply to the live runtime (no restart).

    Validation runs BEFORE any write or runtime mutation: on failure nothing is
    written to disk and nothing in the running profile changes.
    """
    if not main._profile_data:
        raise HTTPException(status_code=404, detail="No profile loaded.")

    # Which fields the caller actually sent (Pydantic v2 `model_fields_set`,
    # v1 `__fields_set__`), narrowed to a definite set type.
    _fields: Any = getattr(update, "model_fields_set", None)
    if _fields is None:  # Pydantic v1 fallback
        _fields = getattr(update, "__fields_set__", set())
    provided: set[str] = set(_fields)

    changes: dict[str, Any] = {}

    if "system_prompt" in provided:
        system_prompt = update.system_prompt or ""
        if len(system_prompt) > main._MAX_SYSTEM_PROMPT:
            raise HTTPException(
                status_code=400,
                detail=f"system_prompt too long (max {main._MAX_SYSTEM_PROMPT} characters).",
            )
        changes["system_prompt"] = system_prompt

    if "mode" in provided:
        main._validate_routing_mode(update.mode)
        changes["mode"] = update.mode

    if "preferred_provider" in provided:
        preferred = update.preferred_provider
        if preferred == "":
            preferred = None  # empty selection clears the override
        if preferred is not None and preferred not in await main._known_provider_names():
            raise HTTPException(status_code=400, detail=f"Unknown provider: {preferred}.")
        changes["preferred_provider"] = preferred

    if not changes:
        raise HTTPException(status_code=400, detail="No editable fields provided.")

    # Persist first; only mutate the live runtime if the write succeeds.
    try:
        await asyncio.wait_for(
            asyncio.to_thread(main._persist_profile_changes, changes),
            timeout=10,
        )
    except asyncio.TimeoutError:
        main.write_ops_event(
            event="settings_update",
            outcome="failure",
            detail={"fields": list(changes), "error": "timed out after 10s"},
        )
        raise HTTPException(status_code=504, detail="Saving settings timed out.") from None
    except Exception as exc:  # noqa: BLE001 — surface a clean 500, keep runtime intact
        main.write_ops_event(
            event="settings_update",
            outcome="failure",
            detail={"fields": list(changes), "error": str(exc)},
        )
        raise HTTPException(status_code=500, detail="Failed to save settings.") from exc

    # Apply to live runtime state IN PLACE so the next /chat uses it (no restart).
    if "system_prompt" in changes:
        main._profile_data["system_prompt"] = changes["system_prompt"]
    if "mode" in changes or "preferred_provider" in changes:
        routing = main._profile_data.setdefault("routing", {})
        if "mode" in changes:
            routing["mode"] = changes["mode"]
        if "preferred_provider" in changes:
            routing["preferred_provider"] = changes["preferred_provider"]

    main.write_ops_event(event="settings_update", outcome="success", detail={"fields": list(changes)})
    return main._profile_data


@router.post("/chat", summary="Send a message to the active AI provider", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Route a chat message through the configured provider chain.

    The history list contains prior turns (role: user|assistant).
    The new `message` is appended as the final user turn.

    Routing mode, preferred provider, and fallback order are all read
    from the active profile's `routing` section.

    After a successful provider response, auto-extraction is run to detect
    any memory candidates in the conversation turn.
    """
    if main._router is None:
        raise HTTPException(
            status_code=503,
            detail="ProviderRouter is not available. Check startup logs.",
        )

    # Build the full message list from history + the new user message
    messages: list[Message] = [
        Message(role=m.role, content=m.content) for m in request.history
    ]
    messages.append(Message(role="user", content=request.message))

    system_prompt: str | None = main._profile_data.get("system_prompt") or None

    # M26.5: route() is synchronous (subprocess/network); run it in a worker
    # thread so the event loop stays responsive, with a bounded request time.
    # NOTE: main._profile_data is read here without a lock. Under the single-worker
    # uvicorn deployment this is safe (attribute/dict reads are atomic); a lock
    # would only be needed if multiple workers ever shared this process.
    # CAVEAT: on timeout, wait_for stops awaiting but cannot cancel the worker
    # thread — the underlying provider call keeps running to its own limit (each
    # CLI adapter self-limits at 120s). We return promptly to the client; the
    # orphaned attempt finishes and is discarded in the background.
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(main._router.route, messages, system_prompt, main._profile_data),
            timeout=main._ROUTE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.error("Router timed out after %ss (chat)", main._ROUTE_TIMEOUT)
        return ChatResponse(
            response="The request timed out.",
            provider="none",
            model=None,
            success=False,
            diagnostics=None,
        )

    # Fire-and-forget auto-extraction (fast pattern matching only). Wrapped so a
    # slow YAML write can neither block the loop nor fail an answered chat.
    if main._memory is not None:
        try:
            await asyncio.wait_for(
                asyncio.to_thread(main._memory.auto_extract, request.message, response.content),
                timeout=main._AUTO_EXTRACT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("auto_extract timed out after %ss (non-fatal)", main._AUTO_EXTRACT_TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            logger.error("auto_extract raised an unexpected error: %s", exc)

    return ChatResponse(
        response=response.content,
        provider=response.provider_name,
        model=response.model,
        success=response.success,
        diagnostics=response.metadata.get("diagnostics"),  # M22 trace (content-free) or None
    )


@router.get("/providers", summary="List all providers and their current availability")
async def providers() -> list[dict[str, Any]]:
    """
    Returns metadata for every configured provider adapter.

    Each entry includes:
      - name: provider key (e.g. "claude", "gemini")
      - enabled: whether it's enabled in config/providers.yaml
      - available: whether it can actually be used right now
      - cost_tier: "low" | "medium" | "high"
      - type: "cli" | "api" | "stub"
    """
    if main._router is None:
        raise HTTPException(
            status_code=503,
            detail="ProviderRouter is not available. Check startup logs.",
        )

    # M26.5: list_providers() probes adapter availability (Ollama does a ~1s
    # network health check, CLI adapters shell out) — run it off the loop.
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(main._router.list_providers),
            timeout=main._PROVIDERS_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=503, detail="Provider listing timed out.") from None
