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
from typing import TYPE_CHECKING, Any, Callable

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

        routing_cfg: dict[str, Any] = profile_config.get("routing", {})
        mode: str = routing_cfg.get("mode", "balanced")
        preferred: str | None = routing_cfg.get("preferred_provider") or None

        ordered_names = self._get_ordered_names(mode)

        # Build the final attempt order:
        # 1. preferred_provider first (if set and in our adapter map)
        # 2. then the mode-ordered list (deduplicated, preferred already tried)
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

        # Diagnostics ledger (None when disabled → routing is the unchanged path).
        trace = (
            RequestTrace(mode=mode, attempt_order=list(attempt_order))
            if self._diag_enabled
            else None
        )
        t_start = time.perf_counter()

        errors: list[str] = []

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

            call_t0 = time.perf_counter()
            try:
                response: "ProviderResponse" = adapter.complete(messages, system_prompt)
            except Exception as exc:  # noqa: BLE001
                call_ms = (time.perf_counter() - call_t0) * 1000.0
                error_msg = f"{name}: exception during complete(): {exc}"
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
                if not self._fallback_on_error:
                    break
                continue
            call_ms = (time.perf_counter() - call_t0) * 1000.0

            if rec is not None:
                rec.call_ms = call_ms
                rec.duration_ms = avail_ms + call_ms
                rec.model = response.model
                rec.transport = self._transport_for(name, response)

            if response.success:
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
                return self._finalize_trace(trace, t_start, name, response)

            # Provider returned success=False
            error_msg = f"{name}: {response.error or 'unknown error'}"
            logger.warning("Router: provider failed — %s (%.0fms)", error_msg, call_ms)
            errors.append(error_msg)
            if rec is not None:
                rec.outcome = "failure"
                rec.error = short_error(response.error)
                rec.error_kind = classify_error_kind("failure", response.error)
                assert trace is not None  # rec is non-None iff trace is (see rec assignment)
                trace.add(rec)

            if not self._fallback_on_error:
                break

        # All providers exhausted
        all_errors = "; ".join(errors) if errors else "no providers attempted"
        logger.error("Router: all providers failed. Errors: %s", all_errors)

        failure = ProviderResponse(
            success=False,
            content="All providers failed.",
            provider_name="none",
            error=all_errors,
        )
        return self._finalize_trace(trace, t_start, None, failure)

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
