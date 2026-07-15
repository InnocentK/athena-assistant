"""
tests/test_provider_router.py — Tests for providers/router.py.

Tests routing logic in isolation using mock adapters.
Does not require any real AI provider CLIs or API keys.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_REAL_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Helper: create a mock adapter
# ---------------------------------------------------------------------------


def _make_mock_adapter(name="mock", available=True, success=True, cost_tier="low"):
    """Return a MagicMock that behaves like a ProviderAdapter."""
    from providers.base import ProviderResponse

    adapter = MagicMock()
    adapter.name.return_value = name
    adapter.is_available.return_value = available
    adapter.cost_tier.return_value = cost_tier
    adapter.complete.return_value = ProviderResponse(
        success=success,
        content="mock response",
        provider_name=name,
        model="mock-model",
        error=None if success else "mock failure",
    )
    return adapter


# ---------------------------------------------------------------------------
# Fixture: router wired to a tmp directory
# ---------------------------------------------------------------------------


@pytest.fixture
def router(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """ProviderRouter backed by tmp config directory."""
    import core.config as cc

    monkeypatch.setattr(cc, "APP_ROOT", tmp_path)
    cc.get_settings.cache_clear()

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    shutil.copy(_REAL_ROOT / "config" / "providers.yaml", config_dir / "providers.yaml")

    from providers.router import ProviderRouter

    return ProviderRouter()


# ---------------------------------------------------------------------------
# Basic initialisation
# ---------------------------------------------------------------------------


def test_router_init(router):
    """ProviderRouter initialises without raising."""
    assert router is not None


def test_list_providers_returns_list(router):
    """list_providers() returns a list of dicts with expected keys."""
    providers = router.list_providers()
    assert isinstance(providers, list)
    for item in providers:
        assert "name" in item
        assert "enabled" in item
        assert "available" in item
        assert "cost_tier" in item
        assert "type" in item


# ---------------------------------------------------------------------------
# Routing logic with mock adapters
# ---------------------------------------------------------------------------


def _setup_two_mock_adapters(router, adapter_a, adapter_b):
    """Wire two mock adapters into a router for routing tests."""
    router._all_adapters = {"mock_a": adapter_a, "mock_b": adapter_b}
    router._adapter_configs = {
        "mock_a": {"enabled": True, "type": "api"},
        "mock_b": {"enabled": True, "type": "api"},
    }
    router._ranking = {"balanced": ["mock_a", "mock_b"]}
    router._fallback_on_error = True


def test_router_uses_preferred_provider_first(router):
    """preferred_provider is tried first; on success, the other adapter is skipped."""
    from providers.base import Message

    adapter_a = _make_mock_adapter("mock_a", success=True)
    adapter_b = _make_mock_adapter("mock_b", success=True)
    _setup_two_mock_adapters(router, adapter_a, adapter_b)

    profile = {"routing": {"mode": "balanced", "preferred_provider": "mock_b"}}
    messages = [Message(role="user", content="hello")]

    response = router.route(messages, None, profile)

    assert response.success is True
    # mock_b was preferred and succeeded — mock_a should not have been called
    assert adapter_b.complete.call_count == 1
    assert adapter_a.complete.call_count == 0


def test_router_falls_back_on_failure(router):
    """When the first adapter fails, the router falls back to the next."""
    from providers.base import Message

    adapter_a = _make_mock_adapter("mock_a", success=False)
    adapter_b = _make_mock_adapter("mock_b", success=True)
    _setup_two_mock_adapters(router, adapter_a, adapter_b)

    profile = {"routing": {"mode": "balanced", "preferred_provider": None}}
    messages = [Message(role="user", content="hello")]

    response = router.route(messages, None, profile)

    assert response.success is True
    assert response.provider_name == "mock_b"


def test_router_returns_failure_when_all_fail(router):
    """When all adapters fail, the router returns success=False."""
    from providers.base import Message

    adapter_a = _make_mock_adapter("mock_a", success=False)
    adapter_b = _make_mock_adapter("mock_b", success=False)
    _setup_two_mock_adapters(router, adapter_a, adapter_b)

    profile = {"routing": {"mode": "balanced", "preferred_provider": None}}
    messages = [Message(role="user", content="hello")]

    response = router.route(messages, None, profile)

    assert response.success is False
    assert response.content == "All providers failed."


def test_router_skips_disabled_adapters(router):
    """Disabled adapters are never called during routing."""
    from providers.base import Message

    adapter_a = _make_mock_adapter("mock_a", success=True)
    adapter_b = _make_mock_adapter("mock_b", success=True)

    router._all_adapters = {"mock_a": adapter_a, "mock_b": adapter_b}
    router._adapter_configs = {
        "mock_a": {"enabled": False, "type": "api"},
        "mock_b": {"enabled": True, "type": "api"},
    }
    router._ranking = {"balanced": ["mock_a", "mock_b"]}
    router._fallback_on_error = True

    profile = {"routing": {"mode": "balanced", "preferred_provider": None}}
    messages = [Message(role="user", content="hello")]

    response = router.route(messages, None, profile)

    assert adapter_a.complete.call_count == 0
    assert adapter_b.complete.call_count == 1
    assert response.success is True


def test_router_skips_unavailable_adapters(router):
    """Adapters that report is_available()==False are skipped."""
    from providers.base import Message

    adapter_a = _make_mock_adapter("mock_a", available=False, success=True)
    adapter_b = _make_mock_adapter("mock_b", available=True, success=True)
    _setup_two_mock_adapters(router, adapter_a, adapter_b)

    profile = {"routing": {"mode": "balanced", "preferred_provider": None}}
    messages = [Message(role="user", content="hello")]

    response = router.route(messages, None, profile)

    assert adapter_a.complete.call_count == 0
    assert adapter_b.complete.call_count == 1
    assert response.success is True


# ---------------------------------------------------------------------------
# Ranking / ordering helpers
# ---------------------------------------------------------------------------


def test_get_ordered_names_quality_first(router):
    """_get_ordered_names returns names in the configured order."""
    router._ranking = {"quality_first": ["claude", "gemini"]}
    names = router._get_ordered_names("quality-first")
    assert names == ["claude", "gemini"]


# ---------------------------------------------------------------------------
# Ollama integration with the shipped providers.yaml (Milestone 15.5)
# ---------------------------------------------------------------------------


def test_router_registers_ollama_adapter(router):
    """The ollama adapter is discovered via the registry."""
    assert "ollama" in router._all_adapters


def test_router_skips_ollama_when_disabled_by_default(router):
    """
    ollama ships enabled:false, so even though it leads budget_first it is
    never attempted. Guards the opt-in invariant for Milestone 15.5.
    """
    from providers.base import Message

    ollama = _make_mock_adapter("ollama", available=True, success=True)
    router._all_adapters["ollama"] = ollama

    profile = {"routing": {"mode": "budget-first", "preferred_provider": None}}
    router.route([Message(role="user", content="hi")], None, profile)

    # disabled in the shipped config -> skipped before complete() is ever called
    assert ollama.complete.call_count == 0


def test_router_uses_ollama_when_enabled_and_preferred(router):
    """When enabled and set as preferred_provider, ollama is chosen first."""
    from providers.base import Message

    ollama = _make_mock_adapter("ollama", available=True, success=True)
    router._all_adapters["ollama"] = ollama
    router._adapter_configs["ollama"] = {"enabled": True, "type": "api"}

    profile = {"routing": {"mode": "balanced", "preferred_provider": "ollama"}}
    response = router.route([Message(role="user", content="hi")], None, profile)

    assert response.success is True
    assert response.provider_name == "ollama"
    assert ollama.complete.call_count == 1
