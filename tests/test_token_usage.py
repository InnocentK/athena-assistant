"""Token/context usage capture + surfacing (M27.1).

Covers the additive, content-free ``usage`` path end to end at the unit level:
the OpenAI-usage extractor, the router copying usage onto the diagnostics
record, and the CLI usage-line builder (available + "unavailable"). The web-UI
`buildUsageText` is covered in `tests/js/*`. All mocked — no real providers.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cli.status import build_cli_usage
from providers.base import ProviderResponse, extract_openai_usage

_REAL_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# extract_openai_usage — defensive, counts-only
# ---------------------------------------------------------------------------


def test_extract_usage_reads_counts():
    resp = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=34, total_tokens=46)
    )
    assert extract_openai_usage(resp) == {
        "prompt_tokens": 12,
        "completion_tokens": 34,
        "total_tokens": 46,
    }


def test_extract_usage_none_when_absent():
    assert extract_openai_usage(SimpleNamespace()) is None
    assert extract_openai_usage(SimpleNamespace(usage=None)) is None


def test_extract_usage_partial_and_ignores_non_numeric():
    resp = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=None, total_tokens="x")
    )
    assert extract_openai_usage(resp) == {"prompt_tokens": 5}


def test_extract_usage_rejects_bool():
    # bool is an int subclass; a stray True must not be reported as "1 token"
    resp = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=True, total_tokens=7))
    assert extract_openai_usage(resp) == {"total_tokens": 7}


# ---------------------------------------------------------------------------
# Router copies usage onto the selected record (content-free metadata)
# ---------------------------------------------------------------------------


@pytest.fixture
def router(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import core.config as cc

    monkeypatch.setattr(cc, "APP_ROOT", tmp_path)
    cc.get_settings.cache_clear()
    (tmp_path / "config").mkdir()
    shutil.copy(_REAL_ROOT / "config" / "providers.yaml", tmp_path / "config" / "providers.yaml")
    from providers.router import ProviderRouter

    return ProviderRouter()


def _mock_adapter(name, response):
    adapter = MagicMock()
    adapter.name.return_value = name
    adapter.is_available.return_value = True
    adapter.cost_tier.return_value = "low"
    adapter.complete.return_value = response
    return adapter


def test_router_records_usage_from_response_metadata(router):
    from providers.base import Message

    resp = ProviderResponse(
        content="hi", provider_name="mock_a", model="m", success=True,
        metadata={"usage": {"prompt_tokens": 10, "total_tokens": 15}},
    )
    router._all_adapters = {"mock_a": _mock_adapter("mock_a", resp)}
    router._adapter_configs = {"mock_a": {"enabled": True, "type": "api"}}
    router._ranking = {"balanced": ["mock_a"]}
    router._fallback_on_error = True

    out = router.route([Message(role="user", content="q")], None, {"routing": {"mode": "balanced"}})
    diag = out.metadata["diagnostics"]
    sel_rec = next(r for r in diag["records"] if r["provider"] == "mock_a")
    assert sel_rec["usage"] == {"prompt_tokens": 10, "total_tokens": 15}


def test_router_usage_is_none_when_absent(router):
    from providers.base import Message

    resp = ProviderResponse(content="hi", provider_name="mock_a", model="m", success=True)
    router._all_adapters = {"mock_a": _mock_adapter("mock_a", resp)}
    router._adapter_configs = {"mock_a": {"enabled": True, "type": "api"}}
    router._ranking = {"balanced": ["mock_a"]}
    router._fallback_on_error = True

    out = router.route([Message(role="user", content="q")], None, {"routing": {"mode": "balanced"}})
    diag = out.metadata["diagnostics"]
    sel_rec = next(r for r in diag["records"] if r["provider"] == "mock_a")
    assert sel_rec["usage"] is None


# ---------------------------------------------------------------------------
# build_cli_usage — the STDERR one-liner
# ---------------------------------------------------------------------------


def test_cli_usage_full():
    diag = {
        "selected": "chatgpt",
        "records": [
            {"provider": "chatgpt", "usage": {"prompt_tokens": 1204, "completion_tokens": 320, "total_tokens": 1524}},
        ],
    }
    assert build_cli_usage(diag) == "Tokens: 1,204 prompt + 320 completion = 1,524 total"


def test_cli_usage_unavailable_for_cli_transport():
    diag = {"selected": "claude", "records": [{"provider": "claude", "usage": None}]}
    assert build_cli_usage(diag) == "Tokens: unavailable"


def test_cli_usage_empty_without_trace():
    assert build_cli_usage(None) == ""
    assert build_cli_usage({"selected": None, "records": []}) == ""


def test_cli_usage_partial_counts():
    diag = {"selected": "ollama", "records": [{"provider": "ollama", "usage": {"total_tokens": 42}}]}
    assert build_cli_usage(diag) == "Tokens: 42 total"
