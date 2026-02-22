# Copilot Instructions for whl2conda

## Project Overview

whl2conda is a CLI tool that converts pure Python wheel packages into conda packages.
It renames PyPI dependencies to their conda-forge equivalents, supports V1 (`.tar.bz2`)
and V2 (`.conda`) formats, and reads project-specific options from `pyproject.toml`.

## Development Environment

This project uses [pixi](https://pixi.sh/) for environment management. Some tests also require 
conda/mamba to be installed separately.

```bash
pixi install && pixi run dev-install   # first-time setup
```

## Build, Test, and Lint

```bash
pixi run test              # run full test suite
pixi run pytest            # run pytest directly (same as: pytest -s test)
pixi run lint              # ruff + mypy + format check
pixi run build             # build wheel + conda + sdist packages
pixi run doc               # build MkDocs documentation
```

Run a single test file or test function:
```bash
pixi run -- pytest -s test/api/test_converter.py
pixi run -- pytest -s test/api/test_converter.py::test_function_name
```

Tests marked `@pytest.mark.external` or `@pytest.mark.slow` are skipped by default. Enable with `--run-external` or `--run-slow`.

## Architecture

- **`src/whl2conda/api/`** — Public API. `converter.py` contains the core 
    `Wheel2CondaConverter` that reads a wheel, rewrites metadata (renaming PyPI deps 
    to conda names), and writes a conda package. `stdrename.py` loads the known rename
    mappings from `stdrename.json`.
- **`src/whl2conda/cli/`** — CLI layer built with argparse. `main.py` defines the 
    top-level parser; subcommands (`build`, `convert`, `config`, `diff`, `install`) 
    are in separate modules. `common.py` has shared CLI utilities including markdown 
    help generation.
- **`src/whl2conda/impl/`** — Internal implementation helpers: wheel unpacking 
    (`wheel.py`), `pyproject.toml` parsing (`pyproject.py`), interactive prompts 
    (`prompt.py`), and file downloads (`download.py`).
- **`src/whl2conda/settings.py`** — Global `Whl2CondaSettings` singleton loaded 
    from a platform-specific JSON file. Tests auto-clear settings via the 
    `clear_settings` fixture in `test/conftest.py`.
- **`src/whl2conda/external/`** — Vendored third-party code.
    Excluded from linting and coverage.

## Key Conventions

- **Build system**: hatchling. Version is stored in `src/whl2conda/VERSION` (plain text file).
- **Import style**: Imports are grouped as `# standard`, `# third party`, `# this project`.
- **Formatting**: ruff with 88-char line length, LF line endings, preserved quote style. Google-style docstrings.
- **Type checking**: mypy with `check_untyped_defs = true`. The package ships a `py.typed` marker.
- **Test layout**: Tests mirror the source tree under `test/` (e.g., `test/api/`, `test/cli/`, `test/impl/`).
- **License headers**: All source files include the Apache 2.0 license header.
