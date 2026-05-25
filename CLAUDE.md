# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

whl2conda is a CLI tool that converts pure Python wheel packages into conda packages without
creating conda environments to build (much faster than conda-build). It renames PyPI
dependencies to their conda-forge equivalents, supports V1 (`.tar.bz2`) and V2 (`.conda`)
formats, reads project-specific options from `pyproject.toml`, and has experimental support
for binary wheels via `--allow-impure`.

## Environment

This project uses [pixi](https://pixi.sh/) for environment management. All commands below run
through pixi. Some tests additionally require `conda`/`mamba` installed separately on PATH,
since whl2conda generates and installs real conda packages.

```bash
pixi install && pixi run dev-install   # first-time setup
pixi task list                         # see all available tasks
```

## Common commands

```bash
pixi run test              # full test suite (alias for pytest -s test)
pixi run lint              # ruff check + pyright + mypy + ruff format --check
pixi run build             # build sdist + conda + wheel into dist/
pixi run doc               # generate CLI docs, then build MkDocs site
pixi run coverage          # tests with coverage report
```

Run a single test file or function (note the `--` to pass args through pixi):

```bash
pixi run -- pytest -s test/api/test_converter.py
pixi run -- pytest -s test/api/test_converter.py::test_function_name
```

Tests marked `@pytest.mark.external` (depend on real PyPI packages) or `@pytest.mark.slow`
are skipped by default. Enable with `--run-external` / `--run-slow` (see `test/conftest.py`).

## Architecture

The package is layered: `cli/` → `api/` → `impl/`.

- **`src/whl2conda/api/`** — Public API. `converter.py` holds `Wheel2CondaConverter`, the core
  engine that reads a wheel, rewrites metadata (renaming PyPI deps to conda names, optionally
  hiding pip deps), and writes a conda package. `stdrename.py` loads the known rename mappings
  bundled in `stdrename.json` (regenerate with `pixi run update-stdrename`).
- **`src/whl2conda/cli/`** — argparse-based CLI. `main.py` defines the top-level parser;
  subcommands `build`, `convert`, `config`, `diff`, `install` are separate modules. `common.py`
  has shared utilities including markdown help generation (used to build the CLI docs).
- **`src/whl2conda/impl/`** — Internal helpers: wheel unpacking (`wheel.py`), `pyproject.toml`
  parsing (`pyproject.py`), interactive prompts (`prompt.py`), file downloads (`download.py`).
- **`src/whl2conda/settings.py`** — Global `Whl2CondaSettings` singleton loaded from a
  platform-specific JSON file. Tests auto-reset it via the `clear_settings` fixture in
  `test/conftest.py`.
- **`src/whl2conda/external/`** — Vendored third-party code. Excluded from linting, type
  checking, and coverage — don't modify to satisfy lint.

Tests mirror the source tree under `test/` (`test/api/`, `test/cli/`, `test/impl/`).
`test-projects/` and `research/` are excluded from linting.

## Conventions

- **Version**: stored as plain text in `src/whl2conda/VERSION`; hatchling reads it. Do not
  hardcode the version elsewhere.
- **Imports**: grouped as `# standard`, `# third party`, `# this project`.
- **Formatting**: ruff, 88-char lines, LF endings, preserved quote style, Google-style
  docstrings. Run `pixi run lint` before considering work done.
- **Type checking**: both mypy (`check_untyped_defs = true`) and pyright run in `lint`. The
  package ships a `py.typed` marker, so keep public APIs typed.
- **License headers**: all source files carry the Apache 2.0 license header — include it on new
  files.

## CLI docs are generated

The reference docs under `doc/reference/cli/` are generated from `--markdown-help` output by
`pixi run build-cli-docs`. After changing CLI arguments/help text, regenerate rather than
editing those files by hand.
