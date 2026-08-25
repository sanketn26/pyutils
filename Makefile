# pyutils — independent Python utilities monorepo
#
#   make setup              create .venv and install everything
#   make new NAME=foo       scaffold a new package
#   make test [PKG=foo]     run tests
#   make lint [PKG=foo]     ruff check
#   make clean              remove venv, caches, build artifacts

PYTHON_VERSION ?= 3.13
PACKAGES_DIR   := packages
UV             := uv
export PATH := $(HOME)/.local/bin:$(PATH)

PACKAGES := $(shell find $(PACKAGES_DIR) -mindepth 1 -maxdepth 1 -type d ! -name '_*' -printf '%f\n' 2>/dev/null | sort)

.DEFAULT_GOAL := help

.PHONY: help setup env install sync python \
        list new add run \
        test lint format check \
        clean clean-venv clean-caches

help:
	@printf '%s\n' \
	  'pyutils monorepo (Python $(PYTHON_VERSION)+)' \
	  '' \
	  'Setup' \
	  '  make setup              Install uv, Python $(PYTHON_VERSION), create .venv, sync all packages' \
	  '  make env                Alias for setup' \
	  '  make python             Show the workspace Python' \
	  '' \
	  'Packages' \
	  '  make list               List workspace packages' \
	  '  make new NAME=foo       Scaffold packages/foo  (DESC="..." optional)' \
	  '  make add PKG=foo DEP=x  Add a runtime dependency to a package' \
	  '  make run PKG=foo        Run python -m <import>  (ARGS="..." optional)' \
	  '' \
	  'Quality' \
	  '  make test [PKG=foo]     Run pytest' \
	  '  make lint [PKG=foo]     Ruff check' \
	  '  make format [PKG=foo]   Ruff format + --fix' \
	  '  make check              lint + test' \
	  '' \
	  'Cleanup' \
	  '  make clean              Remove .venv, caches, build artifacts, bytecode' \
	  '  make clean-venv         Remove only .venv' \
	  '  make clean-caches       Remove ruff/pytest/mypy/__pycache__/build artifacts'

define ensure_uv
	@command -v uv >/dev/null 2>&1 || { \
		echo "Installing uv..."; \
		curl -LsSf https://astral.sh/uv/install.sh | sh; \
	}
endef

setup env install sync:
	$(ensure_uv)
	$(UV) python install $(PYTHON_VERSION)
	$(UV) python pin $(PYTHON_VERSION)
	$(UV) sync --all-packages --group dev
	@echo "Environment ready: $$($(UV) run python -V)"
	@$(UV) run python -c "import sys; print(sys.executable)"

python:
	$(UV) run python -V
	@$(UV) run python -c "import sys; print(sys.executable)"

list:
	@if [ -z "$(PACKAGES)" ]; then echo "(no packages yet)"; else printf '%s\n' $(PACKAGES); fi

new:
	@test -n "$(NAME)" || { echo "usage: make new NAME=foo [DESC='...']"; exit 1; }
	@python3 scripts/new_package.py "$(NAME)" "$(or $(DESC),Independent utility)"
	$(UV) sync --all-packages --group dev

add:
	@test -n "$(PKG)" || { echo "usage: make add PKG=foo DEP=httpx"; exit 1; }
	@test -n "$(DEP)" || { echo "usage: make add PKG=foo DEP=httpx"; exit 1; }
	$(UV) add --package "$(PKG)" $(DEP)

define require_pkg
	@test -n "$(PKG)" || { echo "PKG is required"; exit 1; }
	@test -d "$(PACKAGES_DIR)/$(PKG)" || { echo "unknown package: $(PKG)"; echo "known: $(PACKAGES)"; exit 1; }
endef

test:
ifdef PKG
	$(require_pkg)
	$(UV) run --package "$(PKG)" --group dev pytest "$(PACKAGES_DIR)/$(PKG)"
else
	$(UV) run pytest $(PACKAGES_DIR)
endif

lint:
ifdef PKG
	$(require_pkg)
	$(UV) run ruff check "$(PACKAGES_DIR)/$(PKG)"
else
	$(UV) run ruff check $(PACKAGES_DIR)
endif

format:
ifdef PKG
	$(require_pkg)
	$(UV) run ruff format "$(PACKAGES_DIR)/$(PKG)"
	$(UV) run ruff check --fix "$(PACKAGES_DIR)/$(PKG)"
else
	$(UV) run ruff format $(PACKAGES_DIR)
	$(UV) run ruff check --fix $(PACKAGES_DIR)
endif

check: lint test

run:
	$(require_pkg)
	$(UV) run --package "$(PKG)" python -m $(subst -,_,$(PKG)) $(ARGS)

clean: clean-venv clean-caches
	@echo "Clean complete."

clean-venv:
	rm -rf .venv
	@echo "Removed .venv"

clean-caches:
	@find . \( -path ./.git -o -path ./.venv \) -prune -o -type d -name '__pycache__' -print0 \
		| xargs -0r rm -rf
	@find . \( -path ./.git -o -path ./.venv \) -prune -o -type d \( \
			-name '.pytest_cache' -o -name '.ruff_cache' -o -name '.mypy_cache' \
			-o -name '*.egg-info' -o -name 'dist' -o -name 'build' \
		\) -print0 | xargs -0r rm -rf
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage coverage.xml
	@echo "Removed caches and build artifacts"
