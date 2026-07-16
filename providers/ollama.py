"""
providers/ollama.py — Ollama (local LLM) adapter for Athena Assistant.

Talks to a local or self-hosted Ollama instance over its OpenAI-compatible
HTTP API, reusing the `openai` Python SDK with `base_url` pointed at the
Ollama endpoint. This is the same SDK plumbing used by providers/chatgpt.py;
only the base_url, api_key, model, and timeouts differ.

ONE ACTIVE MODEL PER CONFIG
  The active model is read from the OLLAMA_MODEL environment variable. Switch
  models by changing that value (and restarting); the adapter performs no
  automatic multi-model selection. That is intentionally out of scope.

CONFIGURATION (environment variables)
  OLLAMA_API_URL   Endpoint base URL. Default: http://localhost:11434/v1
                   May point at another machine, e.g. http://192.168.1.20:11434/v1
  OLLAMA_MODEL     Active model name, e.g. "gemma4" or "qwen3.6". REQUIRED —
                   if unset, the provider reports itself unavailable.
  OLLAMA_API_KEY   Optional. Ollama ignores auth, but the openai SDK requires a
                   non-empty key, so a dummy value ("ollama") is used if unset.
  OLLAMA_TIMEOUT   Optional. Completion timeout in seconds. Default: 120
                   (matches the 120s convention used by the CLI adapters).

Availability: active health check (GET /models via the SDK) with a short
              (~1s) timeout; treated as unavailable on any failure/timeout.
Cost tier: low
"""

from __future__ import annotations

import os
from typing import Iterator

from providers.base import (
    Message,
    ProviderAdapter,
    ProviderResponse,
    extract_openai_usage,
)

# ---------------------------------------------------------------------------
# Defaults / constants
# ---------------------------------------------------------------------------
DEFAULT_BASE_URL: str = "http://localhost:11434/v1"
DEFAULT_COMPLETION_TIMEOUT: float = 120.0  # seconds — matches CLI adapters
HEALTHCHECK_TIMEOUT: float = 1.0           # seconds — keep routing snappy
DUMMY_API_KEY: str = "ollama"              # Ollama ignores auth; SDK needs non-empty


def _base_url() -> str:
    """Resolve the Ollama endpoint base URL from the environment."""
    url = os.environ.get("OLLAMA_API_URL", "").strip()
    return url or DEFAULT_BASE_URL


def _model() -> str:
    """Resolve the active Ollama model name from the environment (may be empty)."""
    return os.environ.get("OLLAMA_MODEL", "").strip()


def _api_key() -> str:
    """Resolve the API key — a dummy is used because Ollama ignores auth."""
    key = os.environ.get("OLLAMA_API_KEY", "").strip()
    return key or DUMMY_API_KEY


def _completion_timeout() -> float:
    """Resolve the completion timeout in seconds, falling back to the default."""
    raw = os.environ.get("OLLAMA_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_COMPLETION_TIMEOUT
    try:
        value = float(raw)
        return value if value > 0 else DEFAULT_COMPLETION_TIMEOUT
    except ValueError:
        return DEFAULT_COMPLETION_TIMEOUT


class OllamaAdapter(ProviderAdapter):
    """Adapter that calls a local Ollama server via its OpenAI-compatible API."""

    def name(self) -> str:
        return "ollama"

    def cost_tier(self) -> str:
        return "low"

    def is_available(self) -> bool:
        """
        Lightweight active health check.

        Returns True only if BOTH are satisfied:
          1. OLLAMA_MODEL is configured (a reachable server with no configured
             model cannot do useful work, so we do not advertise availability).
          2. A short GET /models call to the endpoint succeeds within
             HEALTHCHECK_TIMEOUT seconds.

        Never raises: any import error, connection error, or timeout results
        in False so the router can simply skip this provider.
        """
        if not _model():
            return False

        try:
            import openai  # noqa: PLC0415 — lazy so a missing install never breaks import
        except ImportError:
            return False

        try:
            client = openai.OpenAI(
                base_url=_base_url(),
                api_key=_api_key(),
                timeout=HEALTHCHECK_TIMEOUT,
                max_retries=0,
            )
            # Cheap reachability probe — lists installed models, no inference.
            client.models.list()
            return True
        except Exception:  # noqa: BLE001 — any failure means "not available"
            return False

    def complete(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> ProviderResponse:
        # Lazy import — keeps the module loadable even without the openai package
        try:
            import openai  # noqa: PLC0415
        except ImportError:
            return ProviderResponse(
                success=False,
                content="",
                provider_name="ollama",
                error=(
                    "The 'openai' package is not installed. "
                    "Run: pip install openai>=1.0"
                ),
            )

        model = _model()
        if not model:
            return ProviderResponse(
                success=False,
                content="",
                provider_name="ollama",
                error="OLLAMA_MODEL is not set; configure a local model (e.g. gemma4, qwen3.6).",
            )

        base_url = _base_url()
        timeout = _completion_timeout()

        # Build the OpenAI-style messages payload
        api_messages: list[dict[str, str]] = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        for msg in messages:
            api_messages.append({"role": msg.role, "content": msg.content})

        try:
            client = openai.OpenAI(
                base_url=base_url,
                api_key=_api_key(),
                timeout=timeout,
                max_retries=0,
            )
            response = client.chat.completions.create(
                model=model,
                messages=api_messages,  # type: ignore[arg-type]
            )
            content = response.choices[0].message.content or ""
            usage = extract_openai_usage(response)
            # M30: empty output is a failure on every adapter, in both modes —
            # the router falls back instead of returning a blank answer.
            if not content.strip():
                return ProviderResponse(
                    success=False,
                    content="",
                    provider_name="ollama",
                    model=model,
                    error="Ollama returned no output.",
                    metadata={"usage": usage} if usage else {},
                )
            return ProviderResponse(
                content=content,
                provider_name="ollama",
                model=model,
                success=True,
                metadata={"usage": usage} if usage else {},
            )

        except openai.APITimeoutError:
            return ProviderResponse(
                success=False,
                content="",
                provider_name="ollama",
                model=model,
                error=f"Timeout: Ollama did not respond within {timeout:g} seconds.",
            )
        except openai.APIConnectionError as exc:
            return ProviderResponse(
                success=False,
                content="",
                provider_name="ollama",
                model=model,
                error=f"Connection error: could not reach Ollama at {base_url}: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 — base contract: never raise
            return ProviderResponse(
                success=False,
                content="",
                provider_name="ollama",
                model=model,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Streaming (M30)
    # ------------------------------------------------------------------

    def supports_streaming(self) -> bool:
        return True

    def complete_stream(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> "Iterator[str | ProviderResponse]":
        """
        Stream a completion (M30): yield text chunks, then the final
        ProviderResponse (assembled content). Unlike chatgpt, no
        ``stream_options={"include_usage": True}`` is sent — OpenAI-compat
        servers vary in support and a rejected request parameter would break
        streaming outright. If the server volunteers usage on a chunk anyway
        it is recorded; otherwise usage is honestly absent. Error strings and
        client bounding (timeout, max_retries=0) match complete().
        """
        try:
            import openai  # noqa: PLC0415
        except ImportError:
            yield ProviderResponse(
                success=False, content="", provider_name="ollama",
                error="The 'openai' package is not installed. Run: pip install openai>=1.0",
            )
            return

        model = _model()
        if not model:
            yield ProviderResponse(
                success=False, content="", provider_name="ollama",
                error="OLLAMA_MODEL is not set; configure a local model (e.g. gemma4, qwen3.6).",
            )
            return

        base_url = _base_url()
        timeout = _completion_timeout()
        api_messages: list[dict[str, str]] = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        for msg in messages:
            api_messages.append({"role": msg.role, "content": msg.content})

        parts: list[str] = []
        usage = None
        try:
            client = openai.OpenAI(
                base_url=base_url,
                api_key=_api_key(),
                timeout=timeout,
                max_retries=0,
            )
            stream = client.chat.completions.create(
                model=model,
                messages=api_messages,  # type: ignore[arg-type]
                stream=True,
            )
            for chunk in stream:
                chunk_usage = extract_openai_usage(chunk)
                if chunk_usage:
                    usage = chunk_usage
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                text = getattr(delta, "content", None) if delta is not None else None
                if text:
                    parts.append(text)
                    yield text
        except openai.APITimeoutError:
            yield ProviderResponse(
                success=False, content="", provider_name="ollama", model=model,
                error=f"Timeout: Ollama did not respond within {timeout:g} seconds.",
            )
            return
        except openai.APIConnectionError as exc:
            yield ProviderResponse(
                success=False, content="", provider_name="ollama", model=model,
                error=f"Connection error: could not reach Ollama at {base_url}: {exc}",
            )
            return
        except Exception as exc:  # noqa: BLE001 — base contract: never raise
            yield ProviderResponse(
                success=False, content="", provider_name="ollama", model=model,
                error=str(exc),
            )
            return

        content = "".join(parts)
        if not content.strip():
            yield ProviderResponse(
                success=False, content="", provider_name="ollama", model=model,
                error="Ollama returned no output.",
            )
            return
        yield ProviderResponse(
            content=content, provider_name="ollama", model=model, success=True,
            metadata={"usage": usage} if usage else {},
        )
