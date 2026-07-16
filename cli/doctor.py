"""
cli/doctor.py — `athena doctor`: preflight diagnostics (M28.6).

The executable form of docs/PLATFORMS.md: can THIS host run Athena, and
what's missing? Checks are **config/filesystem-only — deliberately no
network** (same rule as the router's config-based availability), so doctor
is deterministic and works offline.

Secret hygiene contract: the report shows provider-key NAMES and set/not-set
only — never a value (enforced by test).

Each check returns (name, status, detail) with status "ok" | "warn" | "fail";
`run_doctor()` prints the report to STDOUT (the report IS the answer) and
returns 1 if anything failed, else 0. Warns don't fail the run.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

Check = tuple[str, str, str]

_KEY_NAMES = ("OPENAI_API_KEY", "XAI_API_KEY")
_VENDOR_CLIS = ("claude", "gemini", "grok", "hermes")
_DAV_CONFIGS = ("caldav", "carddav", "nextcloud")


def check_versions() -> list[Check]:
    from core.version import __version__  # noqa: PLC0415

    py = sys.version_info
    py_txt = f"{py.major}.{py.minor}.{py.micro}"
    py_ok = (py.major, py.minor) >= (3, 10)
    return [
        ("app version", "ok", __version__),
        ("python", "ok" if py_ok else "fail", py_txt + ("" if py_ok else " (need >= 3.10)")),
    ]


def check_env_keys(app_root: Path) -> list[Check]:
    out: list[Check] = []
    env_path = app_root / ".env"
    out.append(
        ("env file", "ok" if env_path.exists() else "warn",
         ".env present" if env_path.exists() else ".env missing (copy .env.example)")
    )
    for key in _KEY_NAMES:
        is_set = bool(os.environ.get(key, "").strip())
        out.append(
            (f"key {key}", "ok" if is_set else "warn",
             "set" if is_set else "not set (API transport unavailable)")
        )
    return out


def check_vendor_clis() -> list[Check]:
    out: list[Check] = []
    for cli in _VENDOR_CLIS:
        found = shutil.which(cli) is not None
        out.append(
            (f"cli {cli}", "ok" if found else "warn",
             "on PATH" if found else "not found (CLI transport unavailable)")
        )
    return out


def check_profile(app_root: Path) -> list[Check]:
    from core.config import get_settings  # noqa: PLC0415
    from core.loader import load_yaml  # noqa: PLC0415

    out: list[Check] = []
    name = get_settings().active_profile
    if os.environ.get("ATHENA_PROFILE_OVERRIDE", "").strip():
        source = "override flag"
    elif (app_root / "config" / "active_profile.yaml").exists():
        source = "switch file"
    elif os.environ.get("ACTIVE_PROFILE"):
        source = "env"
    else:
        source = "default"
    out.append(("active profile", "ok", f"{name} (via {source})"))

    pdir = app_root / "profiles" / name
    yaml_path = pdir / "profile.yaml"
    if not yaml_path.exists():
        out.append(("profile.yaml", "fail", f"missing: profiles/{name}/profile.yaml"))
        return out
    try:
        data = load_yaml(yaml_path)
        valid = isinstance(data, dict) and bool(data)
    except Exception:  # noqa: BLE001
        valid = False
    out.append(("profile.yaml", "ok" if valid else "fail", "parses" if valid else "invalid yaml"))
    mem = pdir / "memory"
    out.append(
        ("memory dir", "ok" if mem.is_dir() else "warn",
         "present" if mem.is_dir() else "missing (created on first save)")
    )
    return out


def check_dirs(app_root: Path) -> list[Check]:
    out: list[Check] = []
    for rel in ("logs", "audit", "data"):
        p = app_root / rel
        if not p.exists():
            out.append((f"dir {rel}/", "fail", "missing (run task setup)"))
        elif not os.access(p, os.W_OK):
            out.append((f"dir {rel}/", "fail", "not writable"))
        else:
            out.append((f"dir {rel}/", "ok", "writable"))
    return out


def check_disk(app_root: Path) -> list[Check]:
    try:
        free = shutil.disk_usage(app_root).free
    except Exception:  # noqa: BLE001
        return [("disk", "warn", "could not measure free space")]
    gb = free / (1024**3)
    return [("disk", "ok" if gb >= 1 else "warn", f"{gb:.1f} GB free" + ("" if gb >= 1 else " (<1 GB)"))]


def check_dav(app_root: Path) -> list[Check]:
    from core.loader import load_yaml  # noqa: PLC0415

    out: list[Check] = []
    for name in _DAV_CONFIGS:
        path = app_root / "config" / f"{name}.yaml"
        try:
            cfg = load_yaml(path) if path.exists() else {}
        except Exception:  # noqa: BLE001
            cfg = {}
        if not cfg or not cfg.get("enabled"):
            out.append((f"dav {name}", "ok", "disabled"))
        elif str(cfg.get("url", "")).strip():
            out.append((f"dav {name}", "ok", "enabled, url configured (not probed)"))
        else:
            out.append((f"dav {name}", "warn", "enabled but no url configured"))
    return out


def run_doctor() -> int:
    """Print the preflight report to stdout; exit code 1 iff any check fails."""
    from core.config import APP_ROOT  # noqa: PLC0415 — resolve at call time (tests patch it)

    checks: list[Check] = []
    checks += check_versions()
    checks += check_env_keys(APP_ROOT)
    checks += check_vendor_clis()
    checks += check_profile(APP_ROOT)
    checks += check_dirs(APP_ROOT)
    checks += check_disk(APP_ROOT)
    checks += check_dav(APP_ROOT)

    label = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL"}
    width = max(len(name) for name, _, _ in checks)
    print("athena doctor — preflight report")
    for name, status, detail in checks:
        print(f"  {label[status]}  {name:<{width}}  {detail}")
    fails = sum(1 for _, s, _ in checks if s == "fail")
    warns = sum(1 for _, s, _ in checks if s == "warn")
    print(f"{len(checks)} checks: {fails} failed, {warns} warnings.")
    print("Note: doctor checks presence/config, not validity — no network calls.")
    return 1 if fails else 0
