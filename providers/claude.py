"""
providers/claude.py — Claude CLI adapter for Athena Assistant.

Calls the Claude CLI (`claude -p "<prompt>"`) as a subprocess.
The CLI must be installed and authenticated separately; see:
  https://github.com/anthropics/claude-cli  (or equivalent)

Availability: `shutil.which("claude")` must return a non-None path.
Cost tier: high

M28.2 — token usage: when the installed CLI advertises `--output-format`
(feature-detected via `claude --help`, cached), completions run with
`--output-format json` and the result envelope is parsed **defensively**:
content from the `"result"` key, usage counts mapped onto
``metadata["usage"]`` like the API adapters. ANY deviation (no flag support,
non-JSON stdout, missing keys) degrades to today's plain-text behavior —
never break the primary provider for a metric.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

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


def _map_claude_usage(raw: Any) -> dict[str, int] | None:
    """
    Map the Claude CLI envelope's usage object onto the M27.1 count schema
    (prompt/completion/total tokens). Ints only (bool rejected); None when
    nothing usable — "unavailable" downstream, never a fabricated number.
    """
    if not isinstance(raw, dict):
        return None
    out: dict[str, int] = {}
    for src, dst in (("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens")):
        val = raw.get(src)
        if isinstance(val, int) and not isinstance(val, bool):
            out[dst] = val
    if "prompt_tokens" in out and "completion_tokens" in out:
        out["total_tokens"] = out["prompt_tokens"] + out["completion_tokens"]
    return out or None


class ClaudeAdapter(ProviderAdapter):
    """Adapter that drives the Claude CLI via subprocess."""

    def __init__(self) -> None:
        # M28.2: feature-detection result, cached per adapter lifetime.
        # None = not probed yet; True/False = probed.
        self._json_supported: bool | None = None

    def name(self) -> str:
        return "claude"

    def cost_tier(self) -> str:
        return "high"

    def is_available(self) -> bool:
        return shutil.which("claude") is not None

    def _supports_json_output(self) -> bool:
        """
        True iff `claude --help` mentions `--output-format` (M28.2). Probed
        once and cached; ANY failure → False (plain invocation, today's path).
        The probe is local and fast — same subprocess hardening as completions.
        """
        if self._json_supported is None:
            try:
                probe = subprocess.run(
                    ["claude", "--help"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    stdin=subprocess.DEVNULL,
                    timeout=10,
                )
                self._json_supported = "--output-format" in (
                    (probe.stdout or "") + (probe.stderr or "")
                )
            except Exception:  # noqa: BLE001 — no probe, no JSON mode
                self._json_supported = False
        return self._json_supported

    def complete(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> ProviderResponse:
        prompt = _build_prompt(messages, system_prompt)
        json_mode = self._supports_json_output()
        args = ["claude", "-p", prompt]
        if json_mode:
            args += ["--output-format", "json"]

        try:
            result = subprocess.run(
                args,
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
                provider_name="claude",
                error="Timeout: Claude CLI did not respond within 120 seconds.",
            )
        except Exception as exc:  # noqa: BLE001
            return ProviderResponse(
                success=False,
                content="",
                provider_name="claude",
                error=f"Subprocess error: {exc}",
            )

        if result.returncode == 0:
            raw = result.stdout.strip()
            if json_mode:
                return self._parse_json_envelope(raw)
            return ProviderResponse(
                content=raw,
                provider_name="claude",
                success=True,
            )

        return ProviderResponse(
            success=False,
            content="",
            provider_name="claude",
            error=result.stderr.strip() or f"Non-zero exit code: {result.returncode}",
        )

    @staticmethod
    def _parse_json_envelope(raw: str) -> ProviderResponse:
        """
        Defensive parse of the `--output-format json` envelope (M28.2).

        Expected: {"type":"result","result":"...","usage":{...},"is_error":false}.
        Every deviation degrades: non-JSON or no "result" key → raw stdout IS
        the answer (success, no usage). "is_error": true → provider failure.
        """
        try:
            data = json.loads(raw)
        except Exception:  # noqa: BLE001 — CLI didn't honor JSON mode → plain answer
            return ProviderResponse(content=raw, provider_name="claude", success=True)
        if not isinstance(data, dict) or not isinstance(data.get("result"), str):
            return ProviderResponse(content=raw, provider_name="claude", success=True)

        content = data["result"]
        if data.get("is_error") is True:
            return ProviderResponse(
                success=False,
                content="",
                provider_name="claude",
                error=content.strip() or "Claude CLI reported an error result.",
            )
        usage = _map_claude_usage(data.get("usage"))
        model = data.get("model") if isinstance(data.get("model"), str) else None
        return ProviderResponse(
            content=content.strip(),
            provider_name="claude",
            model=model,
            success=True,
            metadata={"usage": usage} if usage else {},
        )
