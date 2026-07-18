# Python API

*whl2conda* can be used programmatically from Python as well as from
the command line. The modules in this section document the public
python API.

## Stability policy

The **public API** consists of exactly the classes, functions, and
attributes documented in this section (equivalently, the names
exported in the `__all__` of the `whl2conda.api` modules and
`whl2conda.settings`). Everything else — including the
`whl2conda.cli`, `whl2conda.impl`, and `whl2conda.external`
packages and any name starting with an underscore — is internal
and may change without notice.

For the public API:

* Backwards-incompatible changes will not be made without a
  deprecation period of at least one release *and* at least six
  months: the deprecated form will continue to work and emit a
  `DeprecationWarning` before it is removed.
* All changes to the public API are recorded in the
  [changelog](../../about/changelog.md).
* The package ships a `py.typed` marker, so the public API can be
  type-checked with mypy or pyright.

## Modules

* [whl2conda.api.converter](converter.md) — convert wheels to conda packages
* [whl2conda.api.compare](compare.md) — semantically compare conda packages
* [whl2conda.api.stdrename](stdrename.md) — standard pypi to conda renames
* [whl2conda.settings](settings.md) — persistent user settings
