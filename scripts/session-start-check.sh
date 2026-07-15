#!/usr/bin/env bash
# scripts/session-start-check.sh — SessionStart hook (M26.17).
#
# Verifies the baseline a fresh agent session needs before touching code:
#   1. core runtime deps import cleanly
#   2. ruff lint is clean (M26.19 — sub-second)
#   3. the test suite is green
#
# REPORTING ONLY: always exits 0. A red baseline is exactly the information
# the session needs (pre-existing failures are not yours) — it must inform,
# never block the session from opening.

cd "$(dirname "$0")/.." || exit 0

echo "=== Athena baseline check (SessionStart hook) ==="

PY="python3"
command -v "$PY" >/dev/null 2>&1 || { echo "python3 not found — install Python 3.10+"; exit 0; }

if "$PY" -c "import fastapi, yaml, pydantic, vobject, caldav, requests, defusedxml" 2>/dev/null; then
  echo "deps: OK (core imports present)"
else
  echo "deps: MISSING — run: pip install -r requirements.txt  (then: pip install -e .)"
  exit 0   # no point running pytest without deps
fi

# Lint (M26.19): fast correctness gate. Reports only — never blocks.
if command -v ruff >/dev/null 2>&1 || "$PY" -m ruff --version >/dev/null 2>&1; then
  RUFF_CMD="ruff"; command -v ruff >/dev/null 2>&1 || RUFF_CMD="$PY -m ruff"
  if $RUFF_CMD check . >/dev/null 2>&1; then
    echo "lint: OK (ruff clean)"
  else
    echo "lint: issues found — run 'task lint' (or 'ruff check .') for detail; 'task lint:fix' auto-fixes most"
  fi
else
  echo "lint: ruff not installed (pip install -r requirements.txt) — skipped"
fi

# Type-check (M26.21): lenient mypy gate. Reports only — never blocks.
if "$PY" -m mypy --version >/dev/null 2>&1; then
  if "$PY" -m mypy . >/dev/null 2>&1; then
    echo "types: OK (mypy clean)"
  else
    echo "types: issues found — run 'task typecheck' (or 'mypy .') for detail"
  fi
else
  echo "types: mypy not installed (pip install -r requirements.txt) — skipped"
fi

if "$PY" -m pytest --version >/dev/null 2>&1; then
  echo "test suite: running (fail-fast)…"
  # -x: a red baseline reports quickly; green runs the full suite (~30s).
  "$PY" -m pytest -q -x 2>&1 | tail -3
  echo "(if failures appear above, they are PRE-EXISTING — record them before changing code)"
else
  echo "pytest: not installed — baseline not verified (pip install -r requirements.txt)"
fi

exit 0
