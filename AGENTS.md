# MonitorHub — AI Agent Instructions

## Python environment (IMPORTANT)

- This project requires **Python 3.12** and uses the virtualenv at `.venv/`.
- **ALWAYS** run tests and scripts with the explicit interpreter path:
  `.venv/bin/python`
- **NEVER** use bare `python`, `python3`, or `pip` — the system `PATH` may
  resolve to a pyenv/shim interpreter (e.g. Python 3.9) that does not support
  the `X | None` union syntax used throughout this codebase, causing
  `TypeError: unsupported operand type(s) for |`.
- Prefer the Makefile targets, which hardcode the interpreter:
  - `make test-unit` — run the full unit test suite (integration tests are skipped)
  - `make test-integration` — run rclone/s3 integration tests (needs credentials in `testdata/.env`)
  - `make test-command-action-handler` — run CommandActionHandler tests
  - `make check-env` — verify the .venv interpreter
- For ad-hoc checks, use the explicit path, e.g.:
  `.venv/bin/python -c "..."` or `.venv/bin/python -m unittest tests.test_x`
- Before running tests, confirm the environment with `make check-env` if the
  interpreter has not been verified in the current session.

## Testing

- Unit tests live in `tests/` and use `unittest` (pattern `test_*.py`).
- Integration tests (e.g. `tests/test_rclone_handler_integration.py`,
  `tests/test_s3_handler_integration.py`) require external services or
  credentials. They self-skip under `make test-unit`; run them explicitly
  with `make test-integration`. `tests/interactive_test_*.py` scripts are
  interactive/manual and are never picked up by unittest discovery.
- After modifying code, run the relevant unit tests via `make test-unit` or
  the targeted make target, and confirm they pass before declaring done.

## Git commits

- After completing a coherent unit of work (a feature, bugfix, refactor, or doc
  update) and confirming the relevant tests pass, create a commit.
- Commit messages: imperative mood, one line, matching the existing log style
  (e.g. "Add X", "Fix Y", "Remove Z"); add a body only when extra context helps.
- Do NOT commit when:
  - the working tree is clean,
  - tests failed or were not run,
  - the changes are experimental, incomplete, or mid-task,
  - the tree contains unrelated or stale WIP that belongs to a different task
    or session.
- Never commit credentials, secrets, or ignored files (e.g. `testdata/.env`).

## Project conventions

- Python 3.12 features are permitted (e.g. `X | None`, `match`, dataclasses).
- Follow PEP 8; prioritize readability.
- Keep the package layering: `app/utils` and `app/monitor` are the backend and
  must not import `app.cli` (the presentation layer). Interactive/reporting
  code belongs in `app/cli`. `tests/test_import_layering.py` enforces this.
- Do not modify files in `.venv/`, `.vscode/`, `data/`, or `build/`.
