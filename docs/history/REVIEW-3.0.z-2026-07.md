# REVIEW-3.0.z — scoped review of the post-3.0 stabilization wave (M30.10)

**Scope:** the nine unreviewed milestones M30.1–M30.9 (commits `41d5ffb` →
`7f946da`, 3.0.0 → 3.0.8) — the cadence rule's ≥5-autonomous-milestones
trigger, run before the M31 Voice epic opens. Method: fresh adversarial read
of the FINAL state of every changed file (not the edit deltas), with special
attention to the three behavior changes that all touch the same chat path and
had never been examined together (M30.5 inlining, M30.7 tool restriction,
M30.9 temporal context), plus targeted live verification of the three
least-certain mechanisms (voice-prefs fallback state machine, claude stderr
composition under the denylist, absolute-path attachment references).

## Bucket: FIX

**None.** No confirmed defects found.

## Bucket: DEFER

**None new.** The wave's own Later items (provider toggles, failure cooldown,
include_usage probe, realtime-voice bridge) were filed as the milestones
shipped and remain the complete set.

## Bucket: BLESS — intended/accepted behavior, recorded with reasons

- **B1 — a stale tool-denylist annotates failure text.** Unknown names in
  `--disallowedTools` make the CLI print a warning to stderr; claude failures
  surface `stderr.strip()`, so IF a future CLI drops a tool name AND a call
  fails, the error message gains a "deny rule matches no known tool" prefix.
  Verified: all 11 current names are valid (no warnings today). Blessed as a
  self-healing hint — the noise literally tells the maintainer the list is
  stale (INVARIANTS already directs keeping it current).
- **B2 — continuous mic can deliver without an explicit stop.** Browsers may
  end a continuous recognition session on their own (network hiccup, engine
  timeout); `onend` then delivers the accumulated buffer as if the user had
  clicked stop. Blessed: "deliver everything that was heard" is the feature's
  intent; dropping the buffer would be worse.
- **B3 — voice-prefs storage state machine (verified correct).** Walked all
  three failure paths: `getItem` throws → memory-only defaults; `setItem`
  throws → the localStorage-merged prefs are carried INTO memory (no loss);
  corrupted stored JSON → defaults for the session. Once the memory fallback
  engages it wins for the session — acceptable for a per-browser accessibility
  pref.
- **B4 — `uploads/*` searches match at any depth under search roots.** The
  Files tab's second pattern rglobs, so a hypothetical `data/x/uploads/y`
  would also list. Harmless breadth; only `data/uploads/` exists in practice.
- **B5 — the `.speak &&` count-pinned test is deliberately brittle.** It
  fails when anyone adds a TTS call site without a pref gate. That is its
  job; noted so a future agent extends the count knowingly rather than
  deleting the assertion.

## Lens statements (checked, nothing found)

**Correctness** — inlining: cap counts successes only, the anchored regex
ignores mid-sentence mentions, greedy match handles `]` in filenames,
absolute paths resolve through the traversal guard (verified live:
non-allowlisted → byte-identical message); temporal context: guarded clock,
always-line contract consciously changes the hermes/gemini/grok CLI prompt
shape for empty-profile cases (spec'd in M30.9); ETag fix import order and
its regression pin verified. **Security** — the allowlist is the ONLY gate
for attachment reads (no parallel filesystem path); the denylist tightens
the claude agent; no new secret surfaces; inlined content goes to providers
only, never rendered (history keeps raw — XSS posture unchanged).
**Concurrency** — all new state is per-request (inlining), per-process-
cached (help probe), or per-browser (prefs); no shared-dict writes added.
**Cross-surface** — inlining + temporal ride the shared seam (web and CLI
identical); voice prefs are deliberately browser-local and documented as
such. **Cross-adapter** — neutral cwd applies to all five subprocess sites;
the tool denylist is claude-only because only claude's CLI is an agent
(gemini's flag surface unprobed — revisit only if agentic behavior is ever
observed there). **Test quality** — the wave added ~40 tests: real
generator/class fakes, SimpleNamespace SDK shapes, live-probed CLI behavior
(deny-rule warnings) encoded as comments; the jsdom harness gained panel
containers, unlocking panel-flow tests. **Agent ergonomics** — nine specs
filed, per-milestone CHANGELOG/INVARIANTS entries, both triage queues
narrated in CLAUDE.md; the finding→milestone→doc chain is followable end to
end.

Gate at review time: ruff clean, `mypy .` exit 0, **615 pytest / 35 vitest**,
version 3.0.8, working tree clean (user's own profile.yaml edit excepted).

**Verdict: the 3.0.z wave is sound. The road to M31 (3.1) is clear.**
