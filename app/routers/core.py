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
import json
import re
import time
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from core.config import get_settings
from core.logger import logger
from providers.base import Message, ProviderResponse

from app.models import (
    ChatRequest, ChatResponse,
    ProfileActivateRequest,
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


_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@router.get("/profiles", summary="List available profiles (M28.5)")
async def profiles_list() -> list[dict[str, Any]]:
    """
    Every directory under profiles/ that contains a parseable profile.yaml,
    with its display name and whether it is the active one.
    """
    from core.config import profiles_dir  # noqa: PLC0415
    from core.loader import load_yaml  # noqa: PLC0415

    active = get_settings().active_profile
    out: list[dict[str, Any]] = []
    base = profiles_dir()
    if not base.exists():
        return out
    for entry in sorted(base.iterdir()):
        if not entry.is_dir() or not (entry / "profile.yaml").exists():
            continue
        try:
            data = load_yaml(entry / "profile.yaml") or {}
        except Exception:  # noqa: BLE001 — unreadable profile listed as broken
            data = {}
        out.append(
            {
                "name": entry.name,
                "display_name": data.get("name", entry.name),
                "active": entry.name == active,
            }
        )
    return out


@router.post("/profiles/activate", summary="Switch the active profile at runtime (M28.5)")
async def profiles_activate(body: ProfileActivateRequest) -> dict[str, Any]:
    """
    Activate profiles/<name> without a restart.

    Persists the selection to config/active_profile.yaml (which beats the
    ACTIVE_PROFILE env — see core/config.py resolution order; the CLI's
    --profile flag still beats both), then reinitializes the profile-bound
    state (_profile_data, memory, saved items). In-flight requests finish
    against the OLD managers (handlers bind main.X at call time); new
    requests see the new profile. Never touches .env.
    """
    from core.config import APP_ROOT, active_profile_dir, profiles_dir  # noqa: PLC0415
    from core.loader import load_yaml, save_yaml  # noqa: PLC0415
    from memory.manager import MemoryManager  # noqa: PLC0415
    from saved.manager import SavedItemsManager  # noqa: PLC0415

    name = body.name.strip()
    if not _PROFILE_NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail="Invalid profile name (letters, digits, - and _ only).",
        )
    target = profiles_dir() / name / "profile.yaml"
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Profile not found: {name}")
    data = load_yaml(target)
    if not isinstance(data, dict) or not data:
        raise HTTPException(
            status_code=400, detail=f"Profile '{name}' has an invalid profile.yaml."
        )

    def _switch() -> None:
        save_yaml(
            APP_ROOT / "config" / "active_profile.yaml",
            {"active_profile": name},
            sort_keys=False,
        )
        get_settings.cache_clear()
        # REVIEW-3.0 F5: update-then-prune, never clear()+update() — /chat
        # readers in other worker threads share this dict and must never
        # observe it empty. Every intermediate state is a mix of two VALID
        # profiles; the object identity is preserved (managers hold the ref).
        main._profile_data.update(data)
        for stale_key in [k for k in main._profile_data if k not in data]:
            del main._profile_data[stale_key]
        main._memory = MemoryManager(active_profile_dir(), main._profile_data)
        main._saved = SavedItemsManager(active_profile_dir())
        # M29.1: conversations are per-profile too.
        from history.manager import ConversationStore  # noqa: PLC0415

        main._history = ConversationStore(active_profile_dir())

    await asyncio.to_thread(_switch)
    logger.info("Profile switched to '%s' (runtime, M28.5).", name)
    main.write_ops_event(
        event="profile_activate", outcome="success", detail={"profile": name}
    )
    return {
        "activated": True,
        "name": name,
        "display_name": data.get("name", name),
        "note": (
            "Selection persisted to config/active_profile.yaml — survives "
            "restarts and applies to the CLI's next run. In-flight requests "
            "finish on the previous profile."
        ),
    }


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

    # Build the full message list from history + the new user message via the
    # shared turn helper (M29.0) — one assembly path with the CLI.
    from core.chat_turn import (  # noqa: PLC0415
        build_turn_messages,
        record_turn,
        system_prompt_from,
    )

    messages: list[Message] = build_turn_messages(
        ((m.role, m.content) for m in request.history), request.message
    )
    system_prompt: str | None = system_prompt_from(main._profile_data)

    # Persistent history (M29.1): resolve/create the conversation, record the
    # user turn before routing. All best-effort — history must never block or
    # fail a chat.
    conv_id: str | None = request.conversation_id
    # REVIEW-3.0 F6: one validator, shared with the store — never re-inline.
    from history.manager import is_valid_conversation_id  # noqa: PLC0415

    if conv_id is not None and not is_valid_conversation_id(conv_id):
        raise HTTPException(status_code=400, detail="Invalid conversation_id.")
    if main._history is not None:
        try:
            if conv_id is None:
                conv_id = await asyncio.to_thread(main._history.new_conversation)
        except Exception as exc:  # noqa: BLE001 — degrade to unpersisted chat
            logger.warning("history unavailable for this turn (non-fatal): %s", exc)
            conv_id = None
        if conv_id is not None:
            await asyncio.to_thread(
                record_turn, main._history, conv_id, "user", request.message
            )
    else:
        conv_id = None

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

    # Fire-and-forget auto-extraction via the shared sync core (M29.0), still
    # wrapped here so a slow YAML write can neither block the loop nor fail an
    # answered chat (extract_memory itself swallows non-timeout errors).
    if main._memory is not None:
        from core.chat_turn import extract_memory  # noqa: PLC0415

        try:
            await asyncio.wait_for(
                asyncio.to_thread(extract_memory, main._memory, request.message, response.content),
                timeout=main._AUTO_EXTRACT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("auto_extract timed out after %ss (non-fatal)", main._AUTO_EXTRACT_TIMEOUT)

    # Record the assistant turn (M29.1) — best-effort, after routing.
    if conv_id is not None:
        await asyncio.to_thread(
            record_turn,
            main._history,
            conv_id,
            "assistant",
            response.content,
            {
                "provider": response.provider_name,
                "model": response.model,
                "success": response.success,
            },
        )

    return ChatResponse(
        response=response.content,
        provider=response.provider_name,
        model=response.model,
        success=response.success,
        diagnostics=response.metadata.get("diagnostics"),  # M22 trace (content-free) or None
        conversation_id=conv_id,
    )


# ---------------------------------------------------------------------------
# Streaming chat (M30)
# ---------------------------------------------------------------------------

# Sentinel returned by next(it, _STREAM_DONE) so StopIteration never crosses
# the thread boundary (StopIteration inside coroutine machinery is poison).
_STREAM_DONE: Any = object()


def _sse_frame(event: str, payload: dict[str, Any]) -> str:
    """
    One Server-Sent-Events frame: a named event with single-line JSON data.
    json.dumps never emits raw newlines (they are escaped inside strings), so
    the data field is always exactly one `data:` line.
    """
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _stream_done_payload(
    response: "ProviderResponse", conv_id: str | None
) -> dict[str, Any]:
    """
    The `done` event payload — mirrors ChatResponse (response/provider/model/
    success/diagnostics/conversation_id) so clients can treat it exactly like
    the buffered answer, plus `error` (streaming failures can occur after text
    was already delivered, where the response body alone can't carry a reason).
    """
    return {
        "response": response.content,
        "provider": response.provider_name,
        "model": response.model,
        "success": response.success,
        "diagnostics": response.metadata.get("diagnostics"),  # M22 trace or None
        "error": response.error,
        "conversation_id": conv_id,
    }


@router.post("/chat/stream", summary="Send a message; stream the reply as SSE (M30)")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """
    Streaming variant of POST /chat (M30). Emits Server-Sent Events:

        event: chunk   data: {"text": "…"}            0..n, as text arrives
        event: done    data: {ChatResponse fields}    exactly once, last

    Semantics are /chat's: same conversation_id validation/creation, same
    user-turn record before routing, same memory extraction and assistant-turn
    record on completion (both finish BEFORE the done frame is sent), same
    total _ROUTE_TIMEOUT budget. Non-streaming providers arrive as one chunk +
    done. On timeout the done frame carries success=false and "The request
    timed out." If the client disconnects mid-stream the request is abandoned
    (no assistant turn is recorded — the reply was never delivered). The
    buffered POST /chat is unchanged and remains the compatibility surface.
    """
    if main._router is None:
        raise HTTPException(
            status_code=503,
            detail="ProviderRouter is not available. Check startup logs.",
        )
    # Bound after the guard: the provider router is process-lifetime (never
    # re-bound by a profile switch, unlike _memory/_history), and the closure
    # below runs after this handler returns, where mypy can't narrow
    # main._router. Named provider_router: bare `router` is this module's
    # APIRouter.
    provider_router = main._router

    from core.chat_turn import (  # noqa: PLC0415
        build_turn_messages,
        extract_memory,
        record_turn,
        system_prompt_from,
    )
    from history.manager import is_valid_conversation_id  # noqa: PLC0415

    messages: list[Message] = build_turn_messages(
        ((m.role, m.content) for m in request.history), request.message
    )
    system_prompt: str | None = system_prompt_from(main._profile_data)

    # Conversation resolution + user-turn record: identical to /chat, and done
    # BEFORE streaming starts so a bad id is a plain 400, not a broken stream.
    conv_id: str | None = request.conversation_id
    if conv_id is not None and not is_valid_conversation_id(conv_id):
        raise HTTPException(status_code=400, detail="Invalid conversation_id.")
    if main._history is not None:
        try:
            if conv_id is None:
                conv_id = await asyncio.to_thread(main._history.new_conversation)
        except Exception as exc:  # noqa: BLE001 — degrade to unpersisted chat
            logger.warning("history unavailable for this turn (non-fatal): %s", exc)
            conv_id = None
        if conv_id is not None:
            await asyncio.to_thread(
                record_turn, main._history, conv_id, "user", request.message
            )
    else:
        conv_id = None

    async def event_source() -> AsyncIterator[str]:
        # Total budget mirrors /chat: _ROUTE_TIMEOUT across ALL providers'
        # attempts, however many chunks arrive. Each generator step runs in a
        # worker thread (M26.5 — the sync router must not block the loop).
        # CAVEAT (as /chat): a timed-out step's thread cannot be cancelled; the
        # orphaned generator keeps running to the adapter's own limit and is
        # discarded — we never touch the iterator again after abandoning it.
        deadline = time.monotonic() + main._ROUTE_TIMEOUT
        it = iter(
            provider_router.route_stream(messages, system_prompt, main._profile_data)
        )
        response: "ProviderResponse | None" = None
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                item = await asyncio.wait_for(
                    asyncio.to_thread(next, it, _STREAM_DONE), timeout=remaining
                )
                if item is _STREAM_DONE:
                    # Defensive: route_stream contractually ends with a done
                    # event; ending without one is treated as a failure below.
                    break
                kind, payload = item
                if kind == "chunk":
                    yield _sse_frame("chunk", {"text": payload})
                elif kind == "done":
                    response = payload
                    break
        except asyncio.TimeoutError:
            logger.error("Router timed out after %ss (chat/stream)", main._ROUTE_TIMEOUT)
            yield _sse_frame(
                "done",
                {
                    "response": "The request timed out.",
                    "provider": "none",
                    "model": None,
                    "success": False,
                    "diagnostics": None,
                    "error": None,
                    "conversation_id": conv_id,
                },
            )
            return
        except Exception as exc:  # noqa: BLE001 — mid-response: no 500 left to send
            logger.error("chat/stream internal error: %s", exc)
            yield _sse_frame(
                "done",
                {
                    "response": "",
                    "provider": "none",
                    "model": None,
                    "success": False,
                    "diagnostics": None,
                    "error": f"internal error: {exc}",
                    "conversation_id": conv_id,
                },
            )
            return

        if response is None:  # generator ended without a done event (defensive)
            response = ProviderResponse(
                success=False,
                content="",
                provider_name="none",
                error="stream ended without a final response",
            )

        # Post-turn bookkeeping BEFORE the done frame goes out — /chat's exact
        # order (memory → assistant record → respond), so when the client sees
        # `done` the conversation file already holds the turn.
        if main._memory is not None:
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(
                        extract_memory, main._memory, request.message, response.content
                    ),
                    timeout=main._AUTO_EXTRACT_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "auto_extract timed out after %ss (non-fatal)",
                    main._AUTO_EXTRACT_TIMEOUT,
                )
        if conv_id is not None:
            await asyncio.to_thread(
                record_turn,
                main._history,
                conv_id,
                "assistant",
                response.content,
                {
                    "provider": response.provider_name,
                    "model": response.model,
                    "success": response.success,
                },
            )

        yield _sse_frame("done", _stream_done_payload(response, conv_id))

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
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
