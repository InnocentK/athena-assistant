"""
tests/test_provider_hermes.py — Hermes CLI adapter (Milestone 23).

Fully mocked: no real `hermes` binary, no subprocess, no network. The parser is
exercised against the real Hermes stdout samples (box-delimited answer).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from providers.base import Message, ProviderResponse
from providers.hermes import DEFAULT_BIN, HermesAdapter, _extract_answer

_REAL_ROOT = Path(__file__).parent.parent

# --- Real Hermes stdout samples (box-delimited answer) ---

SHORT_FRESH = """Query: What day is it?
Initializing agent...
────────────────────────────────────────
  ┊ 💻 $         date  0.2s
╭─ ⚕ Hermes ─────────────────────────────────────────────────────────────────────╮
    It's Wednesday, June 24, 2026.
╰────────────────────────────────────────────────────────────────────────────────╯
Resume this session with:
  hermes --resume 20260624_192511_a7f493
Session:        20260624_192511_a7f493
Duration:       19s
Messages:       4 (1 user, 2 tool calls)
"""

SHORT_LIVE = """● hermes chat -q "What day is it?"
Initializing agent...
────────────────────────────────────────
  ┊ 💻 $         date  0.2s
╭─ ⚕ Hermes ─────────────────────────────────────────────────────────────────────╮
    Wednesday, June 24, 2026.
╰────────────────────────────────────────────────────────────────────────────────╯
 ⚕ gpt-5.4-nano │ 15.4K/400K │ [░░░░░░░░░░] 4% │ 52s │ ⏲ 5s
──────────────────────────────────────────────────────────────────────────────────
❯
"""

MULTILINE = """Initializing agent...
╭─ ⚕ Hermes ───────────────────────────╮
    Key points:
    - Keep secrets in env.
    - Use an allowlist.
╰───────────────────────────────────────╯
Session: x
"""

NO_BOX = """Initializing agent...
no box here, format changed
Session: x
"""


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for var in ("HERMES_BIN", "HERMES_TIMEOUT"):
        monkeypatch.delenv(var, raising=False)


def _run(mocker, stdout="", returncode=0, stderr="", side_effect=None):
    if side_effect is not None:
        return mocker.patch("providers.hermes.subprocess.run", side_effect=side_effect)
    return mocker.patch(
        "providers.hermes.subprocess.run",
        return_value=mocker.MagicMock(returncode=returncode, stdout=stdout, stderr=stderr),
    )


# ---------------------------------------------------------------------------
# Identity / availability
# ---------------------------------------------------------------------------


def test_name_and_cost_tier():
    a = HermesAdapter()
    assert a.name() == "hermes"
    assert a.cost_tier() == "medium"


def test_is_available(mocker):
    mocker.patch("providers.hermes.shutil.which", return_value="/usr/bin/hermes")
    assert HermesAdapter().is_available() is True
    mocker.patch("providers.hermes.shutil.which", return_value=None)
    assert HermesAdapter().is_available() is False


# ---------------------------------------------------------------------------
# Parser — calibrated on the real samples
# ---------------------------------------------------------------------------


def test_extract_answer_short_fresh():
    answer, mode = _extract_answer(SHORT_FRESH)
    assert answer == "It's Wednesday, June 24, 2026."
    assert mode == "stripped"


def test_extract_answer_short_live():
    answer, mode = _extract_answer(SHORT_LIVE)
    assert answer == "Wednesday, June 24, 2026."
    assert mode == "stripped"


def test_extract_answer_multiline_dedented():
    answer, mode = _extract_answer(MULTILINE)
    assert mode == "stripped"
    assert answer == "Key points:\n- Keep secrets in env.\n- Use an allowlist."


def test_extract_answer_raw_fallback():
    answer, mode = _extract_answer(NO_BOX)
    assert mode == "raw"
    assert "no box here" in answer


# ---------------------------------------------------------------------------
# complete() — invocation + success
# ---------------------------------------------------------------------------


def test_complete_invocation_and_success(mocker):
    run = _run(mocker, stdout=SHORT_FRESH, returncode=0)
    resp = HermesAdapter().complete([Message(role="user", content="What day is it?")], None)

    assert resp.success is True
    assert resp.content == "It's Wednesday, June 24, 2026."
    assert resp.provider_name == "hermes"
    assert resp.metadata["transport"] == "cli"
    assert resp.metadata["source"] == "hermes"
    assert resp.metadata["parse_mode"] == "stripped"

    args, kwargs = run.call_args
    assert args[0][:3] == [DEFAULT_BIN, "chat", "-q"]   # hermes chat -q <prompt>
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["timeout"] == 120.0


def test_complete_raw_parse_mode(mocker):
    _run(mocker, stdout=NO_BOX, returncode=0)
    resp = HermesAdapter().complete([Message(role="user", content="x")], None)
    assert resp.success is True
    assert resp.metadata["parse_mode"] == "raw"


def test_bin_and_timeout_overrides(mocker, monkeypatch):
    monkeypatch.setenv("HERMES_BIN", "/opt/hermes")
    monkeypatch.setenv("HERMES_TIMEOUT", "30")
    run = _run(mocker, stdout=SHORT_FRESH)
    HermesAdapter().complete([Message(role="user", content="x")], None)
    args, kwargs = run.call_args
    assert args[0][0] == "/opt/hermes"
    assert kwargs["timeout"] == 30.0


# ---------------------------------------------------------------------------
# complete() — error handling (never raises)
# ---------------------------------------------------------------------------


def test_complete_timeout(mocker):
    _run(mocker, side_effect=subprocess.TimeoutExpired(cmd="hermes", timeout=120))
    resp = HermesAdapter().complete([Message(role="user", content="x")], None)
    assert resp.success is False
    assert "Timeout" in (resp.error or "")
    assert resp.metadata["transport"] == "cli"


def test_complete_nonzero_exit(mocker):
    _run(mocker, stdout="", returncode=2, stderr="hermes: error")
    resp = HermesAdapter().complete([Message(role="user", content="x")], None)
    assert resp.success is False
    assert "hermes: error" in (resp.error or "")


def test_complete_subprocess_exception(mocker):
    _run(mocker, side_effect=FileNotFoundError("no hermes"))
    resp = HermesAdapter().complete([Message(role="user", content="x")], None)
    assert resp.success is False
    assert "Subprocess error" in (resp.error or "")


def test_complete_empty_output_fails(mocker):
    _run(mocker, stdout="   \n  \n", returncode=0)
    resp = HermesAdapter().complete([Message(role="user", content="x")], None)
    assert resp.success is False
    assert "no parseable output" in (resp.error or "")


# ---------------------------------------------------------------------------
# Diagnostics integration (M22 contract) — Hermes shows as a cli record
# ---------------------------------------------------------------------------


def test_diagnostics_records_hermes_as_cli(tmp_path, monkeypatch):
    import core.config as cc
    from diagnostics.store import get_diagnostics_store

    monkeypatch.setattr(cc, "APP_ROOT", tmp_path)
    cc.get_settings.cache_clear()
    (tmp_path / "config").mkdir()
    shutil.copy(_REAL_ROOT / "config" / "providers.yaml", tmp_path / "config" / "providers.yaml")

    from providers.router import ProviderRouter

    get_diagnostics_store().reset()
    router = ProviderRouter()

    class _FakeHermes:
        def is_available(self):
            return True

        def complete(self, messages, system_prompt):
            return ProviderResponse(
                content="hi", provider_name="hermes", success=True,
                metadata={"transport": "cli", "source": "hermes", "parse_mode": "stripped"},
            )

    router._all_adapters = {"hermes": _FakeHermes()}
    router._adapter_configs = {"hermes": {"enabled": True, "type": "cli"}}
    router._ranking = {"balanced": ["hermes"]}

    resp = router.route([Message(role="user", content="x")], None, {"routing": {"mode": "balanced"}})
    rec = resp.metadata["diagnostics"]["records"][0]
    assert rec["provider"] == "hermes"
    assert rec["transport"] == "cli"
    assert rec["duration_ms"] >= 0
    get_diagnostics_store().reset()
