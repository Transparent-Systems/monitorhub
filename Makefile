# MonitorHub Makefile
# Ensures the project virtualenv (.venv) is always used for tests and scripts.
# Agents and developers should use these targets instead of invoking bare
# `python` or `python3`, which may resolve to a system/pyenv interpreter.

PYTHON := .venv/bin/python
UNITTEST := $(PYTHON) -m unittest
RUFF := $(PYTHON) -m ruff

.PHONY: help check-env test test-unit test-integration test-command-action-handler test-command-processor lint lint-fix clean

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-28s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

check-env: ## Verify the .venv interpreter is available and print its version
	@test -x $(PYTHON) || { \
		echo "ERROR: $(PYTHON) not found. Create the virtualenv first:"; \
		echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"; \
		exit 1; }
	@$(PYTHON) -c "import sys; print(f'Using {sys.executable} ({sys.version.split()[0]})')"

test: test-unit ## Run all unit tests

test-unit: check-env ## Run the full unit test suite
	$(UNITTEST) discover -s tests -p "test_*.py" -v

test-integration: check-env ## Run integration tests (needs credentials in testdata/.env)
	$(PYTHON) -m tests.test_rclone_handler_integration
	$(PYTHON) -m tests.test_s3_handler_integration

test-command-action-handler: check-env ## Run CommandActionHandler unit tests only
	$(UNITTEST) tests.test_command_action_handler -v

test-command-processor: check-env ## Run CommandProcessor command unit tests only
	$(UNITTEST) tests.test_command_processor -v

lint: check-env ## Run ruff lint checks (report only)
	$(RUFF) check --config scripts/ruff.toml .

lint-fix: check-env ## Auto-fix safe ruff lint issues
	$(RUFF) check --config scripts/ruff.toml . --fix

clean: ## Remove Python build/test artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .ruff_cache build dist *.egg-info