"""
providers/base.py — Abstract base classes and shared data types for all provider adapters.

Every concrete adapter must subclass ProviderAdapter and implement all four
abstract methods. The Message and ProviderResponse dataclasses are the sole
data-exchange contract between the router and the adapters.
"""

from __future__ import annotations

import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class Message:
    """A single turn in a conversation."""

    role: str    # "system" | "user" | "assistant"
    content: str


@dataclass
class ProviderResponse:
    """The result of a provider completion call."""

    content: str
    provider_name: str
    model: str | None = None
    error: str | None = None
    success: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


def neutral_cwd() -> str:
    """
    The working directory for CLI provider subprocesses (M30.3): the system
    temp dir — guaranteed to be outside any repository.

    Vendor CLIs (claude, gemini, …) discover project agent config by walking
    UP from their cwd; inheriting Athena's caller cwd meant `athena` run from
    inside any project leaked that project's instructions and hooks into the
    chat (observed live: a repo's SessionStart hook ran the full test suite
    per message and the answer arrived in the repo-agent persona). Every CLI
    adapter's ``subprocess.run`` must pass ``cwd=neutral_cwd()``. User-GLOBAL
    vendor config (e.g. ``~/.claude/``) still applies by design — that is the
    operator's own CLI login/identity, not project context.
    """
    return tempfile.gettempdir()


def extract_openai_usage(response: Any) -> dict[str, Any] | None:
    """
    Pull token counts from an OpenAI-SDK-style completion response (M27.1).

    Returns a **content-free** dict of the counts that are present
    (``prompt_tokens`` / ``completion_tokens`` / ``total_tokens``), or ``None``
    when the response carries no usable ``usage`` object. Token *counts* are
    metadata (permitted in diagnostics); token *text* is never touched. Defensive
    by contract — a provider that omits or mangles ``usage`` yields ``None``
    ("unavailable" downstream), never an exception.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    out: dict[str, Any] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        val = getattr(usage, key, None)
        if isinstance(val, bool):  # bool is an int subclass — reject it explicitly
            continue
        if isinstance(val, (int, float)):
            out[key] = int(val)
    return out or None


class ProviderAdapter(ABC):
    """
    Abstract base for all AI provider adapters.

    Each adapter is responsible for:
      - reporting its availability (is_available)
      - executing a chat completion (complete)
      - declaring its name and cost tier

    The router only calls complete() on adapters where is_available() is True.

    Streaming (M30): adapters that can deliver incremental output override
    ``supports_streaming()`` to return True and implement
    ``complete_stream()`` — a generator yielding text chunks (str) and
    finishing with the final ``ProviderResponse`` (assembled full content;
    usage best-effort). CLI subprocess adapters answer whole and keep the
    default (False): the router degrades them to a single buffered chunk.
    """

    def supports_streaming(self) -> bool:
        """True iff this adapter implements ``complete_stream()`` (M30)."""
        return False

    def complete_stream(
        self,
        messages: "list[Message]",
        system_prompt: str | None = None,
    ) -> "Iterator[str | ProviderResponse]":
        """
        Stream a completion: yield text chunks, then the final
        ``ProviderResponse`` (M30). Default: not supported — the router must
        check ``supports_streaming()`` first and never reach this.
        """
        raise NotImplementedError(f"{self.name()} does not support streaming")

    @abstractmethod
    def name(self) -> str:
        """Return the canonical lowercase name for this provider (e.g. 'claude')."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """
        Return True if this provider can be used right now.

        For CLI adapters: check that the CLI binary is on PATH.
        For API adapters: check that the required env var / credential is set.
        For stub adapters: always return False.
        """
        ...

    @abstractmethod
    def cost_tier(self) -> str:
        """Return the cost tier for this provider: 'low' | 'medium' | 'high'."""
        ...

    @abstractmethod
    def complete(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> ProviderResponse:
        """
        Execute a chat completion and return a ProviderResponse.

        Must never raise — catch all exceptions internally and return a
        ProviderResponse with success=False and a descriptive error field.
        """
        ...
