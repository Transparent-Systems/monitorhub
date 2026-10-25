# MonitorHub Makefile
# Ensures the project virtualenv (.venv) is always used for tests and scripts.
# Agents and developers should use these targets instead of invoking bare
# `python` or `python3`, which may resolve to a system/pyenv interpreter.

PYTHON := .venv/bin/python
UNITTEST := $(PYTHON) -m unittest
RUFF := $(PYTHON) -m ruff

.PHONY: help check-env check-actions test test-unit test-integration test-command-action-handler test-commands update-diagrams update-diagram-actionhandler update-diagram-commands docs-install docs-build docs-serve lint lint-fix clean

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-28s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

check-env: ## Verify the .venv interpreter is available and print its version
	@test -x $(PYTHON) || { \
		echo "ERROR: $(PYTHON) not found. Create the virtualenv first:"; \
		echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"; \
		exit 1; }
	@$(PYTHON) -c "import sys; print(f'Using {sys.executable} ({sys.version.split()[0]})')"

check-actions: check-env ## Report the Node runtime every workflow action declares
	$(PYTHON) utils/check_actions.py

test: test-unit ## Run all unit tests

test-unit: check-env ## Run the full unit test suite
	$(UNITTEST) discover -s tests -p "test_*.py" -v

test-integration: check-env ## Run integration tests (needs credentials in testdata/.env)
	$(PYTHON) -m tests.test_rclone_handler_integration
	$(PYTHON) -m tests.test_s3_handler_integration

test-command-action-handler: check-env ## Run CommandActionHandler unit tests only
	$(UNITTEST) tests.test_command_action_handler -v

test-commands: check-env ## Run Commands unit tests only
	$(UNITTEST) tests.test_commands -v

update-diagrams: check-env ## Regenerate both class diagrams in ARCHITECTURE.md
	$(PYTHON) utils/update_diagram.py actionhandler
	$(PYTHON) utils/update_diagram.py commands

update-diagram-actionhandler: check-env ## Regenerate the ActionHandler class diagram
	$(PYTHON) utils/update_diagram.py actionhandler

update-diagram-commands: check-env ## Regenerate the Commands class diagram
	$(PYTHON) utils/update_diagram.py commands

# Documentation: source in docs/, published to GitHub Pages by
# .github/workflows/docs.yml. docs-build runs strict, so a broken internal link
# fails here exactly as it does in CI.
docs-install: check-env ## Install the documentation dependencies into .venv
	$(PYTHON) -m pip install -r requirements-docs.txt

docs-build: check-env ## Build the documentation (strict: broken links fail)
	$(PYTHON) -m mkdocs build --strict

docs-serve: check-env ## Serve the documentation locally on http://127.0.0.1:8000
	$(PYTHON) -m mkdocs serve

lint: check-env ## Run ruff lint checks (report only)
	$(RUFF) check .

lint-fix: check-env ## Auto-fix safe ruff lint issues
	$(RUFF) check . --fix

clean: ## Remove Python build/test artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .ruff_cache build dist site *.egg-info
