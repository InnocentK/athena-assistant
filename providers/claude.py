"""
providers/claude.py — Claude CLI adapter for Athena Assistant.

Calls the Claude CLI (Claude Code's `claude -p "<prompt>"`) as a subprocess.
The CLI must be installed and authenticated separately (see Anthropic's
Claude Code documentation).

Availability: `shutil.which("claude")` must return a non-None path.
Cost tier: high

M28.2 — token usage: when the installed CLI advertises `--output-format`
(feature-detected via `claude --help`, cached), completions run with
`--output-format json` and the result envelope is parsed **defensively**:
content from the `"result"` key, usage counts mapped onto
``metadata["usage"]`` like the API adapters. ANY shape deviation degrades to
plain-text behavior — never break the primary provider for a metric.

M29.5 — model attribution: the real envelope (validated against Claude Code
2.1.206) carries no top-level ``model``; the name is recovered from the
``modelUsage`` object's key, best-effort.

M29.8 (REVIEW-3.0 F4/F14): ``is_error`` is evaluated BEFORE any shape
fallback (an error envelope without a string ``result`` must never render as
a successful answer), and empty output is a provider FAILURE in both modes
(hermes parity — the router falls through to a provider that answers).
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
            if not raw:
                # M29.8 (F14): empty output is a failure — hermes parity; the
                # router falls through instead of surfacing a blank answer.
                return ProviderResponse(
                    success=False,
                    content="",
                    provider_name="claude",
                    error="Claude CLI returned no output.",
                )
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
        Defensive parse of the `--output-format json` envelope (M28.2, order
        hardened M29.8/F4, empty-output failure M29.8/F14).

        Expected: {"type":"result","result":"...","usage":{...},"is_error":false}.
        Order matters: `is_error` is checked BEFORE any shape fallback, so an
        error envelope without a string `result` is still a failure — never
        raw-JSON-as-success. Non-error shape deviations degrade: non-JSON or
        no `result` key → raw stdout IS the answer. Empty content → failure.
        """
        try:
            data = json.loads(raw)
        except Exception:  # noqa: BLE001 — CLI didn't honor JSON mode → plain path
            data = None

        if isinstance(data, dict):
            # F4: error verdict first — independent of the result field's shape.
            if data.get("is_error") is True:
                err = data.get("result") if isinstance(data.get("result"), str) else None
                err = (err or "").strip()
                if not err:
                    subtype = data.get("subtype")
                    err = subtype if isinstance(subtype, str) and subtype else ""
                return ProviderResponse(
                    success=False,
                    content="",
                    provider_name="claude",
                    error=err or "Claude CLI reported an error result.",
                )
            if isinstance(data.get("result"), str):
                content = data["result"].strip()
                if not content:
                    # F14: an empty answer is useless — fail so the router
                    # falls through (hermes parity).
                    return ProviderResponse(
                        success=False,
                        content="",
                        provider_name="claude",
                        error="Claude CLI returned no output.",
                    )
                usage = _map_claude_usage(data.get("usage"))
                model = data.get("model") if isinstance(data.get("model"), str) else None
                if model is None:
                    # M29.5: the real envelope (validated on 2.1.206) has no
                    # top-level "model" — the name is modelUsage's key.
                    model_usage = data.get("modelUsage")
                    if isinstance(model_usage, dict) and model_usage:
                        first = next(iter(model_usage))
                        model = first if isinstance(first, str) else None
                return ProviderResponse(
                    content=content,
                    provider_name="claude",
                    model=model,
                    success=True,
                    metadata={"usage": usage} if usage else {},
                )

        # Non-JSON / shapeless non-error output: the raw text is the answer —
        # unless it's empty (F14).
        if not raw:
            return ProviderResponse(
                success=False,
                content="",
                provider_name="claude",
                error="Claude CLI returned no output.",
            )
        return ProviderResponse(content=raw, provider_name="claude", success=True)
