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

from providers.base import Message, ProviderAdapter, ProviderResponse

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
            return ProviderResponse(
                content=content,
                provider_name="chatgpt",
                model="gpt-4o",
                success=True,
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
