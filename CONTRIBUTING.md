# Contributing to fritzmoles-mcp

Thank you for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/the78mole/fritzmoles-mcp.git
cd fritzmoles-mcp
uv sync --extra dev
pre-commit install
```

`uv.lock` is authoritative: CI installs it with `uv sync --locked`, which fails
if the lockfile has drifted from `pyproject.toml`. After changing a dependency,
run `uv lock` and commit the result.

## Running the Server Locally

```bash
cp .env.example .env   # fill in FRITZ_USERNAME / FRITZ_PASSWORD
uv run fritzmoles-mcp
```

Test interactively with the MCP Inspector:

```bash
uv run mcp dev src/fritzmoles_mcp/server.py
```

## Tests

```bash
uv run pytest
```

The suite runs without a FRITZ!Box: `tests/conftest.py` provides a fake TR-064
connection and a fake URL fetcher, and `tests/fixtures/` holds XML samples taken
from AVM's TR-064 specifications. When you add a tool, add the matching
`(service, action)` response to the fake and a dispatch test through
`server.mcp.call_tool(...)`. Coverage must stay at or above 80 %.

## Code Style

[ruff](https://docs.astral.sh/ruff/) for formatting and linting (also run by pre-commit):

```bash
uv run ruff format .
uv run ruff check --fix .
```

## Commit Messages

Commits on `main` drive automatic versioning via
[paulhatch/semantic-version](https://github.com/paulhatch/semantic-version)
with `bump_each_commit` enabled - **every push to `main` creates a release and
publishes to PyPI**. Use [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix | Effect |
|--------|--------|
| `fix: …`, `chore: …`, `docs: …`, `test: …` | patch bump (0.0.**x**) |
| `feat: …` | minor bump (0.**x**.0) |
| `feat!: …` / `fix!: …` / `refactor!: …` | major bump (**x**.0.0) |

## Pull Requests

1. Fork the repository and create a feature branch.
2. Keep changes focused - one topic per PR.
3. Add or update tests for new behaviour.
4. Ensure `ruff format`, `ruff check` and `pytest` are clean.
5. Open the PR against `main` and describe what changed and why.

## Reporting Issues

Please open a [GitHub Issue](https://github.com/the78mole/fritzmoles-mcp/issues)
and include a short description, steps to reproduce, expected vs. actual
behaviour, your FRITZ!OS version and `python --version` / `uv --version`.

## License

By contributing you agree that your work will be released under the
[MIT License](LICENSE) of this project.
