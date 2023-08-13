DEV_ENV := whl2conda-dev

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
	"--- dev environment ---\n" \
	"createdev - create conda development environment named $(DEV_ENV)" \
	"updatedev - update conda development environment"
	"--- testing --\n" \
	"pylint - run pylint checks" \
	"mypy   - run mypy type checks " \
	"lint   - run all lint checkers" \
	"pytest - run pytests" \

createdev:
	conda env create -f environment.yml -n $(DEV_ENV) --yes
	$(CONDA_RUN) pip install -e . --no-deps --no-build-isolation

updatedev:
	conda env update -f environment.yml -n $(DEV_ENV)
	$(CONDA_RUN) pip install -e . --no-deps --no-build-isolation

pylint:
	$(CONDA_RUN) pylint src test

mypy:
	$(CONDA_RUN) mypy

lint: pylint mypy

pytest:
	$(CONDA_RUN) pytest test
