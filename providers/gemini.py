"""
providers/gemini.py — Gemini CLI adapter for Athena Assistant.

Calls the Gemini CLI (`gemini -p "<prompt>"`) as a subprocess.
The CLI must be installed and authenticated separately.

Availability: `shutil.which("gemini")` must return a non-None path.
Cost tier: medium
"""

from __future__ import annotations

import shutil
import subprocess

from providers.base import Message, ProviderAdapter, ProviderResponse


def _build_prompt(messages: list[Message], system_prompt: str | None) -> str:
    """
    Flatten the message list into a single prompt string for CLI invocation.

    Format:
        [System: <system_prompt>]

        User: ...
        Assistant: ...
        User: ...
        Assistant:
    """
    parts: list[str] = []

    if system_prompt:
        parts.append(f"System: {system_prompt.strip()}\n")

    for msg in messages:
        role = msg.role.capitalize()
        parts.append(f"{role}: {msg.content}")

    # End with "Assistant:" to signal the model should continue from here
    parts.append("Assistant:")

    return "\n".join(parts)


class GeminiAdapter(ProviderAdapter):
    """Adapter that drives the Gemini CLI via subprocess."""

    def name(self) -> str:
        return "gemini"

    def cost_tier(self) -> str:
        return "medium"

    def is_available(self) -> bool:
        return shutil.which("gemini") is not None

    def complete(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> ProviderResponse:
        prompt = _build_prompt(messages, system_prompt)

        try:
            result = subprocess.run(
                ["gemini", "-p", prompt],
                capture_output=True,
                text=True,
                encoding="utf-8",          # M26.8: explicit codec, don't rely on locale
                errors="replace",          # a stray byte must not fail a good run
                stdin=subprocess.DEVNULL,  # never block on an interactive prompt
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return ProviderResponse(
                success=False,
                content="",
                provider_name="gemini",
                error="Timeout: Gemini CLI did not respond within 120 seconds.",
            )
        except Exception as exc:  # noqa: BLE001
            return ProviderResponse(
                success=False,
                content="",
                provider_name="gemini",
                error=f"Subprocess error: {exc}",
            )

        if result.returncode == 0:
            return ProviderResponse(
                content=result.stdout.strip(),
                provider_name="gemini",
                success=True,
            )

        return ProviderResponse(
            success=False,
            content="",
            provider_name="gemini",
            error=result.stderr.strip() or f"Non-zero exit code: {result.returncode}",
        )
