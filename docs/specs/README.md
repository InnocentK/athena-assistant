# docs/specs — milestone specs

The milestone loop (see `../../CLAUDE.md`) is: spec → approval → implement →
test → docs → stop. These files are the "spec" step.

## Shipped (M26.19–M26.22 — the tooling batch)

All four are **implemented and released**; kept here as the historical record of
scope, measured counts, and self-review. `CHANGELOG.md` is the source of truth.

| Spec | Milestone | Shipped as |
|---|---|---|
| [M26.19-ruff-and-pinning.md](M26.19-ruff-and-pinning.md) | Ruff lint + pinned deps | 2.6.19 |
| [M26.20-ci-workflow.md](M26.20-ci-workflow.md) | CI gate (`task ci` + workflow) | no bump (docs/tooling) |
| [M26.21-mypy.md](M26.21-mypy.md) | mypy type gate (lenient) | 2.6.21 |
| [M26.22-js-test-harness.md](M26.22-js-test-harness.md) | jsdom frontend test harness | no bump (test infra) |

## Specced, awaiting go-ahead (M26.23–M26.26 — foundations batch)

Full specs written; **not yet implemented**. Recommended order below (M26.26
depends on M26.23; the others are independent).

| Spec | Milestone | Notes |
|---|---|---|
| [M26.23-git-init.md](M26.23-git-init.md) | git init + first commit | **Needs user input** (identity, remote). Foundational — unblocks CI + M26.26. |
| [M26.24-coverage.md](M26.24-coverage.md) | Coverage measurement | `pytest-cov` + floor; source-only baseline ~80% (86% incl. tests). |
| [M26.25-pip-audit.md](M26.25-pip-audit.md) | Dependency vuln scan + fix | Measured: **4 CVEs in `python-multipart` 0.0.26 → bump 0.0.31**. Version bump. |
| [M26.26-pre-commit.md](M26.26-pre-commit.md) | pre-commit hooks | **Depends on M26.23.** ruff+mypy+hygiene at commit time. |

## Specced, awaiting go-ahead (M26.27 + the feature epics)

Full specs written; **not yet implemented** (M26.27 is being implemented now).

| Spec | Milestone | Notes |
|---|---|---|
| [M26.27-platform-support-docs.md](M26.27-platform-support-docs.md) | Platform support & limitations docs | **Docs only, no bump.** Support matrix (Mac tested / Linux expected / Windows caveats / container API-only / mobile via VPN). Do first — the LXC script + remote-access docs point at it. |
| [M27-live-status-and-usage.md](M27-live-status-and-usage.md) | Live status & usage telemetry (epic) | **M27.0** live status core → 2.7.0; **M27.1** token/context usage on UI+CLI → 2.7.1. Renamed from "Advanced CLI live status" so the cross-surface token work isn't buried under a CLI-only title. |
| [M28-portable-profiles.md](M28-portable-profiles.md) | Portable Profiles (epic) | **M28.0** export → 2.8.0; **M28.1** import → 2.8.1. Snapshot (not sync) host-agnostic, secret-free identity bundle; allowlist-built + leak-guarded. Builds on the backup subsystem. |
