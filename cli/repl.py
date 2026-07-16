"""
cli/repl.py — interactive multi-turn CLI session (M29.2).

Entered by bare ``athena`` on an interactive stdin (TTY); scripts and pipes
never land here (non-TTY bare invocation stays a usage error). One turn
pipeline, shared with the one-shot path and the web surface via M29.0/29.1:
``build_turn_messages`` + spinner/live status + ``record_turn`` persistence +
``extract_memory``.

Output contract (M25, unchanged): STDOUT carries ONLY answers — the ``you>``
input prompt, status, usage, and errors all go to STDERR, so piping a REPL
transcript still yields clean answer text.

History rules: a turn is replayed into later context ONLY on success (M26.10);
failed turns are persisted with ``success: false`` meta but never re-sent.
``/new`` starts a fresh in-session history + persisted conversation;
``/exit``, ``/quit``, or EOF end the session.
"""

from __future__ import annotations

import sys
from typing import Any

_HELP = (
    "Commands: /new (fresh conversation), /list (recent conversations), "
    "/resume <id> (continue one), /exit or /quit (leave). Ctrl-D exits."
)


def run_repl(router: Any, profile_config: dict[str, Any], args: Any) -> int:
    """Run the interactive loop. Returns the process exit code."""
    from core.chat_turn import (  # noqa: PLC0415
        build_turn_messages,
        extract_memory,
        record_turn,
        system_prompt_from,
    )
    from cli.status import (  # noqa: PLC0415
        Spinner,
        build_cli_summary,
        build_cli_usage,
        drive_stream,
        live_status_text,
        stream_is_tty,
    )

    # Persistent history (M29.1) — best-effort: a store failure degrades to an
    # unpersisted session, never blocks the REPL.
    store = None
    conv_id: str | None = None
    try:
        from core.config import active_profile_dir  # noqa: PLC0415
        from history.manager import ConversationStore  # noqa: PLC0415

        store = ConversationStore(active_profile_dir())
        conv_id = store.new_conversation()
    except Exception as exc:  # noqa: BLE001
        print(f"(history unavailable: {exc})", file=sys.stderr)

    memory = None
    if not args.no_memory:
        try:
            from core.config import active_profile_dir  # noqa: PLC0415
            from memory.manager import MemoryManager  # noqa: PLC0415

            memory = MemoryManager(active_profile_dir(), profile_config)
        except Exception:  # noqa: BLE001 — memory stays best-effort
            memory = None

    system_prompt = system_prompt_from(profile_config)
    history: list[tuple[str, str]] = []

    name = profile_config.get("name", "Athena")
    print(f"{name} REPL — {_HELP}", file=sys.stderr)

    while True:
        # Prompt on stderr: stdout must stay answer-only even in a transcript.
        print("you> ", end="", file=sys.stderr, flush=True)
        try:
            text = input()
        except (EOFError, KeyboardInterrupt):
            print("", file=sys.stderr)
            return 0

        text = text.strip()
        if not text:
            continue
        if text in ("/exit", "/quit"):
            return 0
        if text == "/new":
            history = []
            if store is not None:
                try:
                    conv_id = store.new_conversation()
                except Exception:  # noqa: BLE001
                    conv_id = None
            print("(new conversation)", file=sys.stderr)
            continue
        if text == "/list":
            # REPL status, not an answer → stderr (M29.6).
            if store is None:
                print("(history unavailable)", file=sys.stderr)
                continue
            conversations = store.list_conversations()[:10]
            if not conversations:
                print("(no conversations yet)", file=sys.stderr)
            for c in conversations:
                print(
                    f"  {c['id']}  {c['turns']} turns  {c['preview']}",
                    file=sys.stderr,
                )
            continue
        if text.startswith("/resume"):
            parts = text.split(None, 1)
            target = parts[1].strip() if len(parts) > 1 else ""
            if store is None or not target:
                print("Usage: /resume <id>  (see /list)", file=sys.stderr)
                continue
            try:
                turns = store.read(target)
            except (ValueError, FileNotFoundError):
                print(f"(no such conversation: {target})", file=sys.stderr)
                continue
            # Success-only replay (M26.10): failed turns never re-enter context.
            history = [
                (t["role"], str(t.get("content", "")))
                for t in turns
                if t.get("role") in ("user", "assistant")
                and not (t.get("role") == "assistant" and t.get("success") is False)
            ]
            conv_id = target
            print(
                f"(resumed {target}: {len(history)} turns in context)",
                file=sys.stderr,
            )
            continue
        if text.startswith("/"):
            print(_HELP, file=sys.stderr)
            continue

        messages = build_turn_messages(history, text)
        # REVIEW-3.0 F2: the user's question enters context NOW (web parity) —
        # even if this turn fails, the question is kept; only the failure TEXT
        # is never replayed (M26.10). Appended after build so it isn't doubled.
        history.append(("user", text))
        if store is not None and conv_id:
            record_turn(store, conv_id, "user", text)

        spinner = Spinner("Working…", enabled=not args.quiet)

        def _on_attempt(info: dict) -> None:
            spinner.set_text(live_status_text(info))  # noqa: B023 — rebound each turn

        # M30: stream by default (chunks ARE the answer, printed as they
        # arrive); --no-stream keeps the buffered pre-3.0 behavior per turn.
        printed_any = False
        spinner.start()
        try:
            if getattr(args, "no_stream", False):
                response = router.route(
                    messages, system_prompt, profile_config, on_attempt=_on_attempt
                )
            else:
                response, printed_any = drive_stream(
                    router.route_stream(
                        messages, system_prompt, profile_config, on_attempt=_on_attempt
                    ),
                    spinner,
                )
        except Exception as exc:  # noqa: BLE001 — never kill the session on one turn
            spinner.stop()
            print(f"Error: provider call failed: {exc}", file=sys.stderr)
            continue
        spinner.stop()

        if response is None:
            # Streaming iterator ended without a done event (contract violation).
            print("Error: provider stream ended without a final response.", file=sys.stderr)
            continue

        if store is not None and conv_id:
            record_turn(
                store, conv_id, "assistant", response.content,
                {"provider": response.provider_name, "model": response.model,
                 "success": response.success},
            )

        if not response.success:
            message = response.error or response.content or "All providers failed."
            print(f"Error: {message}", file=sys.stderr)
            continue  # M26.10: a failure is never replayed into context

        # The answer — and only the answer — goes to stdout (already printed
        # chunk-by-chunk when streaming).
        if not printed_any:
            print(response.content)

        history.append(("assistant", response.content))

        if not args.quiet:
            diagnostics = (
                response.metadata.get("diagnostics")
                if isinstance(response.metadata, dict)
                else None
            )
            summary = build_cli_summary(diagnostics)
            if summary and (stream_is_tty(sys.stderr) or args.diagnostics):
                print(summary, file=sys.stderr)
                usage_line = build_cli_usage(diagnostics)
                if usage_line:
                    print(usage_line, file=sys.stderr)

        extract_memory(memory, text, response.content)
