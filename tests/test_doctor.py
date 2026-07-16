"""`athena doctor` preflight diagnostics (M28.6).

The security-relevant contract: the report never contains a secret VALUE —
only key names and set/not-set. Everything is config/filesystem-based; no
network. Uses tmp_project via cli_env-style monkeypatching of APP_ROOT.
"""

from __future__ import annotations

import pytest

from cli.main import main


@pytest.fixture
def doctor_env(tmp_project, monkeypatch):
    import core.config as cc

    monkeypatch.setattr(cc, "APP_ROOT", tmp_project)
    monkeypatch.setenv("ACTIVE_PROFILE", "athena")
    cc.get_settings.cache_clear()
    yield tmp_project
    cc.get_settings.cache_clear()


def test_doctor_healthy_project_exits_zero(doctor_env, capsys):
    assert main(["--doctor"]) == 0
    out = capsys.readouterr().out
    assert "preflight report" in out
    assert "app version" in out and "python" in out
    assert "active profile" in out and "athena (via env)" in out
    assert "dir logs/" in out and "writable" in out
    assert "0 failed" in out


def test_doctor_subcommand_sugar(doctor_env, capsys):
    assert main(["doctor"]) == 0
    assert "preflight report" in capsys.readouterr().out


def test_doctor_missing_profile_yaml_fails(doctor_env, capsys):
    (doctor_env / "profiles" / "athena" / "profile.yaml").unlink()
    assert main(["--doctor"]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "profile.yaml" in out


def test_doctor_never_prints_secret_values(doctor_env, capsys, monkeypatch):
    secret = "sk-supersecret-token-abcdef123456"
    (doctor_env / ".env").write_text(f"OPENAI_API_KEY={secret}\n")
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    assert main(["--doctor"]) == 0
    out = capsys.readouterr().out
    assert secret not in out            # the contract
    assert "key OPENAI_API_KEY" in out and "set" in out


def test_doctor_reports_missing_key_and_cli(doctor_env, capsys, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("cli.doctor.shutil.which", lambda _name: None)
    assert main(["--doctor"]) == 0      # warns are not failures
    out = capsys.readouterr().out
    assert "not set" in out
    assert "cli claude" in out and "not found" in out


def test_doctor_finds_clis_when_present(doctor_env, capsys, monkeypatch):
    monkeypatch.setattr("cli.doctor.shutil.which", lambda _name: "/usr/bin/x")
    assert main(["--doctor"]) == 0
    assert "on PATH" in capsys.readouterr().out
