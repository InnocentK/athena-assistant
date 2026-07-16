"""
providers/chatgpt.py — ChatGPT API adapter for Athena Assistant.

Calls the OpenAI Chat Completions API using the `openai` Python package.
The package is imported lazily inside complete() so that a missing install
does not prevent the module from loading.

Availability: OPENAI_API_KEY environment variable must be set and non-empty.
Cost tier: medium
Model: gpt-4o
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

DEFAULT_API_TIMEOUT: float = 120.0  # seconds — matches the Grok/CLI timeout convention


def _api_timeout() -> float:
    """Resolve the API completion timeout in seconds, falling back to the default."""
    raw = os.environ.get("OPENAI_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_API_TIMEOUT
    try:
        value = float(raw)
        return value if value > 0 else DEFAULT_API_TIMEOUT
    except ValueError:
        return DEFAULT_API_TIMEOUT


class ChatGPTAPIAdapter(ProviderAdapter):
    """Adapter that calls the OpenAI Chat Completions API."""

    def name(self) -> str:
        return "chatgpt"

    def cost_tier(self) -> str:
        return "medium"

    def is_available(self) -> bool:
        key = os.environ.get("OPENAI_API_KEY", "")
        return bool(key and key.strip())

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
                provider_name="chatgpt",
                error=(
                    "The 'openai' package is not installed. "
                    "Run: pip install openai>=1.0"
                ),
            )

        timeout = _api_timeout()

        # Build the messages payload
        api_messages: list[dict[str, str]] = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        for msg in messages:
            api_messages.append({"role": msg.role, "content": msg.content})

        try:
            # M26.8: bound the call (timeout + no retries) so a stalled API can't
            # hang for ~30 min (SDK default: 600s read × 3 tries). Mirrors
            # providers/grok.py's API path.
            client = openai.OpenAI(timeout=timeout, max_retries=0)
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=api_messages,  # type: ignore[arg-type]
            )

            content = response.choices[0].message.content or ""
            usage = extract_openai_usage(response)
            # M30: empty output is a failure on every adapter, in both modes —
            # the router falls back instead of returning a blank answer
            # (cross-adapter norm: hermes always, claude since M29.8).
            if not content.strip():
                return ProviderResponse(
                    success=False,
                    content="",
                    provider_name="chatgpt",
                    model="gpt-4o",
                    error="ChatGPT API returned no output.",
                    metadata={"usage": usage} if usage else {},
                )
            return ProviderResponse(
                content=content,
                provider_name="chatgpt",
                model="gpt-4o",
                success=True,
                metadata={"usage": usage} if usage else {},
            )

        except openai.APITimeoutError:
            return ProviderResponse(
                success=False,
                content="",
                provider_name="chatgpt",
                model="gpt-4o",
                error=f"Timeout: ChatGPT API did not respond within {timeout:g} seconds.",
            )
        except openai.APIConnectionError as exc:
            return ProviderResponse(
                success=False,
                content="",
                provider_name="chatgpt",
                model="gpt-4o",
                error=f"Connection error: could not reach the OpenAI API: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 — base contract: never raise
            return ProviderResponse(
                success=False,
                content="",
                provider_name="chatgpt",
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
        ProviderResponse (assembled content; usage from the SDK's
        include_usage final chunk when the backend provides it). Errors —
        including mid-stream — yield a failure ProviderResponse with the same
        error strings as complete(); bounding (timeout, max_retries=0) is
        identical.
        """
        try:
            import openai  # noqa: PLC0415
        except ImportError:
            yield ProviderResponse(
                success=False, content="", provider_name="chatgpt",
                error="The 'openai' package is not installed. Run: pip install openai>=1.0",
            )
            return

        timeout = _api_timeout()
        api_messages: list[dict[str, str]] = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        for msg in messages:
            api_messages.append({"role": msg.role, "content": msg.content})

        parts: list[str] = []
        usage = None
        try:
            client = openai.OpenAI(timeout=timeout, max_retries=0)
            # type-ignore[call-overload]: plain dicts for messages/stream_options
            # instead of the SDK's TypedDict params (same looseness the buffered
            # call carries as arg-type).
            stream = client.chat.completions.create(  # type: ignore[call-overload]
                model="gpt-4o",
                messages=api_messages,
                stream=True,
                # OpenAI proper surfaces usage on the final chunk with this.
                stream_options={"include_usage": True},
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
                success=False, content="", provider_name="chatgpt", model="gpt-4o",
                error=f"Timeout: ChatGPT API did not respond within {timeout:g} seconds.",
            )
            return
        except openai.APIConnectionError as exc:
            yield ProviderResponse(
                success=False, content="", provider_name="chatgpt", model="gpt-4o",
                error=f"Connection error: could not reach the OpenAI API: {exc}",
            )
            return
        except Exception as exc:  # noqa: BLE001 — base contract: never raise
            yield ProviderResponse(
                success=False, content="", provider_name="chatgpt", error=str(exc),
            )
            return

        content = "".join(parts)
        if not content.strip():
            yield ProviderResponse(
                success=False, content="", provider_name="chatgpt", model="gpt-4o",
                error="ChatGPT API returned no output.",
            )
            return
        yield ProviderResponse(
            content=content, provider_name="chatgpt", model="gpt-4o", success=True,
            metadata={"usage": usage} if usage else {},
        )
