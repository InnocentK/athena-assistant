"""
providers/hermes.py — Hermes CLI adapter for Athena Assistant (Milestone 23).

Hermes is a CLI/TUI-oriented assistant (not an HTTP API). Athena drives it
one-shot as a subprocess:

    hermes chat -q "<prompt>"

Hermes wraps the answer in session/status/progress text and renders the final
answer inside a box:

    ╭─ ⚕ Hermes ───────────────────────────╮
        <answer text>
    ╰───────────────────────────────────────╯

`_extract_answer()` pulls the text out of that box (the reliable anchor in both
fresh-terminal and live-session output). If the box can't be found (e.g. a
format change), it conservatively returns the full ANSI-cleaned stdout and sets
``metadata["parse_mode"] = "raw"`` so the degraded mode is visible.

One logical provider ("hermes"), **CLI transport only**, **opt-in** (the
adapter ships `enabled: false` and is in no ranking by default). Athena treats
it as a distinct Hermes path even though Hermes may internally use linked
providers/models.

Config / env:
  HERMES_BIN      binary name or path (default "hermes")
  HERMES_TIMEOUT  one-shot timeout in seconds (default 120)

Availability: HERMES_BIN on PATH. Cost tier: medium (Hermes may use paid models).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

from providers.base import Message, ProviderAdapter, ProviderResponse

DEFAULT_BIN: str = "hermes"
DEFAULT_TIMEOUT: float = 120.0

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _build_prompt(messages: list[Message], system_prompt: str | None) -> str:
    """Flatten the conversation into a single one-shot query string."""
    parts: list[str] = []
    if system_prompt:
        parts.append(f"System: {system_prompt.strip()}\n")
    for msg in messages:
        parts.append(f"{msg.role.capitalize()}: {msg.content}")
    parts.append("Assistant:")
    return "\n".join(parts)


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _dedent_block(lines: list[str]) -> str:
    """Remove the common leading indent from a block (preserves relative shape)."""
    nonempty = [ln for ln in lines if ln.strip()]
    if not nonempty:
        return ""
    indent = min(len(ln) - len(ln.lstrip(" ")) for ln in nonempty)
    return "\n".join(ln[indent:] if len(ln) >= indent else ln for ln in lines).strip("\n")


def _extract_answer(stdout: str) -> tuple[str, str]:
    """
    Extract the answer from Hermes stdout.

    Returns ``(answer, parse_mode)``:
      - primary: the dedented text inside the Hermes answer box — a line that
        contains ``╭`` and ``Hermes`` down to the next line starting with ``╰``
        → ``parse_mode = "stripped"``;
      - fallback: the full ANSI-cleaned stdout → ``parse_mode = "raw"`` when no
        box can be located (never empty, never mangled).
    """
    cleaned = _strip_ansi(stdout).replace("\r", "")
    lines = [ln.rstrip() for ln in cleaned.split("\n")]

    # Use the LAST Hermes box (the final answer), in case earlier boxes appear.
    top_idx: int | None = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if "╭" in s and "Hermes" in s:
            top_idx = i
    if top_idx is not None:
        for j in range(top_idx + 1, len(lines)):
            if lines[j].lstrip().startswith("╰"):
                answer = _dedent_block(lines[top_idx + 1 : j]).strip()
                if answer:
                    return answer, "stripped"
                break

    # Conservative fallback — return everything cleaned, flagged as raw.
    return cleaned.strip(), "raw"


class HermesAdapter(ProviderAdapter):
    """CLI-backed Hermes provider (one-shot ``hermes chat -q``)."""

    def name(self) -> str:
        return "hermes"

    def cost_tier(self) -> str:
        return "medium"

    @staticmethod
    def _bin() -> str:
        return os.environ.get("HERMES_BIN", "").strip() or DEFAULT_BIN

    @staticmethod
    def _timeout() -> float:
        raw = os.environ.get("HERMES_TIMEOUT", "").strip()
        if not raw:
            return DEFAULT_TIMEOUT
        try:
            value = float(raw)
            return value if value > 0 else DEFAULT_TIMEOUT
        except ValueError:
            return DEFAULT_TIMEOUT

    def is_available(self) -> bool:
        return shutil.which(self._bin()) is not None

    def complete(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> ProviderResponse:
        prompt = _build_prompt(messages, system_prompt)
        timeout = self._timeout()
        meta: dict[str, str] = {"transport": "cli", "source": "hermes"}

        try:
            result = subprocess.run(
                [self._bin(), "chat", "-q", prompt],
                capture_output=True,
                text=True,
                encoding="utf-8",          # M26.8: explicit codec for the box's non-ASCII output
                errors="replace",          # a stray byte must not fail a good run
                stdin=subprocess.DEVNULL,  # never block waiting on an interactive prompt
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ProviderResponse(
                success=False, content="", provider_name="hermes",
                error=f"Timeout: Hermes CLI did not respond within {timeout:g} seconds.",
                metadata=meta,
            )
        except Exception as exc:  # noqa: BLE001
            return ProviderResponse(
                success=False, content="", provider_name="hermes",
                error=f"Subprocess error: {exc}", metadata=meta,
            )

        if result.returncode != 0:
            return ProviderResponse(
                success=False, content="", provider_name="hermes",
                error=result.stderr.strip() or f"Non-zero exit code: {result.returncode}",
                metadata=meta,
            )

        answer, parse_mode = _extract_answer(result.stdout or "")
        meta["parse_mode"] = parse_mode
        if not answer:
            return ProviderResponse(
                success=False, content="", provider_name="hermes",
                error="Hermes returned no parseable output.",
                metadata=meta,
            )
        return ProviderResponse(
            content=answer, provider_name="hermes", success=True, metadata=meta,
        )
