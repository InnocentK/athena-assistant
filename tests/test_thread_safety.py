"""
tests/test_thread_safety.py — M26.16 consistency & thread-safety pass.

The singleton stores and the MemoryManager are mutated from
`asyncio.to_thread` worker threads while the event-loop thread reads or
rewrites the same state — genuinely multi-threaded even under single-worker
uvicorn. These tests hammer the hot paths from real threads (they reliably
raised "dictionary changed size during iteration" / RuntimeError / lost
updates before the locks) and pin the small consistency fixes.

Self-contained: threads + tmp dirs only; no network.
"""

from __future__ import annotations

import threading
from pathlib import Path



# ---------------------------------------------------------------------------
# DavStatusStore: concurrent mutation vs deepcopy snapshots
# ---------------------------------------------------------------------------


def test_dav_status_store_concurrent_update_and_snapshot():
    from dav_status.store import DavStatusStore

    store = DavStatusStore()
    stop = threading.Event()
    errors: list[BaseException] = []

    def _writer():
        i = 0
        while not stop.is_set():
            try:
                store.record_success("caldav", item_counts={f"k{i % 50}": i})
                store.add_warning("caldav", f"w{i}")
                store.record_error("carddav", "401 Unauthorized")
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
                return
            i += 1

    threads = [threading.Thread(target=_writer) for _ in range(4)]
    for t in threads:
        t.start()
    try:
        for _ in range(300):
            snapshot = store.get_all()  # deepcopy under the lock
            assert set(snapshot) >= {"caldav", "carddav", "nextcloud"}
            store.get("caldav")
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=5)

    assert not errors, f"writer thread raised: {errors[:1]}"


def test_humanise_error_is_public_with_compat_alias():
    from dav_status.store import DavStatusStore

    assert DavStatusStore.humanise_error(TimeoutError()) == (
        "Connection timed out — server did not respond in time"
    )
    # Pre-M26.16 private name still works (external callers were migrated,
    # but the alias keeps old code/tests from breaking).
    assert DavStatusStore._humanise_error("403 Forbidden") == (
        "Access denied — insufficient permissions"
    )


# ---------------------------------------------------------------------------
# DiagnosticsStore: concurrent record vs recent()
# ---------------------------------------------------------------------------


def test_diagnostics_store_concurrent_record_and_recent():
    from diagnostics.store import DiagnosticsStore, RequestTrace

    store = DiagnosticsStore(maxlen=50)
    stop = threading.Event()
    errors: list[BaseException] = []

    def _writer():
        while not stop.is_set():
            try:
                store.record(RequestTrace(mode="balanced"))
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
                return

    threads = [threading.Thread(target=_writer) for _ in range(4)]
    for t in threads:
        t.start()
    try:
        for _ in range(300):
            items = store.recent()
            assert len(items) <= 50
            store.last()
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=5)

    assert not errors, f"writer thread raised: {errors[:1]}"


# ---------------------------------------------------------------------------
# MemoryManager: concurrent pending-queue writes must not lose updates
# ---------------------------------------------------------------------------


def test_memory_pending_concurrent_adds_lose_nothing(tmp_path: Path):
    from memory.manager import MemoryManager

    profile_dir = tmp_path / "profiles" / "athena"
    (profile_dir / "memory").mkdir(parents=True)

    mm = MemoryManager(profile_dir=profile_dir, profile_config={})

    n_threads, per_thread = 8, 5
    barrier = threading.Barrier(n_threads)

    def _adder(tid: int):
        barrier.wait()
        for j in range(per_thread):
            mm.add_to_pending(
                category="preferences",
                key=f"k-{tid}-{j}",
                value="v",
                reason="race test",
            )

    threads = [threading.Thread(target=_adder, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    pending = mm.get_pending()
    keys = {e["key"] for e in pending}
    assert len(keys) == n_threads * per_thread, (
        f"lost updates: expected {n_threads * per_thread}, got {len(keys)}"
    )


# ---------------------------------------------------------------------------
# backup_inspect goes through _safe_export_path like its siblings
# ---------------------------------------------------------------------------


def test_backup_inspect_uses_safe_export_path(client, tmp_project: Path, monkeypatch):
    import main as app_module

    calls: list[str] = []
    original = app_module._safe_export_path

    def _spy(filename: str):
        calls.append(filename)
        return original(filename)

    monkeypatch.setattr(app_module, "_safe_export_path", _spy)

    resp = client.get("/backup/exports/nonexistent.zip/inspect")
    assert resp.status_code == 404
    assert calls == ["nonexistent.zip"], "inspect must route through the guard"


def test_backup_inspect_valid_zip_still_works(client, tmp_project: Path):
    import json
    import zipfile

    exports = tmp_project / "data" / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(exports / "ok.zip", "w") as zf:
        zf.writestr(
            "athena_backup_manifest.json",
            json.dumps({"backup_version": "1", "app_version": "x", "files": []}),
        )

    resp = client.get("/backup/exports/ok.zip/inspect")
    assert resp.status_code == 200
