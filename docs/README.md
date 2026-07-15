# Athena docs — index

Which doc do you want?

## Getting started / using it

| Doc | Read it when you want to… |
|---|---|
| [../README.md](../README.md) | Understand what Athena is (start here) |
| [INSTALLATION.md](INSTALLATION.md) | Install and run it (local or Docker) + the `athena` CLI |
| [PLATFORMS.md](PLATFORMS.md) | Know which platforms are supported (Mac/Linux/Windows/container/mobile) + remote-access pattern |
| [CONFIGURATION.md](CONFIGURATION.md) | Configure providers, routing, profiles, allowlist, integrations |
| [VALIDATION.md](VALIDATION.md) | Quickly check a running instance is healthy |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Fix a common problem |

## Operating a deployment

| Doc | … |
|---|---|
| [HANDOFF.md](HANDOFF.md) | Orient as a new operator (a reading order) |
| [RUNBOOK.md](RUNBOOK.md) | Perform day-to-day operational tasks |
| [BACKUP.md](BACKUP.md) | Back up and restore |
| [SECURITY.md](SECURITY.md) | Understand what Athena protects and how |
| [TASKFILE.md](TASKFILE.md) | Use the `task` command wrappers |

## Understanding / contributing to the code

| Doc | … |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | See the component map and design decisions |
| [../CLAUDE.md](../CLAUDE.md) | Contribute (the milestone workflow, files to read first) — also `../AGENTS.md` |
| [INVARIANTS.md](INVARIANTS.md) | Know the "do not break these" mechanisms before editing a subsystem |
| [TESTING.md](TESTING.md) | Understand the test suite and coverage |
| [CI.md](CI.md) | Run the lint+suite gate (`task ci`) and activate GitHub CI |
| [specs/README.md](specs/README.md) | Read the approved-but-not-started milestone specs |
| [../CHANGELOG.md](../CHANGELOG.md) | See per-release history |
| [global-claude-template.md](global-claude-template.md) | Set up project-agnostic agent norms (`~/.claude/CLAUDE.md`) |
| [CI.md](CI.md) | Run the lint+type+test gate and activate GitHub CI |

## Version control

The project is a **local git repository** (M26.23). `.gitignore` keeps secrets
(`.env`), the virtualenv, `node_modules/`, and runtime data (`data/`, logs) out
of history. There is **no remote yet** — add one to activate CI ([CI.md](CI.md)).

## Archived

- [history/](history/) — superseded material kept for the record (e.g. the old
  milestone-by-milestone validation log, historical planning notes). Not part of
  the current doc set.

Interactive API reference: `/docs` (Swagger UI) on a running server.
