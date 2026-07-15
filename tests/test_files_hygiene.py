"""
tests/test_files_hygiene.py — Files-tab view hygiene (Milestone 26.3).

The History → Files tab hides internal/operational artifacts (logs, audit,
staging, backups, `*.log`/`.gitkeep`/`*.pyc`) by default. The filter is a
backend capability on `/files/search` (`exclude_internal`) — not browser-only —
and the allowlist/security model is unchanged (default listing is unfiltered).
"""

from __future__ import annotations

from files.manager import _is_internal_path


def test_is_internal_path_true_for_internal():
    for p in [
        "logs/app.log",
        "audit/2026-06-26_file_audit.log",
        "audit/ops_audit.py",
        "data/carddav_staged",
        "data/import_conflicts/x.json",
        "data/restore_staging/2026",
        "data/exports/backup.zip",
        "data/.gitkeep",
        "some/dir/notes.log",
        "pkg/mod.pyc",
    ]:
        assert _is_internal_path(p) is True, p


def test_is_internal_path_false_for_user_files():
    for p in [
        "data/notes.txt",
        "data/sub/report.md",
        "docs/readme.md",
        "config/app.yaml",
        "data/projects/main.py",
    ]:
        assert _is_internal_path(p) is False, p


def _seed(tmp_project):
    (tmp_project / "data" / "notes.txt").write_text("hello")
    (tmp_project / "data" / ".gitkeep").write_text("")
    (tmp_project / "logs" / "app.log").write_text("log line")


def test_files_search_excludes_internal_when_flagged(client, tmp_project):
    _seed(tmp_project)
    user = client.post("/files/search", json={"pattern": "*", "exclude_internal": True}).json()
    assert "data/notes.txt" in user                      # user file kept
    assert "data/.gitkeep" not in user                   # internal file pattern
    assert "data/carddav_staged" not in user             # internal subtree
    assert not any(p.startswith("logs/") for p in user)  # logs subtree
    assert not any(p.endswith(".log") for p in user)     # *.log pattern


def test_files_search_default_is_unfiltered(client, tmp_project):
    _seed(tmp_project)
    allp = client.post("/files/search", json={"pattern": "*"}).json()
    # Backwards-compatible: without the flag the internal artifacts still list.
    assert "data/notes.txt" in allp
    assert any(p.startswith("logs/") for p in allp) or "data/carddav_staged" in allp
