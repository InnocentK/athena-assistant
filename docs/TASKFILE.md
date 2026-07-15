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
| `task setup` | First-time setup: create venv, install deps, copy `.env.example` |
| `task install` | Install / update Python dependencies (venv must be active) |

### Local development

| Task | Description |
|------|-------------|
| `task run` | Start dev server with auto-reload on port 8000 |
| `task run PORT=9000` | Start dev server on a custom port |
| `task run:prod` | Start server without auto-reload, single worker |
| `task health` | Curl `/health` and pretty-print the response |

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
| `requirements.txt` | Dependency list; `task install` installs from it |

## File structure

```
athena-assistant/
├── Taskfile.yml          # Root — project-wide tasks, imports tests/Taskfile.yml
└── tests/
    └── Taskfile.yml      # Test namespace (test:run, test:verbose, test:file, test:clean)
```

The root Taskfile includes `tests/Taskfile.yml` under the `test:` namespace. All test tasks are invoked as `task test:<name>` from the project root.

## Notes

- `task setup` and `task clean` use shell commands and are Linux/macOS only. On Windows, use `run.bat` for setup and delete artifacts manually.
- The `PORT` variable can be overridden: `task run PORT=9000`.
- `task test:file` requires the `FILE` variable: `task test:file FILE=tests/test_config.py`.
