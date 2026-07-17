"""
tests/test_file_manager.py — Tests for files/manager.py.

Covers: allowlist CRUD, path traversal rejection, permission checks,
read/write operations, audit logging, and config write protection.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Local fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def fm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """FileManager wired to a tmp directory."""
    import files.manager as fm_mod
    import core.config as cc

    monkeypatch.setattr(cc, "APP_ROOT", tmp_path)
    monkeypatch.setattr(fm_mod, "APP_ROOT", tmp_path)
    monkeypatch.setattr(fm_mod, "_FILES_CONFIG", tmp_path / "config" / "files.yaml")
    monkeypatch.setattr(fm_mod, "_AUDIT_DIR", tmp_path / "audit")

    # Create minimal directory structure
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "audit").mkdir()

    (config_dir / "files.yaml").write_text(
        yaml.safe_dump(
            {
                "entries": [
                    {
                        "path": "data",
                        "label": "Data",
                        "search": True,
                        "read": True,
                        "write": True,
                    },
                    {
                        "path": "logs",
                        "label": "Logs",
                        "search": True,
                        "read": True,
                        "write": False,
                    },
                ]
            }
        )
    )

    from files.manager import FileManager

    return FileManager()


# ---------------------------------------------------------------------------
# Allowlist CRUD
# ---------------------------------------------------------------------------


def test_list_allowlist_returns_entries(fm):
    """list_allowlist() returns 2 entries; first has path='data'."""
    entries = fm.list_allowlist()
    assert len(entries) == 2
    assert entries[0]["path"] == "data"


def test_add_entry_and_list(fm):
    """Adding a new entry raises count to 3 and the entry appears in the list."""
    fm.add_entry("exports", label="Exports", search=True, read=True, write=True)
    entries = fm.list_allowlist()
    assert len(entries) == 3
    paths = [e["path"] for e in entries]
    assert "exports" in paths


def test_add_duplicate_entry_raises(fm):
    """Adding a path that's already in the allowlist raises ValueError."""
    with pytest.raises(ValueError, match="already in allowlist"):
        fm.add_entry("data", label="Dup", search=True, read=True, write=True)


def test_remove_entry(fm):
    """Removing an existing entry returns True and reduces the list to 1."""
    result = fm.remove_entry("logs")
    assert result is True
    assert len(fm.list_allowlist()) == 1


def test_remove_nonexistent_entry(fm):
    """Removing a path not in the list returns False."""
    assert fm.remove_entry("nonexistent") is False


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def test_resolve_path_within_allowed_root(fm, tmp_path: Path):
    """resolve_path on a file inside an allowed root returns a non-None Path."""
    test_file = tmp_path / "data" / "test.txt"
    test_file.write_text("hello")
    result = fm.resolve_path("data/test.txt")
    assert result is not None
    assert isinstance(result, Path)


def test_resolve_path_traversal_rejected(fm):
    """resolve_path with a path-traversal sequence returns None."""
    result = fm.resolve_path("../../etc/passwd")
    assert result is None


def test_resolve_path_outside_all_roots_rejected(fm):
    """resolve_path for an absolute path outside the allowlist returns None."""
    result = fm.resolve_path("/tmp/outside_project.txt")
    assert result is None


# ---------------------------------------------------------------------------
# Read / write operations
# ---------------------------------------------------------------------------


def test_read_file_success(fm, tmp_path: Path):
    """read_file returns the correct content for an allowed file."""
    test_file = tmp_path / "data" / "hello.txt"
    test_file.write_text("hello world", encoding="utf-8")
    result = fm.read_file("data/hello.txt")
    assert result["content"] == "hello world"


def test_read_file_no_read_permission(fm, tmp_path: Path):
    """read_file raises PermissionError for a path without read permission."""
    # Add a write-only entry
    (tmp_path / "exports").mkdir()
    fm.add_entry("exports", label="Exports", search=False, read=False, write=True)
    test_file = tmp_path / "exports" / "file.txt"
    test_file.write_text("secret", encoding="utf-8")

    with pytest.raises(PermissionError):
        fm.read_file("exports/file.txt")


def test_write_file_success(fm, tmp_path: Path):
    """write_file returns {'written': True, 'path': ...} and creates the file."""
    result = fm.write_file("data/output.txt", "test content")
    assert result["written"] is True
    assert result["path"] == "data/output.txt"
    written_file = tmp_path / "data" / "output.txt"
    assert written_file.exists()
    assert written_file.read_text(encoding="utf-8") == "test content"


def test_write_file_no_write_permission(fm, tmp_path: Path):
    """write_file raises PermissionError for a path with write=False."""
    (tmp_path / "logs" / "output.txt").parent.mkdir(parents=True, exist_ok=True)
    with pytest.raises(PermissionError):
        fm.write_file("logs/output.txt", "test")


def test_write_file_creates_audit_log(fm, tmp_path: Path):
    """write_file appends a WRITE record to the audit directory."""
    fm.write_file("data/audit_test.txt", "audit me")
    audit_dir = tmp_path / "audit"
    audit_files = list(audit_dir.glob("*_file_audit.log"))
    assert len(audit_files) >= 1
    content = audit_files[0].read_text(encoding="utf-8")
    assert "WRITE" in content
    assert "data/audit_test.txt" in content


# ---------------------------------------------------------------------------
# Security guards
# ---------------------------------------------------------------------------


def test_write_to_files_yaml_rejected(fm):
    """write_file raises PermissionError when targeting config/files.yaml."""
    with pytest.raises(PermissionError):
        fm.write_file("config/files.yaml", "hacked: true")


def test_path_traversal_via_write_rejected(fm):
    """write_file raises PermissionError for a traversal path."""
    with pytest.raises(PermissionError):
        fm.write_file("data/../../etc/passwd", "hacked")


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def test_search_files(fm, tmp_path: Path):
    """search_files returns matching files within allowed roots."""
    (tmp_path / "data" / "foo.txt").write_text("foo")
    (tmp_path / "data" / "bar.yaml").write_text("bar: 1")

    txt_results = fm.search_files("*.txt")
    assert any("foo.txt" in r for r in txt_results)

    yaml_results = fm.search_files("*.yaml")
    assert any("bar.yaml" in r for r in yaml_results)


# ---------------------------------------------------------------------------
# Reload
# ---------------------------------------------------------------------------


def test_reload_picks_up_changes(fm, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """After modifying files.yaml and calling reload(), the new entry appears."""
    config_path = tmp_path / "config" / "files.yaml"
    existing = yaml.safe_load(config_path.read_text())
    existing["entries"].append(
        {
            "path": "exports",
            "label": "Exports",
            "search": True,
            "read": True,
            "write": True,
        }
    )
    config_path.write_text(yaml.safe_dump(existing))

    fm.reload()
    paths = [e["path"] for e in fm.list_allowlist()]
    assert "exports" in paths


# ---------------------------------------------------------------------------
# M26.14 — read_file robustness: binary safety + 2MB cap
# ---------------------------------------------------------------------------


def test_read_file_binary_does_not_raise(fm, tmp_path: Path):
    """A non-UTF-8 (binary) file decodes with replacement chars — no exception."""
    (tmp_path / "data" / "blob.bin").write_bytes(b"\x00\xff\xfe\xfa binary \x80")

    result = fm.read_file("data/blob.bin")

    assert result["truncated"] is False
    assert "�" in result["content"]  # replacement character present
    assert "binary" in result["content"]  # valid parts survive


def test_read_file_caps_at_2mb(fm, tmp_path: Path):
    """A >2MB file returns exactly the first 2MB with truncated=True."""
    import files.manager as fm_mod

    big = b"a" * (fm_mod._MAX_READ_BYTES + 100)
    (tmp_path / "data" / "big.txt").write_bytes(big)

    result = fm.read_file("data/big.txt")

    assert result["truncated"] is True
    assert len(result["content"]) == fm_mod._MAX_READ_BYTES


def test_read_file_small_text_untouched(fm, tmp_path: Path):
    """Normal small text round-trips exactly, truncated=False."""
    (tmp_path / "data" / "note.txt").write_text("hello Athena", encoding="utf-8")

    result = fm.read_file("data/note.txt")

    assert result["content"] == "hello Athena"
    assert result["truncated"] is False


# ---------------------------------------------------------------------------
# M30.4 — search results are files only; uploads are reachable one level down
# ---------------------------------------------------------------------------


def test_search_excludes_directories(fm, tmp_path):
    """A bare directory must never appear as a search result — the UI renders
    results as previewable files and a directory preview 400s (observed live
    with data/uploads)."""
    uploads = tmp_path / "data" / "uploads"
    uploads.mkdir()
    (uploads / "doc.txt").write_text("hello")

    results = fm.search_files("*")
    assert not any(r.endswith("data/uploads") for r in results), results
    assert all("uploads" != r.rsplit("/", 1)[-1] for r in results)


def test_search_uploads_pattern_lists_nested_files(fm, tmp_path):
    """The `uploads/*` pattern (used by the Files tab since M30.4) surfaces
    uploaded files one level below the shallow `*` listing."""
    uploads = tmp_path / "data" / "uploads"
    uploads.mkdir()
    (uploads / "pom.xml").write_text("<project/>")

    results = fm.search_files("uploads/*")
    assert any(r.endswith("data/uploads/pom.xml") for r in results), results
