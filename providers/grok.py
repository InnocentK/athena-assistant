"""
providers/grok.py — Grok adapter (CLI + API transports) for Athena Assistant.

Grok is ONE logical provider ("grok") that can run over either of two
transports, selected **explicitly** (no auto/fallback mode in this milestone):

  cli  (default)  — drives the `grok` CLI via subprocess (the original path).
  api             — calls Grok's OpenAI-compatible API via the `openai` SDK
                    (base_url https://api.x.ai/v1, key XAI_API_KEY).

Transport resolution (highest priority first):
  1. GROK_TRANSPORT env var                         ("cli" | "api")
  2. providers.adapters.grok.transport (providers.yaml)
  3. default "cli"   ← the API never silently replaces the CLI

API connection parameters (environment, with documented defaults):
  XAI_API_KEY    API key (required for the api transport)
  GROK_MODEL     model name        (default "grok-4.3")
  GROK_API_URL   base URL          (default "https://api.x.ai/v1")
  GROK_TIMEOUT   completion timeout in seconds (default 120)

Availability: cli → `grok` on PATH; api → XAI_API_KEY set (+ openai installed).
Cost tier: low (both transports).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Iterator

from core.config import APP_ROOT
from core.loader import load_yaml
from providers.base import (
    Message,
    ProviderAdapter,
    ProviderResponse,
    extract_openai_usage,
    neutral_cwd,
)

# ---------------------------------------------------------------------------
# Defaults / constants
# ---------------------------------------------------------------------------
DEFAULT_API_URL: str = "https://api.x.ai/v1"
DEFAULT_MODEL: str = "grok-4.3"
DEFAULT_API_TIMEOUT: float = 120.0  # seconds — matches the CLI timeout convention
CLI_TIMEOUT: int = 120              # seconds


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


def _transport_from_config() -> str:
    """
    Read `providers.adapters.grok.transport` from config/providers.yaml.

    Reuses the existing `core.loader.load_yaml` helper and the `APP_ROOT`
    path helper (the same access path ProviderRouter uses for adapter config).
    Returns "" if absent/unreadable. Read-only — never writes the file.
    """
    try:
        cfg = load_yaml(APP_ROOT / "config" / "providers.yaml")
        grok_cfg = cfg.get("providers", {}).get("adapters", {}).get("grok", {})
        value = grok_cfg.get("transport")
        return str(value).strip().lower() if value else ""
    except Exception:  # noqa: BLE001 — config issues must never break availability/routing
        return ""


def _api_timeout() -> float:
    """Resolve the API completion timeout in seconds, falling back to the default."""
    raw = os.environ.get("GROK_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_API_TIMEOUT
    try:
        value = float(raw)
        return value if value > 0 else DEFAULT_API_TIMEOUT
    except ValueError:
        return DEFAULT_API_TIMEOUT


class GrokAdapter(ProviderAdapter):
    """One logical Grok provider with an explicit CLI-or-API transport."""

    def name(self) -> str:
        return "grok"

    def cost_tier(self) -> str:
        return "low"

    def transport(self) -> str:
        """
        The effective transport this adapter will use right now ("cli"|"api").

        Exposed (M26.2) so provider listings — the Settings → Providers tab and
        `--list-providers` — report the *real* configured transport instead of
        the static ``providers.yaml`` ``type``. Read-only; same resolution as
        ``complete()``/``is_available()``.
        """
        return self._transport()

    # ------------------------------------------------------------------
    # Transport selection
    # ------------------------------------------------------------------

    def _transport(self) -> str:
        """
        Resolve the active transport: GROK_TRANSPORT env → providers.yaml →
        default "cli". Unrecognised values are ignored (fall through), so the
        default of "cli" is preserved — the API is strictly opt-in.
        """
        env = os.environ.get("GROK_TRANSPORT", "").strip().lower()
        if env in ("cli", "api"):
            return env
        cfg = _transport_from_config()
        if cfg in ("cli", "api"):
            return cfg
        return "cli"

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        if self._transport() == "api":
            return self._api_available()
        return shutil.which("grok") is not None

    @staticmethod
    def _api_available() -> bool:
        key = os.environ.get("XAI_API_KEY", "")
        if not (key and key.strip()):
            return False
        try:
            import openai  # noqa: F401, PLC0415 — presence check only
        except ImportError:
            return False
        return True

    # ------------------------------------------------------------------
    # Completion — dispatch by transport
    # ------------------------------------------------------------------

    def complete(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> ProviderResponse:
        if self._transport() == "api":
            return self._complete_api(messages, system_prompt)
        return self._complete_cli(messages, system_prompt)

    # ---- CLI transport (original behaviour, unchanged) ----

    def _complete_cli(
        self, messages: list[Message], system_prompt: str | None
    ) -> ProviderResponse:
        prompt = _build_prompt(messages, system_prompt)
        meta = {"transport": "cli"}

        try:
            result = subprocess.run(
                ["grok", "-p", prompt],
                capture_output=True,
                text=True,
                encoding="utf-8",          # M26.8: explicit codec, don't rely on locale
                errors="replace",          # a stray byte must not fail a good run
                stdin=subprocess.DEVNULL,  # never block on an interactive prompt
                cwd=neutral_cwd(),         # M30.3: no project-context bleed into chats
                timeout=CLI_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return ProviderResponse(
                success=False, content="", provider_name="grok",
                error="Timeout: Grok CLI did not respond within 120 seconds.",
                metadata=meta,
            )
        except Exception as exc:  # noqa: BLE001
            return ProviderResponse(
                success=False, content="", provider_name="grok",
                error=f"Subprocess error: {exc}", metadata=meta,
            )

        if result.returncode == 0:
            content = result.stdout.strip()
            # M30: empty output is a failure on every adapter (router falls back).
            if not content:
                return ProviderResponse(
                    success=False, content="", provider_name="grok",
                    error="Grok CLI returned no output.", metadata=meta,
                )
            return ProviderResponse(
                content=content, provider_name="grok",
                success=True, metadata=meta,
            )

        return ProviderResponse(
            success=False, content="", provider_name="grok",
            error=result.stderr.strip() or f"Non-zero exit code: {result.returncode}",
            metadata=meta,
        )

    # ---- API transport (OpenAI-compatible; mirrors providers/ollama.py) ----

    def _complete_api(
        self, messages: list[Message], system_prompt: str | None
    ) -> ProviderResponse:
        meta: dict[str, Any] = {"transport": "api"}

        try:
            import openai  # noqa: PLC0415
        except ImportError:
            return ProviderResponse(
                success=False, content="", provider_name="grok",
                error="The 'openai' package is not installed. Run: pip install openai>=1.0",
                metadata=meta,
            )

        key = os.environ.get("XAI_API_KEY", "").strip()
        if not key:
            return ProviderResponse(
                success=False, content="", provider_name="grok",
                error="XAI_API_KEY is not set; required for the Grok API transport.",
                metadata=meta,
            )

        base_url = os.environ.get("GROK_API_URL", "").strip() or DEFAULT_API_URL
        model = os.environ.get("GROK_MODEL", "").strip() or DEFAULT_MODEL
        timeout = _api_timeout()

        api_messages: list[dict[str, str]] = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        for msg in messages:
            api_messages.append({"role": msg.role, "content": msg.content})

        try:
            client = openai.OpenAI(
                base_url=base_url, api_key=key, timeout=timeout, max_retries=0
            )
            response = client.chat.completions.create(
                model=model, messages=api_messages,  # type: ignore[arg-type]
            )
            content = response.choices[0].message.content or ""
            usage = extract_openai_usage(response)
            if usage:
                meta["usage"] = usage
            # M30: empty output is a failure on every adapter (router falls back).
            if not content.strip():
                return ProviderResponse(
                    success=False, content="", provider_name="grok", model=model,
                    error="Grok API returned no output.", metadata=meta,
                )
            return ProviderResponse(
                content=content, provider_name="grok", model=model,
                success=True, metadata=meta,
            )
        except openai.APITimeoutError:
            return ProviderResponse(
                success=False, content="", provider_name="grok", model=model,
                error=f"Timeout: Grok API did not respond within {timeout:g} seconds.",
                metadata=meta,
            )
        except openai.APIConnectionError as exc:
            return ProviderResponse(
                success=False, content="", provider_name="grok", model=model,
                error=f"Connection error: could not reach Grok API at {base_url}: {exc}",
                metadata=meta,
            )
        except Exception as exc:  # noqa: BLE001 — base contract: never raise
            return ProviderResponse(
                success=False, content="", provider_name="grok", model=model,
                error=str(exc), metadata=meta,
            )

    # ------------------------------------------------------------------
    # Streaming (M30) — API transport only; the CLI answers whole
    # ------------------------------------------------------------------

    def supports_streaming(self) -> bool:
        """True only on the API transport — a subprocess answer arrives whole."""
        return self._transport() == "api"

    def complete_stream(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> "Iterator[str | ProviderResponse]":
        # Dispatcher (not a generator): raises at CALL time on the cli
        # transport, mirroring the base-class contract — the router checks
        # supports_streaming() first and never reaches this on cli.
        if self._transport() != "api":
            raise NotImplementedError("grok (cli transport) does not support streaming")
        return self._complete_stream_api(messages, system_prompt)

    def _complete_stream_api(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> "Iterator[str | ProviderResponse]":
        """
        Stream a completion over the API transport (M30): yield text chunks,
        then the final ProviderResponse (assembled content). No
        ``stream_options={"include_usage": True}`` is sent — x.ai compatibility
        is not guaranteed and a rejected parameter would break streaming; if
        the server volunteers usage on a chunk it is recorded, otherwise usage
        is honestly absent. Error strings and client bounding match
        _complete_api().
        """
        meta: dict[str, Any] = {"transport": "api"}

        try:
            import openai  # noqa: PLC0415
        except ImportError:
            yield ProviderResponse(
                success=False, content="", provider_name="grok",
                error="The 'openai' package is not installed. Run: pip install openai>=1.0",
                metadata=meta,
            )
            return

        key = os.environ.get("XAI_API_KEY", "").strip()
        if not key:
            yield ProviderResponse(
                success=False, content="", provider_name="grok",
                error="XAI_API_KEY is not set; required for the Grok API transport.",
                metadata=meta,
            )
            return

        base_url = os.environ.get("GROK_API_URL", "").strip() or DEFAULT_API_URL
        model = os.environ.get("GROK_MODEL", "").strip() or DEFAULT_MODEL
        timeout = _api_timeout()

        api_messages: list[dict[str, str]] = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        for msg in messages:
            api_messages.append({"role": msg.role, "content": msg.content})

        parts: list[str] = []
        usage = None
        try:
            client = openai.OpenAI(
                base_url=base_url, api_key=key, timeout=timeout, max_retries=0
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
                success=False, content="", provider_name="grok", model=model,
                error=f"Timeout: Grok API did not respond within {timeout:g} seconds.",
                metadata=meta,
            )
            return
        except openai.APIConnectionError as exc:
            yield ProviderResponse(
                success=False, content="", provider_name="grok", model=model,
                error=f"Connection error: could not reach Grok API at {base_url}: {exc}",
                metadata=meta,
            )
            return
        except Exception as exc:  # noqa: BLE001 — base contract: never raise
            yield ProviderResponse(
                success=False, content="", provider_name="grok", model=model,
                error=str(exc), metadata=meta,
            )
            return

        if usage:
            meta["usage"] = usage
        content = "".join(parts)
        if not content.strip():
            yield ProviderResponse(
                success=False, content="", provider_name="grok", model=model,
                error="Grok API returned no output.", metadata=meta,
            )
            return
        yield ProviderResponse(
            content=content, provider_name="grok", model=model, success=True,
            metadata=meta,
        )
