# docs/specs — milestone specs

The milestone loop (see `../../CLAUDE.md`) is: spec → approval → implement →
test → docs → stop. These files are the "spec" step, kept afterward as the
historical record of scope, measured counts, and self-review. `CHANGELOG.md`
is the source of truth for what actually shipped.

## Shipped

| Spec | Milestone | Shipped as |
|---|---|---|
| [M26.19-ruff-and-pinning.md](M26.19-ruff-and-pinning.md) | Ruff lint + pinned deps | 2.6.19 |
| [M26.20-ci-workflow.md](M26.20-ci-workflow.md) | CI gate (`task ci` + workflow) | no bump |
| [M26.21-mypy.md](M26.21-mypy.md) | mypy type gate (lenient) | 2.6.21 |
| [M26.22-js-test-harness.md](M26.22-js-test-harness.md) | jsdom frontend test harness | no bump |
| [M26.23-git-init.md](M26.23-git-init.md) | git init + first commit | no bump |
| [M26.24-coverage.md](M26.24-coverage.md) | Coverage measurement + floor | no bump |
| [M26.25-pip-audit.md](M26.25-pip-audit.md) | Dependency vuln scan + CVE fix | 2.6.25 |
| [M26.26-pre-commit.md](M26.26-pre-commit.md) | pre-commit hooks | no bump |
| [M26.27-platform-support-docs.md](M26.27-platform-support-docs.md) | Platform support matrix | no bump |
| [M26.28-pwa.md](M26.28-pwa.md) | Installable PWA | 2.6.28 |
| [M27-live-status-and-usage.md](M27-live-status-and-usage.md) | Live status (M27.0) + token usage (M27.1) | 2.7.0 / 2.7.1 |
| [M28-portable-profiles.md](M28-portable-profiles.md) | Portable Profiles export (M28.0) / import (M28.1) | 2.8.0 / 2.8.1 |
| [M28.2-claude-cli-usage.md](M28.2-claude-cli-usage.md) | Claude-CLI token usage (JSON envelope) | 2.8.2 |
| [M28.3-remote-access-doc.md](M28.3-remote-access-doc.md) | Remote-access how-to | no bump |
| [M28.4-mobile-ui-pass.md](M28.4-mobile-ui-pass.md) | Mobile-responsive UI pass | 2.8.4 |
| [M28.5-profile-switcher.md](M28.5-profile-switcher.md) | Runtime profile switcher | 2.8.5 |
| [M28.6-doctor.md](M28.6-doctor.md) | `athena doctor` preflight | 2.8.6 |
| [M29.0-chat-turn-helper.md](M29.0-chat-turn-helper.md) | Shared chat-turn helper | 2.9.0 |
| [M29.1-persistent-history.md](M29.1-persistent-history.md) | Persistent cross-session history | 2.9.1 |
| [M29.2-cli-repl.md](M29.2-cli-repl.md) | CLI REPL | 2.9.2 |
| [M29.3-file-uploads.md](M29.3-file-uploads.md) | Real file uploads | 2.9.3 |
| [M29.4-conversation-export.md](M29.4-conversation-export.md) | Conversation export | 2.9.4 |
| [M29.5-claude-model-attribution.md](M29.5-claude-model-attribution.md) | Claude model attribution | 2.9.5 |
| [M29.6-cli-history.md](M29.6-cli-history.md) | CLI history surfaces | 2.9.6 |
| [M29.7-pre-3.0-review.md](M29.7-pre-3.0-review.md) | Pre-3.0 review & docs sweep | no bump |
| [M29.8-review-remediation.md](M29.8-review-remediation.md) | Review remediation (8 findings) | 2.9.8 |
| [M29.9-remediation-review.md](M29.9-remediation-review.md) | Remediation diff-review (addendum) | no bump |
| [M30-streaming.md](M30-streaming.md) | Streaming (SSE) — the major release | **3.0.0** |
| [M30.1-taskfile-dx.md](M30.1-taskfile-dx.md) | Taskfile DX (install/update/doctor) | no bump |
| [M30.2-mypy-gate-fix.md](M30.2-mypy-gate-fix.md) | Green mypy gate + CalDAV ETag fix | 3.0.1 |
| [M30.3-neutral-cwd.md](M30.3-neutral-cwd.md) | Neutral cwd for CLI provider subprocesses | 3.0.2 |
| [M30.4-uploads-visibility.md](M30.4-uploads-visibility.md) | Uploads visibility + attach UX | 3.0.3 |
| [M30.5-attachment-inlining.md](M30.5-attachment-inlining.md) | Attachment content inlining | 3.0.4 |
| [M30.6-voice-controls.md](M30.6-voice-controls.md) | Voice output/input controls | 3.0.5 |

## Approved, pending implementation

*(none — 3.0.0 shipped; the next milestone starts from a fresh spec)*

Review reports live in [`../history/`](../history/) (REVIEW-2026-07,
REVIEW-3.0-2026-07). The review-cadence rule — when the next review is due —
is in `../../CLAUDE.md` under the milestone loop.
