"""
providers/router.py — ProviderRouter for Athena Assistant.

The router:
  - Reads config/providers.yaml on init via core/loader.py
  - Instantiates only enabled, non-stub adapters
  - Implements three routing modes: quality-first, balanced, budget-first
  - Supports a preferred_provider override from the active profile config
  - Falls back through the ordered list on failure
  - Logs routing decisions when log_provider_choice is enabled

Usage:
    from providers.router import ProviderRouter
    router = ProviderRouter()
    response = router.route(messages, system_prompt, profile_config)
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Callable, Iterator

from core.config import APP_ROOT
from core.loader import load_yaml
from core.logger import logger
from diagnostics.store import (
    ProviderCallRecord,
    RequestTrace,
    classify_error_kind,
    format_summary,
    get_diagnostics_store,
    short_error,
)

if TYPE_CHECKING:
    from providers.base import Message, ProviderAdapter, ProviderResponse

# ---------------------------------------------------------------------------
# Adapter registry — maps config key → (module_path, class_name)
# Imported lazily inside _load_adapters() so missing CLIs never crash import.
# ---------------------------------------------------------------------------
_ADAPTER_REGISTRY: dict[str, tuple[str, str]] = {
    "claude":      ("providers.claude",      "ClaudeAdapter"),
    "gemini":      ("providers.gemini",      "GeminiAdapter"),
    "grok":        ("providers.grok",        "GrokAdapter"),
    "chatgpt":     ("providers.chatgpt",     "ChatGPTAPIAdapter"),
    "ollama":      ("providers.ollama",      "OllamaAdapter"),
    "hermes":      ("providers.hermes",      "HermesAdapter"),
    "chatgpt_cli": ("providers.chatgpt_cli", "ChatGPTCLIAdapter"),
}


def _import_adapter(module_path: str, class_name: str) -> type | None:
    """
    Dynamically import an adapter class.

    Returns None on ImportError so the router can continue without it.
    """
    try:
        import importlib  # noqa: PLC0415
        mod = importlib.import_module(module_path)
        return getattr(mod, class_name)
    except (ImportError, AttributeError) as exc:
        logger.warning("Could not import adapter %s.%s: %s", module_path, class_name, exc)
        return None


class ProviderRouter:
    """
    Routes chat requests to the best available AI provider.

    Routing modes (read from profile_config["routing"]["mode"]):
      - quality-first  → tries adapters in providers.yaml ranking.quality_first order
      - balanced       → tries adapters in providers.yaml ranking.balanced order
      - budget-first   → tries adapters in providers.yaml ranking.budget_first order

    If profile_config["routing"]["preferred_provider"] is set and non-null,
    that provider is tried first regardless of mode.

    Falls back through the list on exception or success=False.
    """

    def __init__(self) -> None:
        providers_path = APP_ROOT / "config" / "providers.yaml"
        self._config: dict[str, Any] = load_yaml(providers_path)

        providers_section: dict[str, Any] = self._config.get("providers", {})
        self._ranking: dict[str, list[str]] = providers_section.get("ranking", {})
        self._adapter_configs: dict[str, Any] = providers_section.get("adapters", {})
        self._fallback_on_error: bool = providers_section.get("fallback_on_error", True)
        self._log_provider_choice: bool = providers_section.get("log_provider_choice", True)

        # Diagnostics (Milestone 22) — measure-only; never changes routing.
        diagnostics_cfg: dict[str, Any] = providers_section.get("diagnostics", {})
        self._diag_enabled: bool = bool(diagnostics_cfg.get("enabled", True))
        self._diag_log_level: str = str(diagnostics_cfg.get("log_level", "info")).lower()
        try:
            get_diagnostics_store().set_maxlen(int(diagnostics_cfg.get("ring_buffer_size", 50)))
        except Exception:  # noqa: BLE001 — diagnostics config must never break init
            pass

        # Instantiate all known adapters (enabled + disabled + stubs)
        # The router tracks them all for list_providers(); only enabled non-stubs
        # are used for actual routing.
        self._all_adapters: dict[str, "ProviderAdapter"] = {}
        self._load_adapters()

    # ------------------------------------------------------------------
    # Initialisation helpers
    # ------------------------------------------------------------------

    def _load_adapters(self) -> None:
        """Instantiate every adapter in the registry, storing in _all_adapters."""
        for key, (module_path, class_name) in _ADAPTER_REGISTRY.items():
            cls = _import_adapter(module_path, class_name)
            if cls is None:
                continue
            try:
                instance = cls()
                self._all_adapters[key] = instance
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not instantiate adapter %s: %s", key, exc)

    def _is_enabled(self, name: str) -> bool:
        """Return True if the adapter is marked enabled in providers.yaml."""
        cfg = self._adapter_configs.get(name, {})
        return bool(cfg.get("enabled", False))

    def _is_stub(self, name: str) -> bool:
        """Return True if the adapter is typed as 'stub' in providers.yaml."""
        cfg = self._adapter_configs.get(name, {})
        return cfg.get("type", "") == "stub"

    def _get_ordered_names(self, mode: str) -> list[str]:
        """
        Return the provider order for the given routing mode.

        Falls back to quality_first if the mode key is unrecognised.
        """
        mode_map = {
            "quality-first": "quality_first",
            "balanced":      "balanced",
            "budget-first":  "budget_first",
        }
        # M26.8: an unrecognised mode falls back to BALANCED (the neutral middle)
        # and logs a warning — never silently to quality_first, which is the
        # most-expensive order and the worst default for a typo (e.g. the
        # underscore form "budget_first").
        key = mode_map.get(mode)
        if key is None:
            logger.warning(
                "Router: unknown routing mode %r — falling back to 'balanced'.", mode
            )
            key = "balanced"
        return list(self._ranking.get(key, []))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route(
        self,
        messages: "list[Message]",
        system_prompt: str | None,
        profile_config: dict[str, Any],
        on_attempt: "Callable[[dict[str, Any]], None] | None" = None,
    ) -> "ProviderResponse":
        """
        Route a chat request to the best available provider.

        ``on_attempt`` is an optional, **measure-only** progress callback (M27.0):
        it is invoked with ``{"provider", "transport", "mode"}`` immediately
        before each *available* provider is called, letting a caller (e.g. the
        CLI live status line) show which provider is being tried right now.
        Callback exceptions are swallowed — like diagnostics, it can never change
        routing or the result.

        Returns a ProviderResponse. Never raises.
        """
        from providers.base import ProviderResponse  # noqa: PLC0415 — lazy

        mode, attempt_order = self._build_attempt_order(profile_config)

        # Diagnostics ledger (None when disabled → routing is the unchanged path).
        trace = (
            RequestTrace(mode=mode, attempt_order=list(attempt_order))
            if self._diag_enabled
            else None
        )
        t_start = time.perf_counter()

        errors: list[str] = []

        for name, adapter, rec, avail_ms in self._callable_attempts(
            attempt_order, trace, mode, errors, on_attempt
        ):
            call_t0 = time.perf_counter()
            try:
                response: "ProviderResponse" = adapter.complete(messages, system_prompt)
            except Exception as exc:  # noqa: BLE001
                call_ms = (time.perf_counter() - call_t0) * 1000.0
                self._attempt_exception(trace, rec, name, avail_ms, call_ms, exc, errors)
                if not self._fallback_on_error:
                    break
                continue
            call_ms = (time.perf_counter() - call_t0) * 1000.0

            self._attempt_record_response(rec, name, response, avail_ms, call_ms)

            if response.success:
                self._attempt_ok(trace, rec, name, response, call_ms)
                return self._finalize_trace(trace, t_start, name, response)

            # Provider returned success=False
            self._attempt_failure(trace, rec, name, response, call_ms, errors)

            if not self._fallback_on_error:
                break

        # All providers exhausted
        return self._finalize_trace(
            trace, t_start, None, self._all_failed_response(errors, ProviderResponse)
        )

    def route_stream(
        self,
        messages: "list[Message]",
        system_prompt: str | None,
        profile_config: dict[str, Any],
        on_attempt: "Callable[[dict[str, Any]], None] | None" = None,
    ) -> "Iterator[tuple[str, Any]]":
        """
        Stream a chat request (M30). A generator yielding
        ``("chunk", str)`` events as provider text arrives, terminated by
        **exactly one** ``("done", ProviderResponse)`` event. Never raises.

        Same attempt loop, order, diagnostics, and ``on_attempt`` callback as
        ``route()`` (shared internals — the routing logic is not forked).
        Delivery semantics:

        - streaming adapter (``supports_streaming()``): its chunks are passed
          through as they arrive; the adapter's final ProviderResponse becomes
          the ``done`` event (trace attached, as ``route()``).
        - non-streaming adapter: buffered ``complete()``, degraded to one
          ``("chunk", full_text)`` + ``("done", …)``.
        - a provider that fails having emitted ZERO chunks falls through to
          the next provider, exactly like ``route()``.
        - a provider that fails AFTER emitting chunks STOPS the request (text
          cannot be un-emitted; switching answers mid-stream would splice two
          providers' prose) — the failure is the ``done`` event.
        - all providers exhausted → same "All providers failed." response as
          ``route()``.

        Diagnostics note: for a streaming attempt, ``call_ms``/``duration_ms``
        span first-call to final-response — the generator is suspended at each
        yielded chunk, so DELIVERY time (SSE write, client consumption) is
        included. That is the user-perceived answer time, which is what the
        summary line reports; it is not directly comparable to a buffered
        attempt's pure provider latency.
        """
        from providers.base import ProviderResponse  # noqa: PLC0415 — lazy

        mode, attempt_order = self._build_attempt_order(profile_config)
        trace = (
            RequestTrace(mode=mode, attempt_order=list(attempt_order))
            if self._diag_enabled
            else None
        )
        t_start = time.perf_counter()

        errors: list[str] = []

        for name, adapter, rec, avail_ms in self._callable_attempts(
            attempt_order, trace, mode, errors, on_attempt
        ):
            try:
                streaming = bool(adapter.supports_streaming())
            except Exception:  # noqa: BLE001 — a capability probe must never break routing
                streaming = False

            call_t0 = time.perf_counter()

            if not streaming:
                # ---- Buffered degrade: identical to route(), then one chunk ----
                try:
                    response: "ProviderResponse" = adapter.complete(messages, system_prompt)
                except Exception as exc:  # noqa: BLE001
                    call_ms = (time.perf_counter() - call_t0) * 1000.0
                    self._attempt_exception(trace, rec, name, avail_ms, call_ms, exc, errors)
                    if not self._fallback_on_error:
                        break
                    continue
                call_ms = (time.perf_counter() - call_t0) * 1000.0
                self._attempt_record_response(rec, name, response, avail_ms, call_ms)
                if response.success:
                    self._attempt_ok(trace, rec, name, response, call_ms)
                    final = self._finalize_trace(trace, t_start, name, response)
                    if final.content:
                        yield ("chunk", final.content)
                    yield ("done", final)
                    return
                self._attempt_failure(trace, rec, name, response, call_ms, errors)
                if not self._fallback_on_error:
                    break
                continue

            # ---- Streaming adapter: pass chunks through as they arrive ----
            emitted = False
            final_resp: "ProviderResponse | None" = None
            try:
                for item in adapter.complete_stream(messages, system_prompt):
                    if isinstance(item, str):
                        if item:
                            emitted = True
                            yield ("chunk", item)
                        continue
                    final_resp = item  # the final ProviderResponse ends the stream
                    break
            except Exception as exc:  # noqa: BLE001
                call_ms = (time.perf_counter() - call_t0) * 1000.0
                self._attempt_exception(
                    trace, rec, name, avail_ms, call_ms, exc, errors,
                    during="complete_stream()",
                )
                if emitted:
                    # Text already reached the client — stop with a failure.
                    failure = ProviderResponse(
                        success=False,
                        content="",
                        provider_name=name,
                        error=f"{name}: exception during complete_stream(): {exc}",
                    )
                    yield ("done", self._finalize_trace(trace, t_start, None, failure))
                    return
                if not self._fallback_on_error:
                    break
                continue
            call_ms = (time.perf_counter() - call_t0) * 1000.0

            if final_resp is None:
                # Contract violation (generator ended without a final response):
                # synthesize a failure so bookkeeping and fallback stay honest.
                final_resp = ProviderResponse(
                    success=False,
                    content="",
                    provider_name=name,
                    error="provider stream ended without a final response",
                )

            self._attempt_record_response(rec, name, final_resp, avail_ms, call_ms)

            if final_resp.success:
                self._attempt_ok(trace, rec, name, final_resp, call_ms)
                final = self._finalize_trace(trace, t_start, name, final_resp)
                if not emitted and final.content:
                    # Defensive: a success whose text never arrived as chunks
                    # still reaches the client (degrade to one buffered chunk).
                    yield ("chunk", final.content)
                yield ("done", final)
                return

            self._attempt_failure(trace, rec, name, final_resp, call_ms, errors)

            if emitted:
                # Chunks already shown — cannot fall through to another provider.
                yield ("done", self._finalize_trace(trace, t_start, None, final_resp))
                return

            if not self._fallback_on_error:
                break

        # All providers exhausted (or fallback disabled after a failure)
        yield (
            "done",
            self._finalize_trace(
                trace, t_start, None, self._all_failed_response(errors, ProviderResponse)
            ),
        )

    # ------------------------------------------------------------------
    # Shared attempt iteration (M30) — ONE routing loop, two delivery modes.
    # route() and route_stream() must never fork their routing behavior.
    # ------------------------------------------------------------------

    def _build_attempt_order(
        self, profile_config: dict[str, Any]
    ) -> tuple[str, list[str]]:
        """
        Resolve (mode, attempt_order) from the profile config:
        preferred_provider first (if set), then the mode-ranked list,
        deduplicated. Logs the plan when log_provider_choice is on.
        """
        routing_cfg: dict[str, Any] = profile_config.get("routing", {})
        mode: str = routing_cfg.get("mode", "balanced")
        preferred: str | None = routing_cfg.get("preferred_provider") or None

        ordered_names = self._get_ordered_names(mode)

        attempt_order: list[str] = []
        if preferred:
            attempt_order.append(preferred)
        for name in ordered_names:
            if name not in attempt_order:
                attempt_order.append(name)

        if self._log_provider_choice:
            logger.info(
                "Router: mode=%s preferred=%s attempt_order=%s",
                mode,
                preferred or "none",
                attempt_order,
            )
        return mode, attempt_order

    def _callable_attempts(
        self,
        attempt_order: list[str],
        trace: "RequestTrace | None",
        mode: str,
        errors: list[str],
        on_attempt: "Callable[[dict[str, Any]], None] | None",
    ) -> "Iterator[tuple[str, ProviderAdapter, ProviderCallRecord | None, float]]":
        """
        Yield ``(name, adapter, rec, avail_ms)`` for each adapter that passes
        the registry / enabled / stub / availability checks, in attempt order.
        All skip bookkeeping (debug logs, diagnostics records, the errors
        list) and the M27.0 ``on_attempt`` announcement happen in here so
        route() and route_stream() iterate identically.
        """
        for name in attempt_order:
            rec = ProviderCallRecord(provider=name) if trace is not None else None
            adapter = self._all_adapters.get(name)

            if adapter is None:
                logger.debug("Router: adapter '%s' not found in registry — skipping.", name)
                self._diag_skip(trace, rec, "skipped", "adapter not in registry")
                continue

            if not self._is_enabled(name):
                logger.debug("Router: adapter '%s' is disabled — skipping.", name)
                self._diag_skip(trace, rec, "skipped", "disabled")
                continue

            if self._is_stub(name):
                logger.debug("Router: adapter '%s' is a stub — skipping.", name)
                self._diag_skip(trace, rec, "skipped", "stub", transport="stub")
                continue

            avail_t0 = time.perf_counter()
            available = adapter.is_available()
            avail_ms = (time.perf_counter() - avail_t0) * 1000.0
            if rec is not None:
                rec.availability_ms = avail_ms
                rec.transport = self._transport_for(name, None)

            if not available:
                logger.debug(
                    "Router: adapter '%s' is not available (CLI missing or key not set) — skipping.",
                    name,
                )
                errors.append(f"{name}: not available")
                if rec is not None:
                    rec.outcome = "unavailable"
                    rec.duration_ms = avail_ms
                    assert trace is not None  # rec is non-None iff trace is (see rec assignment)
                    trace.add(rec)
                continue

            if self._log_provider_choice:
                logger.info("Router: attempting provider '%s' (mode=%s).", name, mode)

            # Live progress (M27.0): announce the provider we're about to call.
            # Measure-only — wrapped so a bad callback can never affect routing.
            attempt_transport = rec.transport if rec is not None else self._transport_for(name, None)
            self._notify_attempt(
                on_attempt,
                {"provider": name, "transport": attempt_transport, "mode": mode},
            )

            yield name, adapter, rec, avail_ms

    def _attempt_exception(
        self,
        trace: "RequestTrace | None",
        rec: "ProviderCallRecord | None",
        name: str,
        avail_ms: float,
        call_ms: float,
        exc: Exception,
        errors: list[str],
        during: str = "complete()",
    ) -> None:
        """Bookkeeping for an adapter call that raised (log, errors, trace)."""
        error_msg = f"{name}: exception during {during}: {exc}"
        logger.warning("Router: %s (%.0fms)", error_msg, call_ms)
        errors.append(error_msg)
        if rec is not None:
            rec.outcome = "exception"
            rec.call_ms = call_ms
            rec.duration_ms = avail_ms + call_ms
            rec.error = short_error(exc)
            rec.error_kind = classify_error_kind("exception", None, exc)
            assert trace is not None  # rec is non-None iff trace is (see rec assignment)
            trace.add(rec)

    def _attempt_record_response(
        self,
        rec: "ProviderCallRecord | None",
        name: str,
        response: "ProviderResponse",
        avail_ms: float,
        call_ms: float,
    ) -> None:
        """Fill the diagnostics record from a completed (ok-or-failed) response."""
        if rec is None:
            return
        rec.call_ms = call_ms
        rec.duration_ms = avail_ms + call_ms
        rec.model = response.model
        rec.transport = self._transport_for(name, response)
        # Token usage (M27.1): best-effort, content-free. Present for API
        # transports; None ("unavailable") for CLI transports.
        meta = response.metadata
        rec.usage = meta.get("usage") if isinstance(meta, dict) else None

    def _attempt_ok(
        self,
        trace: "RequestTrace | None",
        rec: "ProviderCallRecord | None",
        name: str,
        response: "ProviderResponse",
        call_ms: float,
    ) -> None:
        """Bookkeeping for a successful attempt (log + trace record)."""
        if self._log_provider_choice:
            logger.info(
                "Router: provider '%s' succeeded (model=%s, %.0fms).",
                name,
                response.model or "n/a",
                call_ms,
            )
        if rec is not None:
            rec.outcome = "ok"
            assert trace is not None  # rec is non-None iff trace is (see rec assignment)
            trace.add(rec)

    def _attempt_failure(
        self,
        trace: "RequestTrace | None",
        rec: "ProviderCallRecord | None",
        name: str,
        response: "ProviderResponse",
        call_ms: float,
        errors: list[str],
    ) -> None:
        """Bookkeeping for a success=False response (log, errors, trace)."""
        error_msg = f"{name}: {response.error or 'unknown error'}"
        logger.warning("Router: provider failed — %s (%.0fms)", error_msg, call_ms)
        errors.append(error_msg)
        if rec is not None:
            rec.outcome = "failure"
            rec.error = short_error(response.error)
            rec.error_kind = classify_error_kind("failure", response.error)
            assert trace is not None  # rec is non-None iff trace is (see rec assignment)
            trace.add(rec)

    @staticmethod
    def _all_failed_response(
        errors: list[str], response_cls: "type[ProviderResponse]"
    ) -> "ProviderResponse":
        """The canonical all-providers-exhausted failure (shared by both modes)."""
        all_errors = "; ".join(errors) if errors else "no providers attempted"
        logger.error("Router: all providers failed. Errors: %s", all_errors)
        return response_cls(
            success=False,
            content="All providers failed.",
            provider_name="none",
            error=all_errors,
        )

    @staticmethod
    def _notify_attempt(
        callback: "Callable[[dict[str, Any]], None] | None",
        info: dict[str, Any],
    ) -> None:
        """Fire a progress callback (M27.0), swallowing any error. Best-effort:
        a caller's display glitch must never perturb routing."""
        if callback is None:
            return
        try:
            callback(info)
        except Exception:  # noqa: BLE001 — progress is cosmetic; never propagate
            pass

    # ------------------------------------------------------------------
    # Diagnostics helpers (Milestone 22) — measure-only; never raise
    # ------------------------------------------------------------------

    def _diag_skip(
        self,
        trace: "RequestTrace | None",
        rec: "ProviderCallRecord | None",
        outcome: str,
        reason: str,
        transport: str | None = None,
    ) -> None:
        """Record a skipped attempt (disabled / stub / missing) on the trace."""
        if trace is None or rec is None:
            return
        rec.outcome = outcome
        rec.error = reason
        rec.transport = transport if transport is not None else self._transport_for(rec.provider, None)
        trace.add(rec)

    def _transport_for(self, name: str, response: "ProviderResponse | None") -> str:
        """
        Canonical transport for a provider: ``response.metadata['transport']``
        when the adapter provides it (e.g. Grok, M21), else the adapter's
        configured ``type`` (cli/api/stub) from providers.yaml.
        """
        if response is not None:
            t = response.metadata.get("transport")
            if t:
                return str(t)
        # M26.8: for records with no response metadata (unavailable / skipped /
        # exception), consult a dynamic-transport adapter (e.g. Grok cli|api) so
        # the trace reports the REAL transport rather than the static
        # providers.yaml type — otherwise "grok/cli unavailable" is shown when
        # the api key is what's actually missing. Mirrors list_providers() (M26.2).
        adapter = self._all_adapters.get(name)
        resolver = getattr(adapter, "transport", None)
        if callable(resolver):
            try:
                resolved = resolver()
                if resolved:
                    return str(resolved)
            except Exception:  # noqa: BLE001 — a label must never break routing
                pass
        typ = self._adapter_configs.get(name, {}).get("type")
        return str(typ) if typ else "unknown"

    def _finalize_trace(
        self,
        trace: "RequestTrace | None",
        t_start: float,
        selected: str | None,
        response: "ProviderResponse",
    ) -> "ProviderResponse":
        """
        Attach the trace to the response metadata, store it, and log a one-line
        summary. Wrapped so a diagnostics failure can never change the routing
        result or raise.
        """
        if trace is None:
            return response
        try:
            trace.total_ms = (time.perf_counter() - t_start) * 1000.0
            trace.selected = selected
            # Merge into metadata so adapter-provided keys (e.g. transport) survive.
            try:
                response.metadata["diagnostics"] = trace.as_dict()
            except Exception:  # noqa: BLE001
                pass
            get_diagnostics_store().record(trace)
            line = format_summary(trace)
            if self._diag_log_level == "debug":
                logger.debug(line)
            else:
                logger.info(line)
        except Exception:  # noqa: BLE001 — diagnostics must never break routing
            pass
        return response

    def list_providers(self) -> list[dict[str, Any]]:
        """
        Return metadata for every known provider adapter.

        Shape: [{"name": str, "enabled": bool, "available": bool,
                 "cost_tier": str, "type": str}, ...]
        """
        result: list[dict[str, Any]] = []

        for name, adapter in self._all_adapters.items():
            cfg = self._adapter_configs.get(name, {})
            provider_type = cfg.get("type", "unknown")

            # Effective transport (M26.2): if the adapter resolves its own
            # transport (e.g. Grok cli|api), report that truthfully; otherwise
            # fall back to the static providers.yaml `type`. Computed regardless
            # of enabled/available so the listing always shows the real path.
            resolver = getattr(adapter, "transport", None)
            if callable(resolver):
                try:
                    resolved = resolver()
                    if resolved:
                        provider_type = resolved
                except Exception:  # noqa: BLE001 — never let a listing fail
                    pass

            enabled = self._is_enabled(name)

            # Only call is_available() for non-stub adapters to avoid noise
            if self._is_stub(name) or not enabled:
                available = False
            else:
                try:
                    available = adapter.is_available()
                except Exception:  # noqa: BLE001
                    available = False

            result.append(
                {
                    "name": adapter.name(),
                    "enabled": enabled,
                    "available": available,
                    "cost_tier": adapter.cost_tier(),
                    "type": provider_type,
                }
            )

        # Return in a stable order: follow registry insertion order
        return result
