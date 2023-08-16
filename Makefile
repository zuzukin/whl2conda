RM := rm
RMDIR := rm -rf
DEV_ENV := whl2conda-dev

ifdef OS
	# Windows
	OPEN :=
else
	UNAME_S := $(shell uname -s)
	ifeq ($(NAME_S),Darwin)
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
	"--- testing ---\n" \
	"pylint      - run pylint checks\n" \
	"mypy        - run mypy type checks\n" \
	"black-check - check black formatting\n" \
	"lint        - run all lint checkers\n" \
	"pytest      - run pytests\n" \
	"--- documentation ---\n" \
	"doc         - build documentation\n" \
	"open-doc    - open documentation index.html\n" \
	"serve-doc   - serve documentation in temporary web server\n" \
	"clean-doc   - remove generated documentation files"

#
# Environment management
#

createdev:
	conda env create -f environment.yml -n $(DEV_ENV) --yes
	$(CONDA_RUN) pip install -e . --no-deps --no-build-isolation

updatedev:
	conda env update -f environment.yml -n $(DEV_ENV)
	$(CONDA_RUN) pip install -e . --no-deps --no-build-isolation

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
	$(CONDA_RUN) pytest test

test: pytest

# TODO add coverage target

#
# Documentation targets
#

doc/whl2conda-cli.md: src/whl2conda/cli.py
	$(CONDA_RUN) whl2conda --markdown-help > $@

doc: doc/whl2conda-cli.md
	$(CONDA_RUN) mkdocs build

serve-doc: doc/whl2conda-cli.md
	$(CONDA_RUN) mkdocs serve

open-doc: doc/whl2conda-cli.md
	open site/index.html

#
# Cleanup targets
#

clean-doc:
	$(RMDIR) site doc/whl2conda-cli.md

clean: clean-doc
