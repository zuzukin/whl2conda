# whl2conda changes

## [24.1.2] - *in progress*
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
