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

from providers.base import Message, ProviderAdapter, ProviderResponse, neutral_cwd

# M30.7: Athena chat turns are pure-LLM — deny the CLI's agent tools (in -p
# mode it can otherwise read/search the filesystem and run tool loops).
# Explicit names required (a "*" wildcard denies nothing — probed live);
# unknown names only WARN (exit 0), so this list is safe across CLI versions.
_DISALLOWED_TOOLS = (
    "Task,Bash,Glob,Grep,Read,Edit,Write,NotebookEdit,WebFetch,WebSearch,TodoWrite"
)


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
        # M28.2/M30.7: feature-detection, cached per adapter lifetime.
        # _help_text: None = not probed yet; "" = probe failed; else the
        # `claude --help` output both _supports_* checks read.
        self._help_text: str | None = None

    def name(self) -> str:
        return "claude"

    def cost_tier(self) -> str:
        return "high"

    def is_available(self) -> bool:
        return shutil.which("claude") is not None

    def _cli_help(self) -> str:
        """
        `claude --help` output, probed ONCE and cached (M28.2 pattern,
        shared by every feature check since M30.7). ANY failure → "" (all
        checks read False → plain invocation, the safest path). Same
        subprocess hardening + neutral cwd as completions.
        """
        if self._help_text is None:
            try:
                probe = subprocess.run(
                    ["claude", "--help"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    stdin=subprocess.DEVNULL,
                    cwd=neutral_cwd(),  # M30.3: never inherit a project directory
                    timeout=10,
                )
                self._help_text = (probe.stdout or "") + (probe.stderr or "")
            except Exception:  # noqa: BLE001 — no probe, no feature flags
                self._help_text = ""
        return self._help_text

    def _supports_json_output(self) -> bool:
        """True iff the CLI advertises `--output-format` (M28.2)."""
        return "--output-format" in self._cli_help()

    def _supports_tool_restriction(self) -> bool:
        """True iff the CLI advertises `--disallowedTools` (M30.7)."""
        return "--disallowedTools" in self._cli_help()

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
        # M30.7: Athena chat turns are pure-LLM by policy — in `-p` mode the
        # CLI is otherwise a full agent with read-only tools (observed live:
        # it searched its neutral cwd and misdiagnosed the upload system,
        # burning most of a 40–68s turn). Feature-detected like JSON mode;
        # probed live: unknown tool names only WARN (exit 0), so a stale
        # denylist can never break answers. Tool-calling as a real feature
        # stays a Later item with its own safety framing.
        if self._supports_tool_restriction():
            args += ["--disallowedTools", _DISALLOWED_TOOLS]

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",          # M26.8: explicit codec, don't rely on locale
                errors="replace",          # a stray byte must not fail a good run
                stdin=subprocess.DEVNULL,  # never block on an interactive prompt
                cwd=neutral_cwd(),         # M30.3: no project-context bleed into chats
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
