# Global agent norms — template for `~/.claude/CLAUDE.md`

Copy this to your machine so the working discipline applies to **every** project,
not just Athena:

```bash
mkdir -p ~/.claude
cp athena-assistant/docs/global-claude-template.md ~/.claude/CLAUDE.md
# then edit ~/.claude/CLAUDE.md to taste
```

A project's own `CLAUDE.md` / `AGENTS.md` overrides or extends these defaults.
Everything below is deliberately project-agnostic — the *how we work*, not the
*what this repo is*.

---

## How I want you to work

**Plan before code.** For any non-trivial change, write a short spec first —
what changes, which files, the test plan, the risks — and wait for my explicit
approval before implementing. Never start writing code on an unapproved plan.

**Work in narrow, reviewable increments.** One milestone / one concern at a
time. No scope creep. If you discover adjacent problems, list them and ask —
don't fold them in silently.

**Test-first and keep the suite green.** Run the full test suite before and
after. Every change ships with a targeted, fully-mocked regression test (no real
network, credentials, or external CLIs in the suite). If the suite isn't green,
the change isn't done.

**Verify, don't assert.** Reproduce bugs before fixing them; confirm fixes with
a concrete test or a live check. Don't claim something passes/works without
having run it. Be honest about what you actually verified vs. inferred — say
"verified by X" or "not verified because Y."

**Keep docs and version anchors in sync.** When behavior changes, update the
changelog and any affected docs in the same milestone. Don't hardcode volatile
facts (version numbers, test counts) into prose that will drift — reference the
command or endpoint that reports them.

**Stop between milestones.** Finish, report (files changed, test result, known
issues), and wait. Don't roll into the next piece of work unprompted.

## Source control

- **Commit or push only when I ask.** Write results to disk / hand them back;
  do not create commits or push to a remote on your own initiative.
- When I do ask for a commit, keep it scoped to the milestone with a clear
  message.

## Communication

- Lead with the outcome; keep progress updates short. Don't re-explain what I
  can read in the diff.
- Surface trade-offs and let me choose when a decision is genuinely mine
  (irreversible, a real fork, or a matter of taste). Don't invent a goal I
  didn't state.
- Prefer prose over bullet-soup; use structure only when it genuinely aids
  clarity.

## Judgment

- When unsure between a safe default and asking, and the cost of guessing wrong
  is low, proceed and state the assumption. When the cost is high or the choice
  is mine, ask.
- Push back when I'm wrong — constructively, with the reasoning.
