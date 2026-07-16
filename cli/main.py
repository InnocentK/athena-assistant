"""
cli/main.py — Athena one-shot command-line interface (Milestone 16).

Sends a single prompt to the active AI provider and prints the reply, reusing
Athena's existing config/profile/provider stack with no parallel execution
path. The only "logic" here is the thin glue mirrored from the HTTP /chat
handler: build a one-turn message list, read the profile's system prompt, and
call ``ProviderRouter.route(...)``.

Usage:
    python -m cli "What's the status of X?"
    python -m cli --provider ollama "Summarise today's notes"
    python -m cli --mode budget-first "Cheap answer please"
    python -m cli --list-providers

Output contract:
    - The model's answer is written to STDOUT (and nothing else), so it pipes
      cleanly.
    - All logs, diagnostics, and errors go to STDERR.

Exit codes:
    0  success
    1  runtime failure (no/failed providers, invalid or empty profile)
    2  usage error (missing prompt, bad flag — argparse default)
"""

from __future__ import annotations

import argparse
import os
import sys

VALID_MODES = ("quality-first", "balanced", "budget-first")


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser (separated out for testability)."""
    parser = argparse.ArgumentParser(
        prog="athena",
        description=(
            "Athena one-shot CLI — send a single prompt to the active AI "
            "provider and print the reply."
        ),
        epilog=(
            'Examples: athena "What\'s up?"  |  athena ask "What\'s up?"  |  '
            'python -m cli "What\'s up?" (no install needed). '
            "If the prompt starts with '-', put '--' first."
        ),
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        help='The prompt to send, quoted: athena "What\'s up?"',
    )
    parser.add_argument(
        "--profile",
        metavar="NAME",
        help="Profile to load (overrides the ACTIVE_PROFILE env var).",
    )
    parser.add_argument(
        "--mode",
        choices=VALID_MODES,
        help="Routing mode override for this run.",
    )
    parser.add_argument(
        "--provider",
        metavar="NAME",
        help="Preferred provider override for this run (e.g. ollama).",
    )
    parser.add_argument(
        "--list-providers",
        action="store_true",
        help="Print provider availability and exit (no prompt needed).",
    )
    parser.add_argument(
        "--no-memory",
        action="store_true",
        help="Skip best-effort memory auto-extraction for this run.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show INFO-level logs on stderr (default: warnings only).",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress the in-flight spinner and the status summary on stderr.",
    )
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Print an expanded per-provider timing breakdown on stderr.",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Run preflight diagnostics (config/filesystem only) and exit. "
        "Also available as: athena doctor",
    )
    return parser


def _normalize_argv(argv: list[str]) -> list[str]:
    """
    Support the ``ask`` subcommand alias by consuming a leading ``ask`` token.

    ``ask`` is honoured only as the first argument: ``athena ask "..."`` is
    equivalent to ``athena "..."``. A lone ``ask`` with nothing after it leaves
    an empty argv, which then fails the prompt-required check as a usage error
    (exit 2) — it is deliberately NOT treated as a literal prompt of "ask".
    """
    if argv and argv[0] == "ask":
        return argv[1:]
    # M28.6: `athena doctor` sugar — same alias mechanism as `ask`.
    if argv and argv[0] == "doctor":
        return ["--doctor"] + argv[1:]
    return argv


def _configure_cli_logging(verbose: bool) -> None:
    """
    Keep STDOUT clean: send Athena's console logs to STDERR and quiet them.

    core/logger.py attaches a stdout StreamHandler to the 'athena' logger at
    import time. For a CLI we want stdout to carry only the answer, so we
    redirect that handler to stderr and lower the level. The FileHandler
    (logs/app.log) is left untouched. This mutates only the in-process logger;
    core/logger.py source is unchanged.
    """
    import logging

    level = logging.INFO if verbose else logging.WARNING
    alog = logging.getLogger("athena")
    alog.setLevel(level)
    for handler in alog.handlers:
        # M26.6: retarget ONLY Athena's own stdout console handler (tagged in
        # core/logger.py with `_athena_console`). Never touch handlers a third
        # party attached to this shared, non-propagating logger — e.g. pytest's
        # StringIO-backed log-capture handler, whose stream must not be clobbered
        # (doing so previously broke the whole CLI test suite).
        # Only StreamHandlers have a `.stream`; our tagged console handler is one
        # (the isinstance check both narrows the type and is correct defensively).
        if getattr(handler, "_athena_console", False) and isinstance(handler, logging.StreamHandler):
            handler.stream = sys.stderr
            handler.setLevel(level)


def _yn(value: object) -> str:
    return "yes" if value else "no"


def _print_providers(router) -> None:
    """Print a simple aligned table of provider availability to stdout."""
    rows = router.list_providers()
    print(f"{'PROVIDER':<14}{'ENABLED':<10}{'AVAILABLE':<12}{'COST':<8}TYPE")
    for r in rows:
        print(
            f"{str(r.get('name', '')):<14}"
            f"{_yn(r.get('enabled')):<10}"
            f"{_yn(r.get('available')):<12}"
            f"{str(r.get('cost_tier', '')):<8}"
            f"{r.get('type', '')}"
        )


def main(argv: list[str] | None = None) -> int:
    """
    Entry point for the one-shot CLI.

    Returns an integer exit code. Usage errors raise SystemExit(2) via argparse.
    """
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    argv = _normalize_argv(argv)

    # M29.6: `athena history …` is a true subcommand with its own arguments —
    # route it before the main parser (which would choke on its ids).
    if argv and argv[0] == "history":
        from cli.history_cmd import run_history  # noqa: PLC0415

        return run_history(argv[1:])

    args = parser.parse_args(argv)

    # M28.6: doctor runs before any profile/router init and exits with its code.
    if args.doctor:
        from cli.doctor import run_doctor  # noqa: PLC0415

        return run_doctor()

    # Usage validation that needs no Athena imports: the ask path requires a
    # prompt, but --list-providers does not. M29.2: a bare `athena` on an
    # interactive stdin drops into the REPL instead; scripts/pipes (non-TTY)
    # keep the exit-2 usage error so nothing can hang waiting for input.
    wants_repl = False
    if not args.list_providers and (args.prompt is None or not args.prompt.strip()):
        try:
            stdin_tty = sys.stdin.isatty()
        except Exception:  # noqa: BLE001 — odd stdin counts as non-interactive
            stdin_tty = False
        if stdin_tty:
            wants_repl = True
        else:
            parser.error("a prompt is required (or use --list-providers)")

    # Resolve the profile BEFORE importing Athena modules: get_settings() is
    # @lru_cache'd, so the override must be set first. M28.5: --profile sets
    # ATHENA_PROFILE_OVERRIDE (not ACTIVE_PROFILE) so the explicit flag beats
    # the runtime switch file config/active_profile.yaml too.
    if args.profile:
        os.environ["ATHENA_PROFILE_OVERRIDE"] = args.profile

    # Deferred imports so the env above is in effect and FastAPI is never loaded.
    try:
        from core.config import active_profile_dir, get_settings
        from core.loader import load_yaml
        from providers.router import ProviderRouter
    except Exception as exc:  # noqa: BLE001
        print(f"Error: failed to load Athena modules: {exc}", file=sys.stderr)
        return 1

    # Make sure the profile/env overrides take effect, then quiet logging.
    get_settings.cache_clear()
    _configure_cli_logging(args.verbose)

    # Stand up the same router the server uses.
    try:
        router = ProviderRouter()
    except Exception as exc:  # noqa: BLE001
        print(f"Error: provider router failed to initialise: {exc}", file=sys.stderr)
        return 1

    if args.list_providers:
        _print_providers(router)
        return 0

    # M26.8: validate --provider against the known provider names so a typo
    # fails loudly here instead of being silently ignored by the router (which
    # would just fall back to normal routing). --mode is already validated by
    # argparse choices. Validation is by name only — a known-but-disabled
    # provider still passes (that's a config state, not a typo).
    if args.provider:
        try:
            known = {r.get("name") for r in router.list_providers()}
        except Exception:  # noqa: BLE001 — never let validation crash the run
            known = set()
        if known and args.provider not in known:
            print(
                f"Error: unknown provider '{args.provider}'. "
                f"Available: {', '.join(sorted(n for n in known if n))}.",
                file=sys.stderr,
            )
            return 2

    # Load the active profile.
    profile_path = active_profile_dir() / "profile.yaml"
    profile_config = load_yaml(profile_path)
    if not profile_config:
        print(
            f"Error: profile not found or empty: {profile_path}",
            file=sys.stderr,
        )
        return 1

    # Apply per-run routing overrides onto the in-memory profile config only.
    routing = profile_config.setdefault("routing", {})
    if args.mode:
        routing["mode"] = args.mode
    if args.provider:
        routing["preferred_provider"] = args.provider

    # M29.2: bare interactive invocation → the multi-turn REPL (which reuses
    # this same stack: router, overrides, shared turn helpers, history).
    if wants_repl:
        from cli.repl import run_repl  # noqa: PLC0415

        return run_repl(router, profile_config, args)

    # One-shot: a single user turn, system prompt from the profile — assembled
    # via the shared turn helper (M29.0), one code path with /chat.
    from core.chat_turn import build_turn_messages, system_prompt_from  # noqa: PLC0415

    messages = build_turn_messages([], args.prompt)
    system_prompt = system_prompt_from(profile_config)

    from cli.status import (
        Spinner,
        build_cli_breakdown,
        build_cli_summary,
        build_cli_usage,
        live_status_text,
        stream_is_tty,
    )

    # In-flight feedback: a spinner on stderr while route() blocks. Disabled by
    # --quiet and automatically silent when stderr isn't a TTY. M27.0: the
    # router's on_attempt callback updates the label to the provider being tried
    # right now (e.g. "Trying claude/cli…"), so a fall-through is visible live.
    spinner = Spinner("Working…", enabled=not args.quiet)

    def _on_attempt(info: dict) -> None:
        spinner.set_text(live_status_text(info))

    spinner.start()
    try:
        response = router.route(
            messages, system_prompt, profile_config, on_attempt=_on_attempt
        )
    except Exception as exc:  # noqa: BLE001 — route() shouldn't raise, but be safe.
        spinner.stop()
        print(f"Error: provider call failed: {exc}", file=sys.stderr)
        return 1
    spinner.stop()

    if not response.success:
        message = response.error or response.content or "All providers failed."
        print(f"Error: {message}", file=sys.stderr)
        return 1

    # The answer — and only the answer — goes to stdout.
    print(response.content)

    # Status feedback (stderr only, never stdout). The friendly one-liner shows
    # on an interactive TTY or when explicitly asked via --diagnostics; the
    # expanded breakdown is --diagnostics-only. Both derive from the M22 trace
    # and are gracefully absent when diagnostics are disabled.
    if not args.quiet:
        diagnostics = (
            response.metadata.get("diagnostics")
            if isinstance(response.metadata, dict)
            else None
        )
        summary = build_cli_summary(diagnostics)
        if summary and (stream_is_tty(sys.stderr) or args.diagnostics):
            print(summary, file=sys.stderr)
            # Token usage for the selected provider (M27.1): shown alongside the
            # summary. "Tokens: unavailable" for CLI transports that can't report.
            usage_line = build_cli_usage(diagnostics)
            if usage_line:
                print(usage_line, file=sys.stderr)
        if args.diagnostics:
            breakdown = build_cli_breakdown(diagnostics)
            if breakdown:
                print(breakdown, file=sys.stderr)

    # Best-effort, non-fatal memory auto-extraction via the shared sync core
    # (M29.0) — identical semantics to the /chat handler. Manager construction
    # can itself fail; that too must never fail an answered prompt.
    if not args.no_memory:
        from core.chat_turn import extract_memory  # noqa: PLC0415

        try:
            from memory.manager import MemoryManager

            memory = MemoryManager(active_profile_dir(), profile_config)
        except Exception as exc:  # noqa: BLE001 — never fail an answered prompt.
            import logging

            logging.getLogger("athena").warning(
                "auto_extract setup failed (non-fatal): %s", exc
            )
            memory = None
        extract_memory(memory, args.prompt, response.content)

    return 0
