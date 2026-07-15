# Continuous Integration

Athena has a CI gate (M26.20, extended in M26.21): **lint + type-check + the
full test suite**, run on every push and pull request. It needs **no secrets** —
the suite is fully mocked (the M26.17 conftest fixture guarantees no real
provider CLI or network call runs), so it is safe on public repos and forks.

## Run the gate locally (works today, no remote needed)

```bash
task ci        # ruff check  →  mypy .  →  pip install -e .  →  pytest -q
```

This is the exact sequence CI runs. Use it before pushing (or as a future agent's
one-command "is this branch shippable?" check). The SessionStart hook already
runs lint + types + suite at session start; `task ci` adds the packaging step.

## The workflow

`.github/workflows/ci.yml` runs the gate on GitHub Actions across Python **3.10**
(the floor, per `pyproject.toml` `requires-python`) and **3.11** (the version
tested locally). Steps: checkout → set up Python (with pip cache) →
`pip install -r requirements.txt` → `pip install -e .` (this also proves the
packaging path — the console script and the `app`/`app.routers` packages added in
M26.18) → `ruff check .` → `mypy .` → `pytest -q`.

## Activating it

The project **is now a local git repository** (M26.23 — `git init` done, first
commit at 2.6.21). The workflow stays inert only until you add a **GitHub
remote**:

```bash
cd athena-assistant
# create an empty repo on GitHub and push (e.g. with the gh CLI):
gh repo create athena-assistant --private --source=. --remote=origin
git push -u origin main
```

On the first push, GitHub Actions picks up `.github/workflows/ci.yml`
automatically — no extra configuration. Add a status badge to `README.md` once
the repo URL exists:

```markdown
![CI](https://github.com/<you>/athena-assistant/actions/workflows/ci.yml/badge.svg)
```

## Not in scope (possible future work)

Coverage gates, release automation, and deploy pipelines. Windows/macOS runners aren't included — the
app targets Linux/Docker.
