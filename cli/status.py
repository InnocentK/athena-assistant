"""
cli/status.py — CLI status/progress feedback (Milestone 25).

Terminal-side analog of the web UI's M24/M24.5 diagnostics, built entirely from
the content-free M22 trace on ``response.metadata["diagnostics"]`` — no router or
diagnostics-engine changes, no new measurement.

Output contract (inherited from cli/main.py): STDOUT carries only the answer.
Everything here writes to STDERR, and the in-flight spinner only animates when
STDERR is an interactive TTY, so piped/redirected runs stay clean.

The spinner starts generic ("Working… 1.3s") and then, via the router's
``on_attempt`` progress callback (M27.0), updates to the provider being tried
right now ("Trying claude/cli… 1.3s"), so a fall-through across providers is
visible live. ``ProviderRouter.route`` remains synchronous — the callback fires
at each attempt boundary, which is enough for a live status line without a
streaming rewrite (true token-level streaming stays future work).
"""

from __future__ import annotations

import itertools
import sys
import threading
import time
from typing import Any

_SPINNER_FRAMES_UNICODE = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_SPINNER_FRAMES_ASCII = "|/-\\"


def stream_is_tty(stream: Any) -> bool:
    """True if *stream* is an interactive TTY; conservative (False) on error."""
    try:
        return bool(stream.isatty())
    except Exception:  # noqa: BLE001 — treat anything odd as non-interactive
        return False


class Spinner:
    """
    Minimal background-thread spinner that animates on a stream (STDERR by
    default) while a blocking call runs. Disabled — emitting nothing at all —
    unless ``enabled`` and the stream is a TTY. Safe as a context manager;
    ``stop()`` always clears the line and never raises.
    """

    def __init__(
        self,
        text: str = "Working…",
        enabled: bool = True,
        stream: Any = None,
        interval: float = 0.12,
    ) -> None:
        self._text = text
        self._stream = stream if stream is not None else sys.stderr
        self._interval = interval
        self._active = bool(enabled) and stream_is_tty(self._stream)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_time = 0.0

    @property
    def active(self) -> bool:
        """Whether this spinner will actually animate (enabled AND a TTY)."""
        return self._active

    def set_text(self, text: str) -> None:
        """
        Update the in-flight label (M27.0 live status). The animation loop reads
        ``self._text`` afresh each frame, so a mid-flight update (e.g. the router
        moving to the next provider) shows on the next tick. A single attribute
        write is atomic under the GIL, which is all a display string needs.
        """
        self._text = text

    def _frames(self) -> "itertools.cycle[str]":
        enc = ""
        try:
            enc = (self._stream.encoding or "").lower()
        except Exception:  # noqa: BLE001
            enc = ""
        chars = _SPINNER_FRAMES_UNICODE if "utf" in enc else _SPINNER_FRAMES_ASCII
        return itertools.cycle(chars)

    def _run(self) -> None:
        frames = self._frames()
        while not self._stop.is_set():
            elapsed = time.monotonic() - self._start_time
            try:
                self._stream.write(f"\r{next(frames)} {self._text} {elapsed:.1f}s")
                self._stream.flush()
            except Exception:  # noqa: BLE001 — never let the indicator break the run
                return
            self._stop.wait(self._interval)

    def start(self) -> "Spinner":
        if not self._active:
            return self
        self._start_time = time.monotonic()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if not self._active:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)
            self._thread = None
        try:
            self._stream.write("\r\033[K")  # carriage return + clear to end of line
            self._stream.flush()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> "Spinner":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()


def _label(rec: dict[str, Any]) -> str:
    provider = rec.get("provider", "?")
    transport = rec.get("transport")
    return f"{provider}/{transport}" if transport else str(provider)


def live_status_text(info: dict[str, Any]) -> str:
    """
    Spinner label for an in-flight provider attempt (M27.0), built from the
    router's ``on_attempt`` payload (``provider``/``transport``). E.g.
    "Trying claude/cli…". Falls back gracefully when fields are missing.
    """
    return f"Trying {_label(info)}…"


def build_cli_summary(diag: dict[str, Any] | None) -> str:
    """
    Concise one-line summary from the M22 trace dict — mirrors the web wording:

        "Answered via grok/api in 0.8s."
        "claude/cli unavailable; answered via grok/api in 0.8s."
        "No provider answered."

    Returns "" when there is no usable trace (e.g. diagnostics disabled).
    """
    if not isinstance(diag, dict):
        return ""
    records = diag.get("records")
    if not isinstance(records, list):
        return ""

    selected = diag.get("selected")
    if not selected:
        return "No provider answered."

    total = diag.get("total_ms")
    total_s = f"{total / 1000:.1f}s" if isinstance(total, (int, float)) else ""

    sel_rec = next((r for r in records if r.get("provider") == selected), None)
    sel_label = _label(sel_rec) if sel_rec else str(selected)

    priors = [
        f"{_label(r)} {r.get('outcome')}"
        for r in records
        if r.get("provider") != selected and r.get("outcome") != "ok"
    ]
    core = f"answered via {sel_label}" + (f" in {total_s}" if total_s else "") + "."
    if priors:
        return "; ".join(priors) + "; " + core
    return core[0].upper() + core[1:]


def build_cli_breakdown(diag: dict[str, Any] | None) -> str:
    """
    Multi-line, parseable per-attempt breakdown for ``--diagnostics`` (STDERR).
    Built from the same M22 trace; "" when there is no trace.
    """
    if not isinstance(diag, dict):
        return ""
    records = diag.get("records")
    if not isinstance(records, list) or not records:
        return ""

    selected = diag.get("selected")
    head_bits = []
    if diag.get("mode"):
        head_bits.append(f"mode={diag['mode']}")
    total = diag.get("total_ms")
    if isinstance(total, (int, float)):
        head_bits.append(f"total={total / 1000:.1f}s")
    head_bits.append(f"selected={selected or 'none'}")

    lines = ["diagnostics: " + "  ".join(head_bits)]
    for r in records:
        dur = r.get("duration_ms")
        dur_txt = f"{dur:.0f}ms" if isinstance(dur, (int, float)) else "—"
        marker = "*" if r.get("provider") == selected else " "
        line = f"  {marker} {_label(r)} {r.get('outcome', '')} {dur_txt}"
        note = r.get("error_kind") or r.get("error")
        if note:
            line += f" ({note})"
        lines.append(line)
    return "\n".join(lines)
