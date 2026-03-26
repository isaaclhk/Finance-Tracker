# Finance tracker — Development Instructions

## Development Workflow

### Committing

After completing each logical unit of work, automatically stage and commit. Don't batch unrelated changes — keep commits atomic, as a human developer would.

**Before every commit, run these checks on changed files:**

1. `.venv/bin/ruff check worker/` — lint
2. `.venv/bin/ruff format --check worker/` — format check
3. `.venv/bin/python -m pytest tests/ -q` — tests

If any check fails, fix the issues first, re-run checks, then commit.

**Commit message format:** Use conventional commits via commitizen:
- `feat:` — new feature
- `fix:` — bug fix
- `refactor:` — code restructuring with no behavior change
- `docs:` — documentation only
- `test:` — adding or updating tests
- `chore:` — build, config, tooling changes

**Do NOT add a `Co-Authored-By` line.** Commits should be authored by the user only.

**Never commit directly to `main`.** Never create new branches — always commit to the current branch.

### Tools & Environment

- **Python packages:** Use `uv` — never `pip install`. Dependencies are already in `.venv`. To add a package: `uv add <package>`. To run: `uv run <command>` or `.venv/bin/python`.
- Worker dev server: `uv run uvicorn worker.main:app --reload`
- Linting: `ruff` (config in `pyproject.toml`)
- Tests: `.venv/bin/python -m pytest tests/ -q`
- Deployment: `docker compose up --build` (Firefly III + worker + Caddy)
