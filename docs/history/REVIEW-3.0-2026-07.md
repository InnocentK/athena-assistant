# REVIEW-3.0 — pre-3.0.0 fresh-eyes review (M29.7, 2026-07)

**Scope:** the fourteen fast-batch milestones M28.2–M29.6 (primary — full
read, six lenses) plus targeted spot-checks of the pre-batch feature code
M26.27–M28.1 (security + contract lenses). App at 2.9.6, 536 pytest /
22 vitest, all green at review time. Method per
`docs/specs/M29.7-pre-3.0-review.md`; every finding exits through one of
three buckets: **FIX** (→ M29.8 queue below), **DEFER** (→ CLAUDE.md
Later/unscheduled), **BLESS** (→ INVARIANTS/docs note that it's intended).

Findings are numbered F1–F15. F1–F3 were pre-identified in the spec and are
confirmed here; F4–F6 are new discoveries of this review.

> **Errata (same milestone, user-reviewed):** the initial dispositions of F8
> and F14 did not survive scrutiny of the bucket definitions — F8 moved
> BLESS→DEFER (its justification was cost-based, not design-intent), F14
> moved BLESS→FIX (the consistency lens had checked cross-*surface* but not
> cross-*adapter*: hermes already treats empty output as failure). The
> sections below reflect the corrected buckets; the lens-statement section
> records the miss.

---

## Bucket: FIX — proposed M29.8 queue (awaiting user approval)

**F1 — upload same-name overwrite race** (`app/routers/files.py`, M29.3).
`_unique_path()` checks existence, then the file is opened `"wb"` — two
concurrent same-name uploads can both pass the check; the second silently
overwrites the first, contradicting the endpoint's own "never overwrite"
contract. Single-user severity: low. Fix: open with `"xb"` (exclusive) and
retry through the suffix loop on `FileExistsError`. ~8 lines + test.

**F2 — orphan-user-turn semantics differ across surfaces** (M29.1/M29.2).
On a failed provider turn: the **web UI keeps** the user's question in
replayed context (pushed before the fetch), the **REPL drops it** (history
appended only after the success check), and **restore/`/resume` keep it**
(only failed *assistant* turns filtered). Three surfaces, two semantics.
M26.10's rule governs the *failure text*, not the question. Verdict: the
question should be **kept** everywhere — the user did ask it, and dropping
it makes a resumed REPL transcript differ from what the model saw live. Fix:
align the REPL (append the user turn before the success check). ~3 lines +
test asserting cross-surface parity.

**F4 — claude.py error-envelope ordering gap** (M28.2, found by fresh read).
`_parse_json_envelope` checks `isinstance(data.get("result"), str)` and
falls back to *raw-stdout-as-success* BEFORE examining `is_error`. An error
envelope whose `result` is null/absent (plausible for failure subtypes)
would therefore render the raw JSON blob as a *successful answer*. Fix:
evaluate `is_error` before the shape fallback; error text from `result` (if
str), else `subtype`, else a generic message. ~10 lines + envelope tests.

**F14 — empty output treated as success (claude), inconsistent with hermes**
(reclassified BLESS→FIX in errata). Claude exit-0/empty-stdout yields an
empty *successful* answer in both plain and JSON modes, while the hermes
adapter already treats empty output as a **failure** — and failure is the
better semantics: an empty answer is useless, and marking it failed lets the
router fall through to a provider that will actually answer. Fix folded into
the F4 edit (same function/file): empty content → provider failure ("Claude
CLI returned no output."), both modes, + tests. ~4 lines.

**F5 — profile-switch empty-window race** (`app/routers/core.py`, M28.5).
`_switch()` runs `main._profile_data.clear()` then `.update(data)` in a
worker thread while `/chat` handlers in other worker threads read the same
dict (by design, lock-free — the M26.5 note covers *reads*, not a
clear/update writer). Between the two calls a racing request can observe an
**empty** profile: default routing, `None` system prompt. Window is
microseconds and single-user severity is low, but it violates the
settings-edit principle that readers never see invalid state (PATCH /profile
only ever updates keys). Fix: update-then-prune (`update(new)` first, then
delete stale keys) — the dict is never empty and every intermediate state is
a superset/mix of two valid profiles. ~5 lines + a comment; a targeted test
pins the reorder.

**F6 — conversation-id regex duplicated** (M29.1). The pattern
`^[A-Za-z0-9_-]+$` exists independently in `history/manager.py::_ID_RE` and
inline in the `/chat` handler (`app/routers/core.py`). Drift here would let
the handler accept ids the store rejects (or vice versa). Fix: export a
`is_valid_conversation_id()` from `history.manager`; the handler imports it.
~4 lines.

**F7 — missing negative test: history never travels in portable bundles.**
True today *by construction* (export writestr's an explicit allowlist —
verified), but the striplist's most sensitive class (chat content) deserves
an explicit regression assertion like pending-review already has. 1 line in
`tests/test_portable.py`.

**F10 — claude.py docstring drift.** Module header cites a stale CLI URL and
predates M29.5 (model attribution undocumented). Cosmetic; fold the
docstring touch into M29.8 since it's a code file (the no-bump sweep edits
docs only).

**Proposed shape:** one micro-milestone **M29.8 — review remediation**
(→ 2.9.8): F1, F2, F4, F5, F6, F7, F10, F14. Each item is ≤10 lines with its own
test; they share one gate run and one commit. (Splitting per-subsystem à la
M26.5–M26.10 would be ceremony — combined diff is ~40 lines of code.)

## Bucket: DEFER — added to CLAUDE.md Later/unscheduled in this milestone

**F3 — same-second conversation-id ordering tie** (M29.1). Two conversations
created within one second sort by their random suffix in newest-first
listings. Consumers audited: web past-conversations list, `athena history`
list, `export --all` document order, REPL `/list` — all **display-class; no
code path makes a decision from ordering**. Fix would be sub-second id
stamps (id-format change) or last-activity mtime sort (semantics change) —
neither is warranted pre-3.0 for a cosmetic tie. Deferred with an actionable
Later/unscheduled entry (per the standing rule that deferrals are recorded
where agents look, not just in this report).

**F8 — cross-module test-helper imports** (reclassified BLESS→DEFER in
errata: the original justification — "churn without a defect" — was a cost
argument, which is DEFER logic, not a design-intent argument).
`test_history_cli.py` imports fakes from `tests.test_cli` /
`tests.test_repl`; the convention would be conftest.py or a helpers module,
and the coupling can break sibling suites on refactor. Deferred with
trigger: **consolidate the shared fakes when they next change or gain
another importer** (Later/unscheduled entry added; TESTING.md note keeps the
coupling discoverable meanwhile).

## Bucket: BLESS — intended behavior, recorded

**F11 — REPL `_on_attempt` closure-in-loop** (`noqa: B023`). The callback is
defined, bound, and *called* within the same loop iteration (spinner and
callback are recreated per turn) — the late-binding hazard B023 guards
against cannot occur. Blessed with the existing inline comment.

**F12 — Claude help-probe caching semantics.** The `--output-format` probe
runs on first completion (worst case +10s if `--help` hangs once) and caches
for the adapter's lifetime; a mid-process CLI upgrade isn't re-detected
until restart. Correct trade-off for a per-request subprocess adapter.

**F13 — ConversationStore lock pattern.** `list_conversations` holds the
lock only for the directory scan, then re-acquires per `read()` — no nested
acquisition, no deadlock; a file deleted mid-listing is skipped by the
per-file exception guard. Correct as designed.

## Lens statements (what was checked where nothing was found)

- **Security:** traversal guards re-verified at all three input surfaces
  (upload names: basename+charset rewrite before any path; conversation ids
  and profile names: regex before path build — no bypass found, incl. URL-
  encoded and backslash forms since sanitizers run server-side on the
  decoded value). Secret hygiene: doctor prints names only (test-pinned);
  leak-guard unchanged; the pinned real Claude envelope fixture contains no
  live secrets (session id + synthetic figures only). Destructive endpoints
  (history delete, profile activate, portable import) validate before any
  filesystem effect and are ops-audited. The `claude --help` probe carries
  full M26.8 subprocess hardening. Upload cap enforced during streamed write
  (partial removed). Unbounded history growth: plain JSONL, single-user —
  acceptable, retention noted as existing Later-list adjacent concern (not
  added; grow-forever was an explicit M29.1 decision).
- **Concurrency:** store lock discipline (F13), switch race (F5 — the one
  real finding), REPL single-thread assumptions hold, uploads race (F1).
  No other shared-state writers found in the batch code.
- **Cross-surface consistency:** the lens as originally run checked the
  three *surfaces* (web / one-shot / REPL) but not cross-*adapter*
  consistency — the F14 miss (hermes vs claude empty-output semantics) is
  the evidence, caught in the user's review of the dispositions. The cadence
  rule's lens list now names cross-adapter explicitly.
  stdout/stderr contract verified for every
  new command (`history` list/show/export → stdout; REPL prompts/status →
  stderr; doctor report → stdout by design). Success-only replay: F2. Usage
  and status lines render from the same builders on both CLI surfaces.
  Markdown renderer equality is test-pinned (HTTP == store).
- **Test quality:** new-module coverage 77–95%; repl.py's uncovered 23% is
  error/status branches (route-raise path, TTY-gated prints) — acceptable.
  No tautological tests found; the strongest suites (leak-guard, doctor
  secret-hygiene, envelope pinning) assert behavior, not implementation.
  Gap found: F7.
- **Agent ergonomics:** naming conventions hold (`history/manager.py` =
  stateful CRUD; new packages have owns/does-not-own `__init__` docstrings —
  verified for `history/`). INVARIANTS coverage for the batch is complete
  after this review's additions. Docs drift was extensive (13 unlisted
  specs, ARCHITECTURE tree missing every new module) — fixed in this
  milestone's sweep, and the CLAUDE.md ↔ ARCHITECTURE mirror invariant now
  names the spec index as a third sync point.
- **Spot-checks (pre-batch code):** portable export writes an explicit
  member allowlist — `history/` cannot travel (F7 adds the pin); the service
  worker intercepts only `/static/*` + navigations, so no new endpoint is
  ever cached; mobile CSS additions are media-query-scoped with no logic.

## Coverage decision

Measured source-only coverage: **76.86%** (floor 70, set when reality was
74). Floor raised to **74** in this milestone — same ~3-point headroom
philosophy as the original setting; the ratchet locks in the batch's tests
without making honest DAV-mock refactors trip CI.

## Process note

This review also codifies the standing **review-cadence rule** into
CLAUDE.md (full review before any major; scoped review at each epic close;
scoped review after any autonomous batch ≥5 milestones), so the next "1,500
lines in a night" run gets its fresh eyes without anyone asking.

---

## Addendum — M29.9 remediation diff-review (post-M29.8, commit 56204d0)

Scoped fresh-eyes review of the M29.8 diff (~45 code lines) before M30, per
the user-directed application of the cadence rule. Method: evidence pass on
the final committed state (each fix greppably present, its inverse absent) +
line-level scrutiny of the two subtle rewrites (claude parse, REPL flow)
against edge cases.

**Verified fix-by-fix:** F1 `"xb"` present, no `"wb"` in the write path,
mkdir-before-open, handle closed and partial removed on the 413 path, 409 on
suffix exhaustion raised before any handle exists. F2 user-append sits
before the route call; `build_turn_messages` receives pre-append history so
the turn is never doubled; `/new` and `/resume` interplay unchanged. F4/F14
order verified (`is_error` at the top of the dict branch; empty checked in
all three forms — plain, JSON `result`, empty stdout); non-dict JSON still
degrades to raw-as-answer. F5 zero `clear()` in the switch path; prune
iterates a key snapshot; the pre-validated non-empty `data` guarantees the
dict can never empty. F6 the id regex now exists in exactly one module. F7
seeds real chat content and asserts byte-absence, not just name-absence.

**New findings: none.** Two observations, both BLESS:

- **A1 — `is_error` strict-`True` check.** A truthy-but-not-`True`
  `is_error` (e.g. the string `"true"`) does not trigger the failure path
  and degrades to the answer. Consistent with the adapter's defensive
  posture (unknown envelope dialects must not destroy answers); blessed.
- **A2 — REPL exception-path parity.** When `route()` *raises* (as opposed
  to returning a failure), the user turn is also kept — matching the web
  UI's network-error path. The F2 parity therefore extends beyond the
  tested returned-failure case; blessed, noted here as checked.

Gate at review time: ruff + mypy clean, 544 pytest @74 floor, 22 vitest.
**Verdict: M29.8 faithful to its findings; the road to M30 is clear.**


## Addendum — M30 pre-release diff-review (streaming, pre-bump @2.9.8)

Scope: the pre-major review above could not cover code that did not yet
exist, so per the agreed M30 structure this addendum reviews **M30's own
diff** — providers/base.py, chatgpt.py, ollama.py, grok.py, gemini.py,
providers/router.py, app/routers/core.py, static/js/chat.js, cli/status.py,
cli/main.py, cli/repl.py, and the new/updated tests — through the same six
lenses, before the version bump. Method: fresh line-level read of the
assembled final files (not the edit deltas), adversarial walk of every
route_stream fallback/stop path, cross-surface trace of the failure story
(adapter → router event → SSE done frame → web/CLI rendering → history).

**Applied fixes (found by this pass, in-milestone):**

- **A3 — endpoint local shadowed the module's APIRouter.** `chat_stream`
  bound `router = main._router` while every other line of the file uses
  `router` for the APIRouter instance. Renamed to `provider_router`
  (agent-ergonomics: one name, one meaning per file).
- **A4 — adapter `complete_stream` signatures were unannotated.** Added the
  base-matching annotations; that turned mypy's eyes onto the generator
  bodies, which surfaced the SDK-overload looseness the buffered calls
  already carry as `type: ignore[arg-type]` — now carried on the stream
  call as `type: ignore[call-overload]` with a comment. Net: stream bodies
  are type-checked; buffered/stream looseness is symmetrical and explicit.
- **A5 — streaming timings were silently delivery-inclusive.** For a
  streaming attempt, `call_ms`/`duration_ms` span first-call→final-response
  and the router generator is suspended at each yielded chunk, so SSE write
  and client consumption time are included. That is the user-perceived
  answer time (right for the summary line) but not comparable to a buffered
  attempt's pure provider latency — now stated in route_stream's docstring
  rather than left for someone to discover in a latency investigation.

**Observations, blessed (intended behavior, recorded here):**

- **A6 — double `Spinner.stop()` on the CLI streaming path.**
  `drive_stream` stops the spinner at the first chunk; the caller stops it
  again after the iterator ends. The second stop re-writes `\r\033[K` to a
  then-empty stderr line — invisible on a TTY, absent when piped. Keeping
  the caller-side stop is what guarantees the spinner dies on the zero-chunk
  and exception paths; blessed as the simpler invariant ("caller always
  stops it; drive_stream additionally stops it early for display").
- **A7 — client disconnect abandons the turn.** On SSE disconnect the
  async generator is closed at its yield point: no assistant turn is
  recorded (the reply was never delivered), the user turn remains, and the
  orphaned worker-thread `next()` finishes into a dropped reference. Same
  dangling-user-turn shape as a /chat timeout; documented in the endpoint
  docstring. Untestable in TestClient without flaky thread choreography —
  accepted untested, behavior documented.
- **A8 — 400-then-fallback burns one request.** A stale/invalid
  `conversation_id` 400s on /chat/stream, and the UI's fallback re-posts to
  /chat, which 400s again and renders the detail. Two requests to surface
  one error is the cost of "fallback must be unconditional before first
  chunk" (the reliability invariant); blessed.
- **A9 — `extract_memory` runs on failed streams too** (content=""), exactly
  as /chat has always done; parity wins over cleverness.

**Lens statements (checked, nothing found):** correctness — every
route_stream exit yields exactly one done (all-fail, fallback-off, timeout,
contract-violation paths each traced; parity tests pin route() vs
route_stream()); security — no new secret paths, diagnostics stay
content-free (chunk text goes to the client that asked for it, never into
traces/logs), XSS posture unchanged (textContent everywhere, JSON.parse
guarded), subprocess hardening untouched; concurrency — per-request
generator state only, `_STREAM_DONE` sentinel keeps StopIteration out of
the coroutine machinery, deadline math is monotonic, no shared-dict writes
beyond the already-guarded diagnostics store; cross-surface — web/CLI/HTTP
all consume the same route_stream events, both surfaces reconcile to the
done response as authoritative, failure-after-chunks renders partial text +
error on web and partial stdout + stderr error + exit 1 on CLI (documented
under --no-stream for strict scripts); cross-adapter — empty output is now
a failure on EVERY adapter in BOTH modes (chatgpt/ollama/grok-api/grok-cli/
gemini added this milestone; hermes always, claude since M29.8), grok
streams only on its api transport and says so via supports_streaming();
test quality — 49 new tests use real generator fakes (not MagicMock
auto-attrs) and SimpleNamespace SDK chunks so the defensive getattr walks
are honestly exercised; split-frame SSE parse, zero-chunk vs after-chunk
fallback, timeout, and 400 paths all pinned.

Gate at addendum time (pre-bump, 2.9.8): ruff clean; mypy at the 8-error
pre-existing caldav/ics-stub baseline (M26.21); **593 pytest** green,
coverage 77% (floor 74); **28 vitest** green.
**Verdict: M30's diff is fit to become 3.0.0.**


## Erratum — gate lines overstated mypy (found M30.2, 2026-07-16)

Several gate statements in this report and in milestone logs ("ruff + mypy
clean") were verified through a shell pipe (`mypy . | tail …`), which reports
the PIPE's exit status, not mypy's. In any environment with the pinned caldav
3.x actually installed, `mypy .` exited 1 throughout with 8
`"object" not callable`-family errors (caldav's py.typed PEP 562 lazy loader
types module attrs as `object`). The test/lint/coverage figures in those gate
lines are unaffected (verified by their own exit codes); only the mypy claims
were wrong. Fixed in M30.2 (→ 3.0.1): 7 precise per-line ignores + 1 REAL bug
fix the type errors were pointing at (`caldav.dav` does not exist in caldav
3.x — the ETag fetch had silently recorded `""` since the caldav 3 pin), plus
an INVARIANTS rule: the type gate is `mypy .`'s exit code, never assessed
through a pipe. Post-fix: `mypy .` exits 0 — "no issues found in 69 source
files".
