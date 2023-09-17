RM := rm
RMDIR := rm -rf
DEV_ENV := whl2conda-dev
TOUCH := touch

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

VERSION_FILE := src/whl2conda/VERSION
VERSION := $(file < $(VERSION_FILE))

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
	"doc           - build documentation\n" \
	"doc-strict    - build documentation and check links\n" \
	"doc-open      - build/open documentation index.html\n" \
	"doc-serve     - serve documentation in temporary web server\n" \
	"doc-serve-all - serve versioned documentation in temporary web server\n" \
	"doc-deploy    - deploy doc for current version to gh-pages branch\n" \
	"doc-push      - upload docs by pushing gh-pages branch to github\n" \
	"doc-clean     - remove generated documentation files\n" \
	"\n" \
	"--- distribute ---\n" \
	"build        - build wheel and conda package in dist/\n" \
	"check-upload - check uploadable wheels in dist/\n" \
	"upload       - upload the latest wheel in dist (requires pypi access)/\n" \
	"\n" \
	"--- clean ---\n" \
	"clean          - remove generated files\n" \
	"clean-doc      - just remove generated doc files\n" \
	"clean-build    - just remove generated build files\n" \
	"clean-coverage - just remove generated coverage data and reports\n" \
	"clean-all      - remove generated files and caches" \

#
# Environment management
#

DEV_INSTALL := $(CONDA_RUN) pip install -e . --no-deps --no-build-isolation

createdev:
	conda env create -f environment.yml -n $(DEV_ENV)
	$(MAKE) dev-install

updatedev:
	conda env update -f environment.yml -n $(DEV_ENV)
	$(MAKE) dev-install

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
	$(CONDA_RUN) pytest -s --cov=src --cov-report=json --cov-report=term test

slow-coverage:
	$(CONDA_RUN) pytest -s --cov=src --cov-report=json --cov-report=term test --run-slow

htmlcov/index.html: .coverage
	$(CONDA_RUN) coverage html

html-coverage: htmlcov/index.html

open-coverage: htmlcov/index.html
	$(OPEN) $<

#
# Documentation targets
#

MKDOCS_FILE := mkdocs.yml
CLI_SUBCMDS := $(shell $(CONDA_RUN) whl2conda --list-subcommands)
CLI_DOCS := doc/cli/whl2conda.md $(foreach subcmd,$(CLI_SUBCMDS),doc/cli/whl2conda-$(subcmd).md)

# Build main cli man page
doc/cli/whl2conda.md: src/whl2conda/cli/main.py
	$(CONDA_RUN) whl2conda --markdown-help > $@

# Build subcommand cli man page
doc/cli/whl2conda-%.md: src/whl2conda/cli/%.py
	$(CONDA_RUN) whl2conda $* --markdown-help > $@

site/index.html: $(CLI_DOCS) $(MKDOCS_FILE) doc/*.md src/whl2conda/api/*.py
	$(CONDA_RUN) mkdocs build -f $(MKDOCS_FILE)

doc: site/index.html

site/.doc-strict: site/index.html
	$(CONDA_RUN) linkchecker -f likcheckerrc.ini site
	$(TOUCH) $@

doc-strict: site/.doc-strict

doc-serve: $(CLI_DOCS)
	$(CONDA_RUN) mkdocs serve -f $(MKDOCS_FILE)

serve-doc: doc-serve

doc-open: site/index.html
	$(OPEN) site/index.html

open-doc: doc-open

doc-deploy:
	$(CONDA_RUN) mike deploy -F $(MKDOCS_FILE) -u $(VERSION) latest
	$(CONDA_RUN) mike set-default -F $(MKDOCS_FILE) latest

mike-deploy: doc-deploy
mike-build: doc-deploy

doc-push:
	git push origin gh-pages

doc-upload: doc-push

doc-serve-all:
	$(CONDA_RUN) mike serve -F $(MKDOCS_FILE)

mike-serve: doc-serve-all

#
# Distribution targets
#

# TODO - add targets from version
build-sdist:
	$(CONDA_RUN) python -m build --sdist --no-isolation --outdir dist

build-conda:
	# Use tool to build itself!
	$(CONDA_RUN) whl2conda convert --build-wheel

build: build-sdist build-conda

check-upload-wheel:
	$(CONDA_RUN) twine check dist/*.whl

check-upload-sdist:
	$(CONDA_RUN) twine check dist/*.tar.gz

check-upload: check-upload-sdist check-upload-wheel

upload-wheel: check-upload-wheel
	# NOTE: --skip-existing doesn't seem to actually work
	$(CONDA_RUN) twine upload --skip-existing $(lastword $(sort $(wildcard dist/*.whl)))


upload-sdist: check-upload-sdist
	# NOTE: --skip-existing doesn't seem to actually work
	$(CONDA_RUN) twine upload --skip-existing $(lastword $(sort $(wildcard dist/*.tar.gz)))

upload: upload-sdist upload-wheel

#
# Cleanup targets
#

clean-coverage:
	$(RMDIR) htmlcov .coverage coverage.json coverage.xml

clean-doc:
	$(RMDIR) site doc/whl2conda-cli.md

doc-clean: clean-doc

clean-build:
	-find . \( -name '*.whl' -or -name '*.conda' -or -name '*.tar.bz2' \) -exec $(RM) {} \;
	-find . \( -name 'dist' -or -name 'build' -or -name '*.egg-info' \) -exec $(RMDIR) {} \;

clean: clean-doc clean-coverage clean-build

clean-all: clean
	-$(RMDIR) .mypy_cache
	-$(RMDIR) .pytest_cache


