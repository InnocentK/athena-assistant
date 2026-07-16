"""
tests/test_cli.py — Tests for the Athena one-shot CLI (Milestone 16).

Fully mocked: the ProviderRouter and MemoryManager are patched, so no real
provider, CLI binary, network call, or API key is ever needed. The CLI is
pointed at the conftest `tmp_project` tree via a patched APP_ROOT.
"""

from __future__ import annotations

import logging

import pytest

from providers.base import ProviderResponse


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeRouter:
    """Stands in for ProviderRouter; records what route() was called with."""

    def __init__(self, response: ProviderResponse | None = None, providers=None, record: dict | None = None):
        self._response = response or ProviderResponse(
            content="hi from fake", provider_name="fake", model="fake-1", success=True
        )
        self._providers = providers if providers is not None else [
            {"name": "ollama", "enabled": True, "available": True, "cost_tier": "low", "type": "api"},
        ]
        self.record = record if record is not None else {}
        self.route_calls = 0

    def route(self, messages, system_prompt, profile_config, on_attempt=None):
        self.route_calls += 1
        self.record["messages"] = messages
        self.record["system_prompt"] = system_prompt
        self.record["profile_config"] = profile_config
        # M27.0: exercise the live-status callback seam if the CLI supplies one.
        if on_attempt is not None:
            self.record["on_attempt_called"] = True
            on_attempt({"provider": "fake", "transport": "api", "mode": "balanced"})
        return self._response

    def route_stream(self, messages, system_prompt, profile_config, on_attempt=None):
        """M30 streaming analog: the real router degrades to one buffered chunk
        + done for non-streaming adapters — mirror that, reusing route() so the
        recorded calls/counters are identical whichever path the CLI takes."""
        self.record["streamed"] = True
        response = self.route(
            messages, system_prompt, profile_config, on_attempt=on_attempt
        )
        if response.success and response.content:
            yield ("chunk", response.content)
        yield ("done", response)

    def list_providers(self):
        return self._providers


def _install_router(monkeypatch, router):
    """Patch the ProviderRouter class so the CLI's deferred import picks it up."""
    import providers.router as pr

    monkeypatch.setattr(pr, "ProviderRouter", lambda: router)


def _install_memory(monkeypatch, memory_cls):
    import memory.manager as mm

    monkeypatch.setattr(mm, "MemoryManager", memory_cls)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cli_env(tmp_project, monkeypatch):
    """Point the CLI's config/profile resolution at the tmp project tree."""
    import core.config as cc

    monkeypatch.setattr(cc, "APP_ROOT", tmp_project)
    monkeypatch.setenv("ACTIVE_PROFILE", "athena")
    cc.get_settings.cache_clear()
    return tmp_project


@pytest.fixture(autouse=True)
def _restore_athena_logger():
    """
    The CLI redirects the shared 'athena' logger's console handler to stderr.
    Snapshot and restore it around each test so CLI runs don't leak handler
    state into other test files.
    """
    alog = logging.getLogger("athena")
    saved = [(h, getattr(h, "stream", None), h.level) for h in alog.handlers]
    saved_level = alog.level
    yield
    for handler, stream, level in saved:
        if stream is not None:
            try:
                handler.stream = stream
            except Exception:  # noqa: BLE001
                pass
            handler.setLevel(level)
    alog.setLevel(saved_level)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def test_build_parser_smoke():
    from cli.main import build_parser

    args = build_parser().parse_args(
        ["hello world", "--provider", "ollama", "--mode", "balanced"]
    )
    assert args.prompt == "hello world"
    assert args.provider == "ollama"
    assert args.mode == "balanced"
    assert args.list_providers is False


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_one_shot_prints_response_to_stdout(cli_env, monkeypatch, capsys):
    from cli.main import main

    router = _FakeRouter(
        ProviderResponse(content="The answer is 42.", provider_name="ollama", model="gemma4", success=True)
    )
    _install_router(monkeypatch, router)

    code = main(["--no-memory", "What is the answer?"])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out.strip() == "The answer is 42."
    assert router.route_calls == 1


def test_single_user_turn_built(cli_env, monkeypatch):
    from cli.main import main

    record: dict = {}
    _install_router(monkeypatch, _FakeRouter(record=record))

    main(["--no-memory", "ping"])

    messages = record["messages"]
    assert len(messages) == 1
    assert messages[0].role == "user"
    assert messages[0].content == "ping"
    assert record["system_prompt"]  # from the tmp profile's system_prompt


# ---------------------------------------------------------------------------
# --list-providers
# ---------------------------------------------------------------------------


def test_list_providers_prints_table_and_skips_routing(cli_env, monkeypatch, capsys):
    from cli.main import main

    router = _FakeRouter(providers=[
        {"name": "ollama", "enabled": True, "available": True, "cost_tier": "low", "type": "api"},
        {"name": "claude", "enabled": True, "available": False, "cost_tier": "high", "type": "cli"},
    ])
    _install_router(monkeypatch, router)

    code = main(["--list-providers"])
    captured = capsys.readouterr()

    assert code == 0
    assert "PROVIDER" in captured.out
    assert "ollama" in captured.out
    assert router.route_calls == 0


# ---------------------------------------------------------------------------
# Routing overrides
# ---------------------------------------------------------------------------


def test_provider_override_sets_preferred(cli_env, monkeypatch):
    from cli.main import main

    record: dict = {}
    _install_router(monkeypatch, _FakeRouter(record=record))

    code = main(["--provider", "ollama", "--no-memory", "hello"])

    assert code == 0
    assert record["profile_config"]["routing"]["preferred_provider"] == "ollama"


def test_mode_override_sets_mode(cli_env, monkeypatch):
    from cli.main import main

    record: dict = {}
    _install_router(monkeypatch, _FakeRouter(record=record))

    code = main(["--mode", "budget-first", "--no-memory", "hello"])

    assert code == 0
    assert record["profile_config"]["routing"]["mode"] == "budget-first"


def test_unknown_provider_is_usage_error(cli_env, monkeypatch, capsys):
    # M26.8: a --provider typo fails loudly (exit 2) instead of being ignored.
    from cli.main import main

    # _FakeRouter advertises only "ollama" via list_providers().
    _install_router(monkeypatch, _FakeRouter())

    code = main(["--provider", "claud", "--no-memory", "hello"])
    captured = capsys.readouterr()

    assert code == 2
    assert "unknown provider" in captured.err.lower()
    assert "ollama" in captured.err  # lists what IS available


def test_known_provider_still_routes(cli_env, monkeypatch):
    # A known provider name passes validation and reaches the router.
    from cli.main import main

    record: dict = {}
    _install_router(monkeypatch, _FakeRouter(record=record))

    code = main(["--provider", "ollama", "--no-memory", "hello"])

    assert code == 0
    assert record["profile_config"]["routing"]["preferred_provider"] == "ollama"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_missing_prompt_is_usage_error(cli_env, monkeypatch, capsys):
    from cli.main import main

    _install_router(monkeypatch, _FakeRouter())

    with pytest.raises(SystemExit) as exc:
        main([])

    assert exc.value.code == 2
    assert "prompt" in capsys.readouterr().err.lower()


def test_all_providers_failed_returns_1_clean_stdout(cli_env, monkeypatch, capsys):
    from cli.main import main

    router = _FakeRouter(
        ProviderResponse(content="All providers failed.", provider_name="none", success=False, error="no providers available")
    )
    _install_router(monkeypatch, router)

    code = main(["--no-memory", "hello"])
    captured = capsys.readouterr()

    assert code == 1
    assert captured.out.strip() == ""                     # nothing on stdout
    assert "no providers available" in captured.err       # error on stderr


def test_invalid_profile_returns_1(cli_env, monkeypatch, capsys):
    from cli.main import main

    _install_router(monkeypatch, _FakeRouter())

    code = main(["--profile", "does_not_exist", "--no-memory", "hello"])
    captured = capsys.readouterr()

    assert code == 1
    assert "profile" in captured.err.lower()


# ---------------------------------------------------------------------------
# Memory auto-extraction (best-effort, non-fatal)
# ---------------------------------------------------------------------------


def test_auto_extract_runs_by_default(cli_env, monkeypatch):
    from cli.main import main

    calls: dict = {"n": 0, "args": None}

    class _FakeMemory:
        def __init__(self, *a, **k):
            pass

        def auto_extract(self, user, assistant):
            calls["n"] += 1
            calls["args"] = (user, assistant)

    _install_memory(monkeypatch, _FakeMemory)
    _install_router(monkeypatch, _FakeRouter(
        ProviderResponse(content="resp", provider_name="ollama", success=True)
    ))

    code = main(["hello"])

    assert code == 0
    assert calls["n"] == 1
    assert calls["args"] == ("hello", "resp")


def test_no_memory_flag_skips_auto_extract(cli_env, monkeypatch):
    from cli.main import main

    calls = {"n": 0}

    class _FakeMemory:
        def __init__(self, *a, **k):
            pass

        def auto_extract(self, *a, **k):
            calls["n"] += 1

    _install_memory(monkeypatch, _FakeMemory)
    _install_router(monkeypatch, _FakeRouter())

    main(["--no-memory", "hello"])

    assert calls["n"] == 0


def test_auto_extract_failure_is_non_fatal(cli_env, monkeypatch, capsys):
    from cli.main import main

    class _BoomMemory:
        def __init__(self, *a, **k):
            pass

        def auto_extract(self, *a, **k):
            raise RuntimeError("boom")

    _install_memory(monkeypatch, _BoomMemory)
    _install_router(monkeypatch, _FakeRouter(
        ProviderResponse(content="still works", provider_name="ollama", success=True)
    ))

    code = main(["hello"])
    captured = capsys.readouterr()

    assert code == 0                                  # answer succeeded despite memory failure
    assert captured.out.strip() == "still works"


# ---------------------------------------------------------------------------
# `ask` subcommand alias (Milestone 17)
# ---------------------------------------------------------------------------


def test_normalize_argv_strips_leading_ask():
    from cli.main import _normalize_argv

    assert _normalize_argv(["ask", "hello"]) == ["hello"]
    assert _normalize_argv(["ask", "--provider", "o", "q"]) == ["--provider", "o", "q"]
    assert _normalize_argv(["ask"]) == []                       # lone ask -> empty -> usage error
    assert _normalize_argv(["hello"]) == ["hello"]              # bare prompt untouched
    assert _normalize_argv(["--provider", "o", "ask"]) == ["--provider", "o", "ask"]  # only first token


# ---------------------------------------------------------------------------
# Logging isolation (Milestone 26.6) — the CLI must not clobber foreign handlers
# ---------------------------------------------------------------------------


def test_configure_cli_logging_only_touches_tagged_handler():
    """
    _configure_cli_logging must retarget ONLY Athena's own tagged console
    handler (`_athena_console`), never a foreign handler that a third party has
    attached to the shared, non-propagating 'athena' logger. Regression guard
    for the M26.6 bug where the CLI clobbered pytest's StringIO-backed capture
    handler (setting its .stream to sys.stderr), which broke the whole suite.
    """
    import io
    import sys as _sys

    from cli.main import _configure_cli_logging

    alog = logging.getLogger("athena")

    tagged = logging.StreamHandler(io.StringIO())   # mimics core/logger's console handler
    tagged._athena_console = True                   # type: ignore[attr-defined]
    foreign = logging.StreamHandler(io.StringIO())  # mimics pytest's capture handler
    foreign_stream = foreign.stream

    alog.addHandler(tagged)
    alog.addHandler(foreign)
    try:
        _configure_cli_logging(verbose=False)

        # Foreign handler is untouched — its StringIO (and .getvalue) survive.
        assert foreign.stream is foreign_stream
        assert hasattr(foreign.stream, "getvalue")

        # Athena's own tagged handler was retargeted to stderr.
        assert tagged.stream is _sys.stderr
    finally:
        alog.removeHandler(tagged)
        alog.removeHandler(foreign)


def test_ask_alias_routes_prompt(cli_env, monkeypatch):
    from cli.main import main

    record: dict = {}
    _install_router(monkeypatch, _FakeRouter(record=record))

    code = main(["ask", "--no-memory", "hello"])

    assert code == 0
    assert record["messages"][0].content == "hello"


def test_ask_alias_with_flags(cli_env, monkeypatch):
    from cli.main import main

    record: dict = {}
    _install_router(monkeypatch, _FakeRouter(record=record))

    code = main(["ask", "--provider", "ollama", "--no-memory", "hi"])

    assert code == 0
    assert record["messages"][0].content == "hi"
    assert record["profile_config"]["routing"]["preferred_provider"] == "ollama"


def test_ask_alias_list_providers(cli_env, monkeypatch, capsys):
    from cli.main import main

    router = _FakeRouter()
    _install_router(monkeypatch, router)

    code = main(["ask", "--list-providers"])
    captured = capsys.readouterr()

    assert code == 0
    assert "PROVIDER" in captured.out
    assert router.route_calls == 0


def test_lone_ask_is_usage_error(cli_env, monkeypatch, capsys):
    from cli.main import main

    _install_router(monkeypatch, _FakeRouter())

    with pytest.raises(SystemExit) as exc:
        main(["ask"])

    assert exc.value.code == 2
    assert "prompt" in capsys.readouterr().err.lower()


# ---------------------------------------------------------------------------
# Status/progress feedback (Milestone 25) — stderr only, stdout stays the answer
# ---------------------------------------------------------------------------


def _resp_with_diag() -> ProviderResponse:
    diag = {
        "selected": "grok",
        "mode": "balanced",
        "total_ms": 800.0,
        "attempt_order": ["grok"],
        "records": [
            {"provider": "grok", "transport": "api", "outcome": "ok", "duration_ms": 800.0}
        ],
    }
    return ProviderResponse(
        content="42", provider_name="grok", model="grok-4.3", success=True,
        metadata={"diagnostics": diag},
    )


def test_status_default_keeps_stdout_clean_and_quiet(cli_env, monkeypatch, capsys):
    # capsys stderr is not a TTY → no spinner, and the summary is gated off.
    from cli.main import main

    _install_router(monkeypatch, _FakeRouter(_resp_with_diag()))
    code = main(["--no-memory", "q"])
    cap = capsys.readouterr()

    assert code == 0
    assert cap.out.strip() == "42"  # stdout is the answer only
    assert "answered via" not in cap.err.lower()  # no status noise by default off-TTY


def test_diagnostics_flag_emits_summary_and_breakdown_on_stderr(cli_env, monkeypatch, capsys):
    from cli.main import main

    _install_router(monkeypatch, _FakeRouter(_resp_with_diag()))
    code = main(["--no-memory", "--diagnostics", "q"])
    cap = capsys.readouterr()

    assert code == 0
    assert cap.out.strip() == "42"  # stdout still answer-only
    assert "Answered via grok/api in 0.8s." in cap.err
    assert "diagnostics:" in cap.err  # expanded breakdown header


def test_quiet_suppresses_all_status_even_with_diagnostics(cli_env, monkeypatch, capsys):
    from cli.main import main

    _install_router(monkeypatch, _FakeRouter(_resp_with_diag()))
    code = main(["--no-memory", "--quiet", "--diagnostics", "q"])
    cap = capsys.readouterr()

    assert code == 0
    assert cap.out.strip() == "42"
    assert cap.err.strip() == ""  # --quiet wins over --diagnostics


# ---------------------------------------------------------------------------
# M30 — streaming default, --no-stream escape hatch
# ---------------------------------------------------------------------------


class _ChunkedRouter(_FakeRouter):
    """route_stream yields real incremental chunks (not the delegate shim)."""

    def route_stream(self, messages, system_prompt, profile_config, on_attempt=None):
        self.record["streamed"] = True
        if on_attempt is not None:
            on_attempt({"provider": "fake", "transport": "api", "mode": "balanced"})
        yield ("chunk", "Hello ")
        yield ("chunk", "world")
        yield (
            "done",
            ProviderResponse(
                content="Hello world", provider_name="fake", model="m", success=True
            ),
        )


def test_streaming_is_the_default_and_prints_chunks_once(cli_env, monkeypatch, capsys):
    from cli.main import main

    record: dict = {}
    _install_router(monkeypatch, _ChunkedRouter(record=record))

    code = main(["--no-memory", "q"])
    cap = capsys.readouterr()

    assert code == 0
    assert record.get("streamed") is True
    # chunks land on stdout in order, once, with a trailing newline — and the
    # final content is NOT printed a second time.
    assert cap.out == "Hello world\n"


def test_no_stream_flag_uses_buffered_route(cli_env, monkeypatch, capsys):
    from cli.main import main

    record: dict = {}
    router = _FakeRouter(record=record)
    _install_router(monkeypatch, router)

    code = main(["--no-memory", "--no-stream", "q"])
    cap = capsys.readouterr()

    assert code == 0
    assert "streamed" not in record  # route_stream never touched
    assert router.route_calls == 1
    assert cap.out == "hi from fake\n"


def test_stream_failure_exits_1_with_stderr_error(cli_env, monkeypatch, capsys):
    from cli.main import main

    failure = ProviderResponse(
        success=False, content="", provider_name="fake", error="all dead"
    )
    _install_router(monkeypatch, _FakeRouter(failure))

    code = main(["--no-memory", "q"])
    cap = capsys.readouterr()

    assert code == 1
    assert cap.out == ""  # nothing was streamed; stdout stays clean
    assert "all dead" in cap.err
