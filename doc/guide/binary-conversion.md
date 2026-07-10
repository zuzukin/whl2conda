# Binary Wheel Conversion

## Overview

By default, **whl2conda** converts pure Python wheels (`py3-none-any`) into
`noarch: python` conda packages. With the `--allow-impure` flag, it can also
convert platform-specific binary wheels containing compiled extensions (`.so`,
`.pyd`, `.dll`) into architecture-specific conda packages.

```bash
whl2conda convert --allow-impure markupsafe-3.0.2-cp312-cp312-manylinux_2_17_x86_64.whl
```

This produces a conda package with:

- **Platform-specific subdir** (e.g. `linux-64`, `osx-arm64`, `win-64`)
- **Tight Python version pin** (e.g. `python >=3.12,<3.13.0a0`)
- **Python ABI constraint** (e.g. `python_abi 3.12.* *_cp312`)
- **OS minimum version constraints** for macOS wheels (e.g. `__osx >=11.0`)

You can override the automatically derived Python pin with the `--python`
option, in which case no `python_abi` constraint is added:

```bash
whl2conda convert --allow-impure --python '>=3.12' some-wheel.whl
```

## Stable ABI (abi3) wheels

Wheels built against the CPython stable ABI (with an `abi3` tag, e.g.
`cp312-abi3-macosx_11_0_arm64`) work on the tagged Python version *and all
later versions*. **whl2conda** recognizes the `abi3` tag and produces a single
platform-specific conda package that installs on any compatible Python:

- The Python dependency is only a floor (e.g. `python >=3.12`) derived from
  the wheel's Python tag; no upper bound or `python_abi` constraint is added.
  A tighter `Requires-Python` constraint from the wheel metadata is kept.
- The package keeps its platform subdir (e.g. `osx-arm64`) but is marked
  `noarch: python` and lays its files out under `site-packages/`, so the
  installer relocates them into the environment's actual `site-packages`
  directory regardless of Python version. This follows the conda ecosystem
  convention for abi3 packages
  ([CEP-20](https://conda.org/learn/ceps/cep-0020/)).
- The build string is marked accordingly, e.g. `py312_abi3_0`.

!!! note
    This package layout is supported by all current conda install tools —
    the `noarch: python` install machinery it relies on has been present
    since conda 4.3 (2017) and works regardless of the package's platform
    subdir, as codified by CEP-20.

### conda-forge style pins

By default the python dependency is a plain floor (e.g. `python >=3.12`),
which is solvable on any channel. conda-forge instead pins its abi3 packages
with `cpython >=3.12` (which excludes PyPy, whose C API layer does not
support the stable ABI) and `_python_abi3_support 1.*` (which additionally
excludes free-threaded python builds). Pass `--for-conda-forge` (or its
synonym `--for-cpython`) to add these pins:

```bash
whl2conda convert mypackage-1.0-cp312-abi3-macosx_11_0_arm64.whl \
    --allow-impure --for-conda-forge
```

Since the `cpython` and `_python_abi3_support` packages only exist on the
conda-forge channel, do not use this option for packages targeting channels
without them (e.g. Anaconda's `defaults`).

## Downloading binary wheels

You can download and convert binary wheels from PyPI in a single step using
the `--from-pypi` flag together with the download target options:

```bash
whl2conda convert --from-pypi markupsafe \
    --download-platform manylinux2014_x86_64 \
    --download-python-version 3.12 \
    --download-abi cp312
```

Using `--download-platform` automatically implies `--allow-impure`.

The download target options are:

| Option | Description | Example |
|--------|-------------|---------|
| `--download-platform` | Wheel platform tag | `manylinux2014_x86_64`, `macosx_11_0_arm64`, `win_amd64` |
| `--download-python-version` | Target Python version | `3.12` |
| `--download-abi` | Target ABI tag | `cp312` |

These options work with both `--from-pypi` and `--from-index` and are passed
through to `pip download`.

### Cross-platform downloads

You can download wheels for a different platform than the one you are running
on. For example, on macOS you can download and convert a Linux wheel:

```bash
whl2conda convert --from-pypi ujson \
    --download-platform manylinux2014_x86_64 \
    --download-python-version 3.12 \
    --download-abi cp312 \
    --out-dir conda-dist/
```

The target platform is determined by the wheel's platform tag, not the host OS.
To produce conda packages for multiple platforms, download and convert the
appropriate wheel for each one.

## Environment markers

When converting binary wheels, **whl2conda** evaluates platform-specific
environment markers on dependencies against the target platform. For example,
if a Linux wheel declares:

```
nvidia-cuda-runtime-cu12 >=12.0; platform_system == "Linux"
```

this dependency will be included in the converted conda package because the
marker matches the wheel's target platform. Dependencies whose markers do not
match the target (e.g. a Windows-only dependency in a Linux wheel) are excluded.

For pure Python (noarch) conversions, dependencies with environment markers
are still skipped, since noarch packages are platform-independent.

## What works well

Binary conversion is suited for **self-contained extension packages**,
where all compiled code (including any statically linked libraries) is
bundled in the wheel and the package's runtime dependencies are
available as conda packages. The comparison suite described below
verifies — on linux, macOS, and windows — that converted packages for
all of the following kinds of wheels are semantically equivalent to
the corresponding conda-forge packages:

- **C/C++ extensions** — e.g. markupsafe, wrapt, ujson, psutil
- **Cython extensions** — e.g. pyyaml, msgpack (including statically
  linked C libraries such as libyaml)
- **Rust extensions** — e.g. orjson, rpds-py
- **Stable ABI (abi3) extensions** — e.g. cryptography, bcrypt

## Validation against conda-forge

The whl2conda test suite includes an external comparison suite that
converts a curated sample of representative binary PyPI packages
(C extensions, Cython, stable-ABI and non-abi3 rust extensions, and
packages with bundled libraries) and semantically compares each result
against the real conda-forge package of the same version using
`whl2conda diff`. It runs monthly in CI and developers can run it with:

```bash
pixi run compare-conda-forge
```

This requires network access, downloads packages from PyPI and
anaconda.org (cached across runs), and writes a summary report to
`compare-report.md` / `compare-report.json`.

To vet your own conversion, compare it against a reference package
built from a recipe (if one exists) using
[`whl2conda diff`](testing.md#comparing-packages), and install and
test it with [`whl2conda install`](testing.md).

## Known limitations

The converter detects and refuses the known-bad cases it can identify:
wheels that are not pure python (without `--allow-impure`), unsupported
wheel platform tags, and local version suffixes (below). It warns about
wheels that bundle shared libraries. The remaining limitations listed
here are inherent to wheel conversion and are the user's responsibility
to evaluate.

### Local version suffixes

Wheels with local version suffixes (e.g. `torch-2.1.0+cu121`) indicate
custom build variants such as CUDA-specific builds. These are **blocked
with an error** because they bundle variant-specific libraries that
require careful dependency management not possible through simple wheel
conversion.

### Bundled shared libraries

Binary wheels repaired by tools like auditwheel, delocate, or
delvewheel bundle copies of the shared libraries they link against
(in `<package>.libs/` or `.dylibs/` directories). The converter
**warns** when it detects such vendored libraries. The converted
package includes these bundled copies as-is — unlike an equivalent
conda-forge package, which would declare shared library dependencies
instead — which can lead to:

- **Version conflicts** with conda-installed libraries
- **Missing transitive dependencies** not declared in the wheel metadata
- **ABI incompatibilities** when mixed with conda-forge packages

This usually *works* (the same copies are used from PyPI installs), but
duplicates libraries in the environment and bypasses conda's dependency
management for them.

### No `run_exports` or build metadata

Unlike conda-forge packages, converted wheels lack `run_exports` and detailed
build metadata. Downstream packages that depend on the converted package will
not automatically inherit correct library dependencies. You may need to manually
specify additional dependencies using the `-A`/`--add-dependency` flag
during conversion. *Not detected by the converter.*

### Dependencies must exist on the target channel

Dependency names are renamed using the standard pypi-to-conda rename
table (plus any project-specific renames), but the converter does not
verify that the resulting conda packages actually exist on the channel
you will install from. A missing or incorrectly named dependency only
surfaces when the package is installed. *Not detected by the converter* —
test with [`whl2conda install`](testing.md).

### Multi-platform (fat) macOS wheels

macOS wheels may support several platforms at once: `universal2` wheels
contain both x86_64 and arm64 code, and some wheels are tagged for
`x86_64`, `arm64`, *and* `universal2` simultaneously. Conversion produces
a single conda package for one platform: the platform matching the
current system is preferred; otherwise a `universal2` wheel is converted
for `osx-arm64`. Use the `--platform-tag` option to select the target
platform explicitly:

```bash
whl2conda convert orjson-3.11.9-*.whl --allow-impure \
    --platform-tag macosx_10_15_x86_64
```

Alternatively, `--all-platforms` generates one package per supported
platform in a single conversion, writing each package into a
`<subdir>/` subdirectory of the output directory (packages for
different platforms cannot share a directory, since conda package
file names do not include the platform):

```bash
whl2conda convert orjson-3.11.9-*.whl --allow-impure --all-platforms
# -> out-dir/osx-64/orjson-3.11.9-py313_0.conda
#    out-dir/osx-arm64/orjson-3.11.9-py313_0.conda
```

### No pre-compiled `.pyc` files

Conda-forge packages typically include pre-compiled Python bytecode (`.pyc`
files) for faster first imports. Converted wheels do not include these because
wheels themselves omit `.pyc` files per
[PEP 427](https://peps.python.org/pep-0427/), and cross-platform conversions
cannot generate valid bytecode for a different Python version than the one
running the conversion. Conda will compile `.pyc` files at install time, so
this only affects first-import performance.
