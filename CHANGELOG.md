# whl2conda changes

## [next] - *in progress*

### Bug fixes

* `--resolve-extras` no longer fails to resolve extras of packages
  whose pypi metadata does not populate `provides_extra` (which is
  commonly null even when the extras exist); the extra's entries in
  `Requires-Dist` are now authoritative. Found by a new external test
  exercising the real pypi.org metadata API.

### Development

* Code readability overhaul from an internal review: oriented and
  reorganized the converter module, decomposed the convert command's
  main flow, replaced sentinel values with a WheelChoice enum,
  deduplicated CLI logging setup and pyproject list parsing,
  centralized shared test fixtures in conftest files, split the
  oversized converter test module, and removed stale comments and
  dead code throughout.

### Changes

* Dependency rename replacement strings are now validated to contain
  only valid package name characters.
* The documented python API has been narrowed to the intended stable
  surface, with an explicit stability policy: see the new Python API
  overview page in the reference documentation. The `noarch_build_string`
  helper is no longer exported from `whl2conda.api.converter`.

## [26.8.0] - *in progress*

### Features

* `whl2conda build` now supports v1 (`recipe.yaml`) recipes, as built
  by rattler-build, in addition to classic (`meta.yaml`) recipes.
  v1 recipes are rendered with the py-rattler-build python package
  when it is importable and otherwise with the `rattler-build` command;
  the recipe's `tests:` list is run against the generated package
  (in a single shared test environment). v1 recipes must declare
  `noarch: python`. (#160)
* `whl2conda build` now runs the recipe build script in the recipe's
  source directory (conda-build's source work directory when populated,
  otherwise the recipe's local `path:` source), instead of the current
  directory, so it no longer needs to be invoked from the project root.
* New "Building from Recipes" user guide documentation page.
* `whl2conda build` now supports most applicable `conda build` options:
  the build modes `--output` (print the predicted package path without
  building), `-t`/`--test` (test the already-built package),
  `-b`/`--build-only`, and `--skip-existing`, plus `--output-folder`,
  `--package-format`, `--croot`, `--python`, `-q`/`--quiet`, and
  `--debug`. Inapplicable conda build options are accepted and ignored
  with a warning, except upload/signing and non-python language
  options, which are rejected with an error. (#110)
* New `whl2conda build` extension options: `--check` renders the recipe
  and verifies whl2conda can build it, without building anything;
  `--extra-deps` adds conda dependencies to the generated package;
  `--keep-test-env` keeps the test environment for debugging; and
  `--mamba` uses mamba to create test environments and to run
  conda-build when it must be run in the base environment. (#110)

* Package tests for the generated conda package can now be specified
  in `[[tool.whl2conda.tests]]` in pyproject.toml, using the v1 recipe
  `tests` schema, or in a standalone YAML file; the new
  `tool.whl2conda.test-python` option lists python versions to test
  against. (#190)

* New `whl2conda test` command tests a conda package file in a fresh
  environment, using tests from a `--test-file` YAML file, the
  pyproject.toml `[tool.whl2conda.tests]` section, or the test section
  of a conda recipe, optionally against multiple python versions. (#83)

### Changes

* `whl2conda build` renders recipes into its own temporary work
  directory (instead of scraping conda-build console output to locate
  scratch space in conda-bld), checks the exit status of the render,
  uses conda-build in-process when it is importable, and reports
  build errors clearly. (#110)

### Bug fixes

* The build string of generated noarch packages now includes the build
  number (e.g. `py_1`) instead of always being `py_0`. (#110)

### Development

* Extracted the package test logic from `whl2conda build` into a shared,
  reusable test runner supporting both classic recipe `test:` sections
  and v1 recipe `tests:` lists, in preparation for `whl2conda test`
  (#83) and pyproject test specifications (#190). The recipe
  `test.source_files` entries are now honored (they were previously
  ignored).

## [26.7.1] - 2026-7-12

### Bug fixes

* Dependencies with extras (`name[extra,...]`) now generate a warning
  when the extras are dropped, instead of dropping them silently, and
  dependency rename rules are matched against the bracketed form first
  so such dependencies can be mapped to a corresponding conda package
  (e.g. `dask[complete]` to `dask`). For a built-in table of common
  extras with dedicated conda-forge packages (e.g. `uvicorn[standard]`,
  `ray[default]`, `black[jupyter]`), the warning names the
  corresponding conda package. (#217)

### Features

* New `--known-extras` option automatically replaces dependency extras
  from the built-in table of common extras with dedicated conda-forge
  packages (e.g. `uvicorn[standard]` with `uvicorn-standard`). (#217)
* New `--resolve-extras` option resolves remaining dependency extras
  from pypi.org metadata: the extra's dependencies are read from the
  newest release satisfying the dependency's version spec, converted
  like regular dependencies, and any nested extras are resolved
  recursively. This is a best-effort approximation, since the solver
  may install a version whose extras differ. (#36)

### Changes

* New runtime dependency on `packaging` (used to select release
  versions when resolving extras from pypi metadata; it was already
  used opportunistically for dependency marker evaluation).

## [26.7.0] - 2026-7-11

### Features

* Convert stable ABI (abi3) wheels into a single conda package usable on
  all supported python versions, following the CEP-20 layout: the python
  dependency is only a lower bound, and files are installed using the
  noarch python machinery (#183)
* The `--python` option now overrides the automatically generated python
  version pin for binary (`--allow-impure`) conversions (#183)
* New `--for-conda-forge` option (synonym: `--for-cpython`) adds the CEP-20
  python pins used by conda-forge (`cpython` and `_python_abi3_support`)
  when converting stable ABI (abi3) wheels (#194)
* `whl2conda diff` now semantically analyzes the differences between two
  conda packages by default, reporting notable and unexpected differences
  while suppressing differences expected between whl2conda-generated and
  recipe-built packages. The `-T`/`--diff-tool` option is now optional and
  selects the previous raw diff behavior. The analysis engine is also
  available programmatically as `whl2conda.api.compare`.
* New `--platform-tag` option selects the wheel platform tag to convert
  for when converting a multi-platform ("fat") binary wheel (#201)
* New `--all-platforms` option generates a conda package for every
  platform supported by the wheel, each written into a `<subdir>/`
  subdirectory of the output directory (#204)

### Changes

* Binary wheel conversion (`--allow-impure`) is no longer labeled
  experimental: conversions of representative C, C++, Cython, rust, and
  abi3 extension packages are verified to be semantically equivalent to
  the corresponding conda-forge packages on linux, macOS, and windows by
  the new comparison suite. The converter now emits a targeted warning
  when a wheel bundles vendored shared libraries (the main remaining
  limitation) instead of a blanket experimental warning on every binary
  conversion.
* `whl2conda install` no longer checks the conda-libmamba-solver version
  or switches target environments to the classic solver. That workaround
  was only needed for conda-libmamba-solver older than 24.1.0, which fixed
  the underlying file-install issue
  ([conda-libmamba-solver#418](https://github.com/conda/conda-libmamba-solver/issues/418)).
  This also removes a crash when conda-libmamba-solver was not installed
  in the base environment.

### Development

* Documentation is now generated with [Zensical](https://zensical.org)
  instead of the no-longer-maintained MkDocs/mkdocs-material (#173)
* New external comparison test suite (`pixi run compare-conda-forge`)
  converts a curated sample of binary PyPI packages and semantically
  compares the results against the corresponding conda-forge packages,
  building evidence toward removing the experimental label from binary
  conversion. Supersedes the `research/compare_packages.py` prototype,
  which has been removed.

### Bug fixes

* The `timestamp` in the package's `index.json` is now written in
  milliseconds since the epoch, matching conda-build and rattler-build.
  It was previously written in seconds and was also incorrectly shifted
  by the local timezone offset. (#193)
* `whl2conda diff` no longer fails on packages that do not contain an
  `info/files` entry, e.g. packages built by rattler-build (#192)
* Packages converted on Windows no longer contain backslash path
  separators in `info/paths.json` and `info/files`, which violated
  the conda package format (#203)

## [26.2.1] - 2026-7-9

### Bug fixes

* Dependency names that do not match any rename rule are again passed through
  with their original spelling, instead of being rewritten to their PEP 503
  normalized form. This restores pre-26.2.0 behavior for packages whose conda
  name contains `_`, `.` or uppercase characters. (#184)
* Dependency rename patterns are now matched against both the name as written
  in the wheel metadata and its PEP 503 normalized form, so patterns
  containing `_` or `.` work again. (#184)

### Development

* Automated release workflow: pushing a version tag publishes to PyPI
  (trusted publishing), creates the GitHub release, and deploys the
  versioned documentation (#145)

## [26.2.0] - 2026-2-22

### Features

* Experimental support for converting binary (non-pure Python) wheels via `--allow-impure` flag
* Support parsing name from Poetry 2.0 pyproject.toml
* Handle bad UTF-8 in METADATA files
* Support wheel metadata version 2.5 (PEP 770) - SBOM documents

### Bug fixes

* Normalize PyPI package names per PEP 503 when applying dependency renames (#134)
* Show user-friendly error message when wheel download from PyPI fails (#125)

### Changes

* Drop support for python 3.9
* Internal code refactoring and cleanup

### Development

* Switched to pixi for development environment management

## [25.3.0] - 2025-3-20

### Features

* Support metadata version 2.4 (PEP 688)
* Added --allow-metadata-version option to convert command

### Changes

* Drops support for python 3.8

## [24.5.0] - 2024-5-5
### Features
* Added persistent user settings for:
    * default conda format
    * whether to automatically update stdrenames table
    * specify aliases for extra pypi indexes

## [24.4.0] - 2024-4-14
### Changes
* Only use classic installer in `whl2conda install` environments if 
    `conda-libmamba-solver` in base environment has version less than 24.1.0 (see #118)

### Bug fixes
* Transfer executable file permissions from wheel (#135)
* Correct typos in documentation.

## [24.1.2] - 2024-1-28

### Features
* Support `whl2conda convert --python` override.
* Added one-line description to whl2conda package

## [24.1.1] - 2024-1-15

### Features
* Support conversion of wheels containing `*.data` directories
* Support direct download of wheels to convert from pypi repositories

## [24.1.0] - 2024-1-8

### Features
* Add `whl2conda build` - limited experimental drop-in replacement for `conda build`
* Support translation of `~=` and `===` version specification operators.
* `whl2conda install` now supports installing multiple package files at once

### Bug fixes
* Use classic installer in `whl2conda install` environments to work around conda bug (#114)
* Include project URLs in metadata that have multi-word keys (#113)
* Write METADATA file in dist-info using UTF8 (#112)

## [23.9.0] - 2023-9-23

* First official stable release

## [23.8.10] - 2023-9-16 (*prerelease*)

* Fix generation of entry points
* Adjust metadata generation
* Add `whl2conda diff` subcommand

## [23.8.9] - 2023-9-14 (*prerelease*)

* Support `python -m whl2conda`
* Fix issue with license copying

## [23.8.8] - 2023-9-10 (*prerelease*)

* hide pip build wheel output with `--quiet`

## [23.8.7] - 2023-9-9 (*prerelease*)

* first conda-forge release
