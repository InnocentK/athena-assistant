"""
tests/test_cli_status.py — CLI status/progress feedback units (Milestone 25).

Pure, fixture-free tests for cli/status.py: the friendly summary and expanded
breakdown built from the M22 trace dict, and the Spinner's TTY-gating /
line-clearing behaviour. The main() integration (stdout stays answer-only;
--diagnostics / --quiet behaviour) lives in tests/test_cli.py alongside the
existing CLI fixtures.
"""

from __future__ import annotations

import io
import time

from cli.status import (
    Spinner,
    build_cli_breakdown,
    build_cli_summary,
    stream_is_tty,
)


class _FakeTTY:
    """A minimal text stream that can pretend to be (or not be) a TTY.

    (io.StringIO is a C type with no __dict__, so we wrap one rather than
    subclass it.)
    """

    def __init__(self, tty: bool = True, encoding: str = "utf-8") -> None:
        self._buf = io.StringIO()
        self._tty = tty
        self.encoding = encoding

    def write(self, s: str) -> int:
        return self._buf.write(s)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return self._tty

    def getvalue(self) -> str:
        return self._buf.getvalue()


# ---------------------------------------------------------------------------
# build_cli_summary — mirrors the web UI wording
# ---------------------------------------------------------------------------


def test_summary_single_provider():
    diag = {
        "selected": "grok",
        "total_ms": 800.0,
        "records": [{"provider": "grok", "transport": "api", "outcome": "ok", "duration_ms": 800.0}],
    }
    assert build_cli_summary(diag) == "Answered via grok/api in 0.8s."


def test_summary_with_prior_failure():
    diag = {
        "selected": "grok",
        "total_ms": 820.0,
        "records": [
            {"provider": "claude", "transport": "cli", "outcome": "unavailable", "duration_ms": 40.0},
            {"provider": "grok", "transport": "api", "outcome": "ok", "duration_ms": 780.0},
        ],
    }
    assert build_cli_summary(diag) == "claude/cli unavailable; answered via grok/api in 0.8s."


def test_summary_no_provider():
    diag = {
        "selected": None,
        "total_ms": 0.0,
        "records": [{"provider": "claude", "transport": "cli", "outcome": "unavailable", "duration_ms": 40.0}],
    }
    assert build_cli_summary(diag) == "No provider answered."


def test_summary_empty_when_no_trace():
    assert build_cli_summary(None) == ""
    assert build_cli_summary({}) == ""


# ---------------------------------------------------------------------------
# build_cli_breakdown — expanded, --diagnostics only
# ---------------------------------------------------------------------------


def test_breakdown_multiline_and_marks_selected():
    diag = {
        "selected": "grok",
        "mode": "balanced",
        "total_ms": 820.0,
        "records": [
            {"provider": "claude", "transport": "cli", "outcome": "unavailable", "error_kind": "unavailable", "duration_ms": 40.0},
            {"provider": "grok", "transport": "api", "outcome": "ok", "duration_ms": 780.0},
        ],
    }
    lines = build_cli_breakdown(diag).splitlines()
    assert lines[0].startswith("diagnostics:")
    assert "mode=balanced" in lines[0] and "selected=grok" in lines[0]
    assert any("claude/cli unavailable" in ln and "(unavailable)" in ln for ln in lines)
    assert any(ln.strip().startswith("* grok/api ok") for ln in lines)  # selected marked


def test_breakdown_empty_when_no_trace():
    assert build_cli_breakdown(None) == ""
    assert build_cli_breakdown({"records": []}) == ""


# ---------------------------------------------------------------------------
# Spinner — TTY-gated, clears on stop, never raises
# ---------------------------------------------------------------------------


def test_spinner_inactive_and_silent_when_not_tty():
    stream = _FakeTTY(tty=False)
    sp = Spinner("Working…", enabled=True, stream=stream)
    assert sp.active is False
    sp.start()
    sp.stop()
    assert stream.getvalue() == ""  # nothing written on a non-TTY


def test_spinner_inactive_when_disabled_even_on_tty():
    stream = _FakeTTY(tty=True)
    sp = Spinner("Working…", enabled=False, stream=stream)
    assert sp.active is False
    sp.start()
    sp.stop()
    assert stream.getvalue() == ""


def test_spinner_animates_on_tty_and_clears_on_stop():
    stream = _FakeTTY(tty=True)
    sp = Spinner("Working…", enabled=True, stream=stream, interval=0.01)
    assert sp.active is True
    sp.start()
    time.sleep(0.03)
    sp.stop()
    out = stream.getvalue()
    assert "Working" in out  # animated at least once
    assert out.endswith("\r\033[K")  # line cleared on stop


def test_stream_is_tty_helper():
    assert stream_is_tty(_FakeTTY(tty=True)) is True
    assert stream_is_tty(_FakeTTY(tty=False)) is False
    assert stream_is_tty(object()) is False  # no isatty() → conservative False
