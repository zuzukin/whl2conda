# whl2conda changes

## [26.7.0] - *in progress*

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

### Changes

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
