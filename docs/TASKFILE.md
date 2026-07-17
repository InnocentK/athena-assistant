# Athena Assistant — Taskfile Guide

[Taskfile](https://taskfile.dev) is an optional task runner that wraps common developer and operator commands. It is NOT required to run Athena — `run.sh` (macOS/Linux) and `run.bat` (Windows) remain the zero-dependency options.

## Installation

Install the `task` CLI: https://taskfile.dev/installation/

Quick install (Linux/macOS):
```bash
sh -c "$(curl --location https://taskfile.dev/install.sh)" -- -d -b ~/.local/bin
```

Verify:
```bash
task --version
```

## Discovering tasks

```bash
task --list          # all tasks with descriptions
task --list-all      # including internal/hidden tasks
```

## Available tasks

### Setup and dependencies

| Task | Description |
|------|-------------|
| `task setup` | First-time setup: venv, deps, the `athena` command (editable install), `.env` from the example |
| `task install` | Make the venv current: deps **and** the `athena` command — run after pulling changes (M30.1) |
| `task update` | Post-pull one-shot: `install` + `npm install` when npm is present (skipped with a notice otherwise) + prints the installed version (M30.1) |
| `task doctor` | Athena preflight checks — config/filesystem only, no network (M28.6); exits 1 if a check fails |

Why `install` runs `pip install -e .`: the editable install is what provides
the `athena` console command AND the mapping of Athena's own packages, and
that mapping is a snapshot from install time. A venv installed before a
milestone that added a top-level package fails with
`No module named '<pkg>'` until it is re-run — `task install` makes that
impossible to forget (see TROUBLESHOOTING.md, which documents the real
incident).

### Quality gates (M26.19–M26.26)

| Task | Description |
|------|-------------|
| `task lint` | Ruff lint check (correctness gate; config in `pyproject.toml [tool.ruff]`) |
| `task lint:fix` | Auto-fix the safely fixable ruff violations |
| `task typecheck` | mypy (lenient type gate; config in `pyproject.toml [tool.mypy]`) |
| `task audit` | pip-audit over the pinned requirements (known-CVE scan) |
| `task coverage` | Suite with coverage + missing-line report (floor in `pyproject [tool.coverage]`) |
| `task coverage:html` | Coverage as a browsable HTML report in `htmlcov/` |
| `task hooks:install` | Install the git pre-commit hooks (once per clone) |
| `task hooks:run` | Run all pre-commit hooks against every file |
| `task ci` | The full CI gate locally: lint + typecheck + audit + editable install + suite w/ coverage |
| `task test:js` | Frontend (jsdom) tests for `static/js/*` — needs Node (`npm install` first) |

### Local development

| Task | Description |
|------|-------------|
| `task run` | Start dev server with auto-reload on port 8000 |
| `task run PORT=9000` | Start dev server on a custom port |
| `task run:prod` | Start server without auto-reload, single worker |

### Docker

| Task | Description |
|------|-------------|
| `task up` | Build image and start Docker stack (detached) |
| `task down` | Stop and remove containers |
| `task build` | Build Docker image without starting |
| `task logs` | Follow container logs (`docker compose logs -f athena`) |

### Tests

| Task | Description |
|------|-------------|
| `task test:run` | Run the full pytest suite |
| `task test:verbose` | Run tests with full output (`--tb=long`) |
| `task test:file FILE=tests/test_foo.py` | Run a single test file |
| `task test:clean` | Remove `.pytest_cache`, `.coverage`, `htmlcov` |

### Operations (requires a running server)

| Task | Description |
|------|-------------|
| `task health` | Curl `/health` and pretty-print the response |
| `task backup` | Create a backup export via the API |
| `task backup:list` | List available backup exports |
| `task restore:diff ZIP=<filename>` | Dry-run diff for a backup zip |
| `task ops:audit` | Tail today's ops audit log |

### Cleanup

| Task | Description |
|------|-------------|
| `task clean` | Remove `__pycache__`, `*.pyc`, `*.pyo` (excludes `.venv`) |

## Relationship to existing tooling

Taskfile **orchestrates** existing commands — it does not replace anything:

| Tool | Role |
|------|------|
| `run.sh` / `run.bat` | Zero-dependency start scripts; still the primary option on Windows and environments without `task` |
| `docker-compose.yml` | Defines the full container stack; `task up/down/build/logs` wrap it |
| `Dockerfile` | Unchanged; Taskfile does not modify the image build |
| `pytest` | Test runner; `task test:*` are convenience wrappers |
| `requirements.txt` | Dependency list; `task install` installs from it (plus the editable self-install) |

## File structure

```
athena-assistant/
├── Taskfile.yml          # Root — project-wide tasks, imports tests/Taskfile.yml
└── tests/
    └── Taskfile.yml      # Test namespace (test:run, test:verbose, test:file, test:clean)
```

The root Taskfile includes `tests/Taskfile.yml` under the `test:` namespace. All test tasks are invoked as `task test:<name>` from the project root.

## Notes

- `task setup`, `task update`, and `task clean` use shell commands and are Linux/macOS only. On Windows, use `run.bat` for setup (then `pip install -e .` manually) and delete artifacts manually.
- The `PORT` variable can be overridden: `task run PORT=9000`.
- `task test:file` requires the `FILE` variable: `task test:file FILE=tests/test_config.py`.
