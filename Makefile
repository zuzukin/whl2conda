RM := rm
RMDIR := rm -rf
DEV_ENV := whl2conda-dev

ifdef OS
	# Windows
	OPEN :=
else
	UNAME_S := $(shell uname -s)
	ifeq ($(UNAME_S),Darwin)
		OPEN := open
	else
		OPEN := xdg-open
	endif
endif

-include custom.mk

# Whether to run targets in current env or explicitly in $(DEV_ENV)
CURR_ENV_BASENAME := $(lastword $(subst /, ,$(CONDA_PREFIX)))
ifeq ($(CURR_ENV_BASENAME), $(DEV_ENV))
	CONDA_RUN :=
else
	CONDA_RUN := conda run -n $(DEV_ENV) --no-capture-output
endif

.DEFAULT_GOAL := help
help:
	@echo "" \
	"=== make targets ===\n" \
	"--- dev environment ---\n" \
	"createdev - create conda development environment named $(DEV_ENV)\n" \
	"updatedev - update conda development environment\n" \
	"\n" \
	"--- testing ---\n" \
	"pylint        - run pylint checks\n" \
	"mypy          - run mypy type checks\n" \
	"black-check   - check black formatting\n" \
	"lint          - run all lint checkers\n" \
	"pytest        - run pytests\n" \
	"coverage      - run pytests with test coverage\n" \
	"open-coverage - open HTML coverage report\n" \
	"\n" \
	"--- documentation ---\n" \
	"doc         - build documentation\n" \
	"open-doc    - open documentation index.html\n" \
	"serve-doc   - serve documentation in temporary web server\n" \
	"clean-doc   - remove generated documentation files"

#
# Environment management
#

DEV_INSTALL := $(CONDA_RUN) pip install -e . --no-deps --no-build-isolation

createdev:
	conda env create -f environment.yml -n $(DEV_ENV) --yes
	$(DEV_INSTALL)


updatedev:
	conda env update -f environment.yml -n $(DEV_ENV)
	$(DEV_INSTALL)

dev-install:
	$(DEV_INSTALL)

#
# Test and lint targets
#

black-check:
	$(CONDA_RUN) black --check src test

pylint:
	$(CONDA_RUN) pylint src test

mypy:
	$(CONDA_RUN) mypy

lint: pylint mypy black-check

pytest:
	$(CONDA_RUN) pytest -s test

test: pytest

coverage:
	$(CONDA_RUN) pytest -s --cov=src --cov-report=html --cov-report=term test

htmlcov/index.html:
	$(MAKE) coverage

open-coverage: htmlcov/index.html
	$(OPEN) $<

#
# Documentation targets
#

CLI_SUBCMDS := build config install
CLI_DOCS := doc/cli/whl2conda.md $(foreach subcmd,$(CLI_SUBCMDS),doc/cli/whl2conda-$(subcmd).md)

doc/cli/whl2conda.md: src/whl2conda/cli/main.py
	$(CONDA_RUN) whl2conda --markdown-help > $@

doc/cli/whl2conda-%.md: src/whl2conda/cli/%.py
	$(CONDA_RUN) whl2conda $* --markdown-help > $@

doc: $(CLI_DOCS) mkdocs.yml
	$(CONDA_RUN) mkdocs build

serve-doc: $(CLI_DOCS)
	$(CONDA_RUN) mkdocs serve

open-doc: doc/whl2conda-cli.md
	$(OPEN) site/index.html

#
# Cleanup targets
#

clean-coverage:
	$(RMDIR) htmlcov .coverage

clean-doc:
	$(RMDIR) site doc/whl2conda-cli.md

clean-gen:
	-find . \( -name '*.whl' -or -name '*.conda' -or -name '*.tar.bz2' \) -exec $(RM) {} \;
	-find . \( -name 'dist' -or -name 'build' -or -name '*.egg-info' \) -exec $(RMDIR) {} \;

clean: clean-doc clean-coverage clean-gen


