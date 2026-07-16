"""
cli/history_cmd.py — `athena history …` (M29.6).

The CLI's read surface for persistent conversations (M29.1). Routed as a
pre-parser subcommand token from cli/main.py (like `doctor`), so the main
argparse stays untouched.

Output contract (M25): the requested content — the list, the transcript, the
Markdown — IS this command's answer and goes to STDOUT (same rule as
`--list-providers`). Errors and notices go to stderr.

Profile resolution is the standard order (override > switch file > env >
default); `--profile` is not plumbed here — the switch file is the
persistent mechanism.
"""

from __future__ import annotations

import sys
from typing import Any

_SEPARATOR = "\n---\n"


def _store():
    from core.config import active_profile_dir  # noqa: PLC0415
    from history.manager import ConversationStore  # noqa: PLC0415

    return ConversationStore(active_profile_dir())


def _render_transcript(store: Any, conv_id: str) -> str:
    """Human-readable transcript (show); failed turns marked."""
    turns = store.read(conv_id)
    lines = [f"Conversation {conv_id} ({len(turns)} turns)"]
    for t in turns:
        if t.get("role") == "user":
            who = "You"
        else:
            who = "Assistant"
            provider = t.get("provider")
            if provider:
                who += f" ({provider}{'/' + str(t['model']) if t.get('model') else ''})"
            if t.get("success") is False:
                who += " [failed]"
        lines.append(f"{who}: {t.get('content', '')}")
    return "\n".join(lines)


def _for_each_id(store: Any, ids: list[str], render) -> int:
    """Render each id to stdout with separators; unknown/bad id → stderr, 1."""
    rendered: list[str] = []
    for conv_id in ids:
        try:
            rendered.append(render(store, conv_id))
        except ValueError:
            print(f"Error: invalid conversation id: {conv_id}", file=sys.stderr)
            return 1
        except FileNotFoundError:
            print(f"Error: conversation not found: {conv_id}", file=sys.stderr)
            return 1
    print(_SEPARATOR.join(rendered))
    return 0


def run_history(argv: list[str]) -> int:
    """Entry point: [] → list; ['export', …] → markdown; [ids…] → transcripts."""
    try:
        store = _store()
    except Exception as exc:  # noqa: BLE001
        print(f"Error: history unavailable: {exc}", file=sys.stderr)
        return 1

    if not argv:
        conversations = store.list_conversations()
        if not conversations:
            print("No conversations yet.", file=sys.stderr)
            return 0
        print(f"{'ID':<22}{'STARTED':<22}{'TURNS':<7}PREVIEW")
        for c in conversations:
            print(
                f"{c['id']:<22}{(c['started_at'] or '—'):<22}"
                f"{c['turns']:<7}{c['preview']}"
            )
        return 0

    if argv[0] == "export":
        rest = argv[1:]
        if rest == ["--all"]:
            ids = [c["id"] for c in store.list_conversations()]
            if not ids:
                print("No conversations yet.", file=sys.stderr)
                return 0
        elif rest and not any(a.startswith("-") for a in rest):
            ids = rest
        else:
            print(
                "Usage: athena history export <id> [<id> ...] | --all",
                file=sys.stderr,
            )
            return 2
        return _for_each_id(store, ids, lambda s, i: s.render_markdown(i))

    if any(a.startswith("-") for a in argv):
        print("Usage: athena history [<id> ...] | export <id> [...] | export --all", file=sys.stderr)
        return 2
    return _for_each_id(store, argv, _render_transcript)
