# M27 — Live status & usage telemetry — SPEC (epic: M27.0, M27.1)

**Status: specced, awaiting go-ahead. Do NOT implement without explicit
approval. Two sub-milestones, shipped back-to-back and independently testable.**

## Naming note

The roadmap previously called this **"M27 — Advanced CLI live status."** That
title was CLI-only and would have buried genuinely cross-surface work (token/
context usage lands in *both* the browser UI and the CLI) under a CLI heading —
a trap for a future agent ("why is there UI code in a CLI milestone?"). The epic
is therefore renamed **"Live status & usage telemetry"** to tell the truth about
its scope. It splits into:

- **M27.0 — Live status core** (the original "advanced CLI live status" work).
- **M27.1 — Token / context usage surfaces** (UI + CLI, off the shared trace).

Version mapping follows the established convention (milestone number == version
when it bumps): **M27.0 → 2.7.0**, **M27.1 → 2.7.1**. This is cleaner than the
M26.z era's `N → 2.6.N` mapping — it's just plain semver (minor 7, patch 0/1).

## Why (shared context)

Diagnostics (M22) already measure every provider call content-free
(`diagnostics/store.py`: `ProviderCallRecord` / `RequestTrace` — provider,
transport, model, timing, outcome; **no content**). That measure-only ledger was
deliberately built *before* the UI/CLI status surfaces (M24/M25) so those
surfaces render real data rather than guesses. Both sub-milestones here are
**additional surfaces + one additive field on that same trace** — no new
subsystem, in keeping with "measure first, then surface."

---

## M27.0 — Live status core  (→ 2.7.0)

### Goal
A richer **live CLI status line** during a request: current provider/model, the
transport (API vs CLI), elapsed time, and lightweight state ("routing →
calling <model> → 3.4s"), inspired by tools like Hermes. Additive; **not** a TUI
rewrite and **not** streaming.

### Scope
1. Extend the CLI status surface (`cli/status.py`) to render a live,
   progressively-updated status line to **stderr** (so piped stdout stays clean
   — preserve the M25 stdout/stderr split; INVARIANTS "CLI logging").
2. Drive it from the existing diagnostics trace / router lifecycle — reuse the
   provider/model/transport/timing already captured; do not introduce a parallel
   timing path.
3. Respect non-interactive contexts: when stderr isn't a TTY (pipes, CI, the
   test suite), degrade to the current quiet/one-shot behaviour — no ANSI spam in
   logs. Gate the live redraw on `isatty`.
4. Keep it dependency-light (no heavyweight TUI lib; simple carriage-return
   redraw or an already-present dep). Guardrail: "no heavyweight dependencies
   without a good reason."
5. Tests: fully mocked (no real CLIs/keys/network). Assert the TTY path emits the
   expected fields and the non-TTY path stays quiet. Add the "status line goes to
   stderr, never stdout" assertion to the regression set.

### Version: **2.7.0** (user-visible CLI feature). CHANGELOG + INVARIANTS
(reaffirm the stdout/stderr contract) + `docs/TESTING.md`.

---

## M27.1 — Token / context usage surfaces  (→ 2.7.1)

### Goal
Show **token / context usage** of the current model both in the **Athena web UI**
and in **athena-cli** responses — built together off the shared trace so the two
surfaces stay consistent.

### Scope
1. **Additive trace field.** Add an optional `usage` field (e.g. prompt /
   completion / total tokens, and context-window size where known) to the
   diagnostics record. It is **metadata, not content** — this stays within the
   "diagnostics are content-free" invariant (token *counts* are fine; token
   *text* is not). Field is optional and defaults to "unknown".
2. **Best-effort capture per transport** (graceful degradation is a first-class
   requirement, not an afterthought):
   - **API transports** (chatgpt / grok-api / ollama via the OpenAI SDK):
     responses carry a `usage` object — read it directly. Reliable.
   - **Claude CLI**: obtain usage via `--output-format json` where the installed
     CLI supports it; parse defensively.
   - **Other CLI adapters** (gemini / grok / hermes): usage often unavailable —
     capture if the CLI surfaces it, else record "unavailable."
   - **Never fabricate or estimate** counts. Unknown renders as an explicit
     "unavailable," not a guessed number.
3. **UI surface.** Show current-model token/context usage in the chat UI
   (e.g. a small status element: "1,204 / 200k tokens" or "usage unavailable").
   Frontend change lives in `static/js/*` with a jsdom test (M26.22 harness).
4. **CLI surface.** Append a usage line to `athena-cli` responses — on **stderr**
   (metadata, keep stdout = answer only, per M27.0 / M25). "unavailable" when the
   transport can't report it.
5. **Tests:** mocked provider responses with and without `usage`; assert the
   field flows to both surfaces and that the missing-usage path renders
   "unavailable" cleanly on both. jsdom test for the UI element.

### Version: **2.7.1** (user-visible UI + CLI feature). CHANGELOG + `docs/TESTING.md`
+ INVARIANTS note ("diagnostics stay content-free; token *counts* are metadata
and permitted, token *text* is not").

---

## Self-review notes (epic-wide)

- **Do M27.0 then M27.1**, back-to-back. M27.1's UI/CLI usage line naturally
  lives *in* the status surface M27.0 builds, so ordering them this way avoids
  reworking the CLI output twice.
- **The trace is the single source.** Both surfaces read the same record; never
  compute usage or timing twice. This is the reason M22 exists.
- **Graceful "unavailable" is the correctness bar.** The feature must be honest
  across a fleet of providers with wildly different introspection — a wrong
  number is worse than an honest blank.
- **stdout stays the answer.** Every status/usage byte goes to stderr; the M25
  contract is load-bearing for CLI piping and must not regress.

## Out of scope
- True per-provider streaming (SSE/WebSocket) — still "later/unscheduled."
- Cost/pricing estimation from token counts (pricing is provider- and
  time-dependent; out of scope).
- Cross-session usage aggregation / history persistence.
