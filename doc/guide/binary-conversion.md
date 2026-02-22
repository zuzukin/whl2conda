# Binary Wheel Conversion

!!! warning "Experimental"
    Binary wheel conversion is an experimental feature. The generated conda
    packages may not work correctly for all packages. Use with caution.

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

Binary conversion is best suited for **simple C/C++ extension packages** where
the wheel is self-contained — all compiled code is bundled in the wheel and
runtime dependencies are available as conda packages. Examples include:

- **markupsafe** — simple C speedups
- **wrapt** — C extension for decorators
- **ujson** — fast JSON parser
- **pyyaml** — YAML parser with C library (libyaml)
- **msgpack** — MessagePack serializer

## Known limitations

### Local version suffixes

Wheels with local version suffixes (e.g. `torch-2.1.0+cu121`) indicate
custom build variants such as CUDA-specific builds. These are blocked because
they bundle variant-specific libraries that require careful dependency
management not possible through simple wheel conversion.

### Bundled shared libraries

Binary wheels may bundle shared libraries (`.so`, `.dylib`, `.dll`) that
overlap with or conflict with libraries provided by other conda packages.
The converted package includes these bundled copies as-is, which can lead to:

- **Version conflicts** with conda-installed libraries
- **Missing transitive dependencies** not declared in the wheel metadata
- **ABI incompatibilities** when mixed with conda-forge packages

### No `run_exports` or build metadata

Unlike conda-forge packages, converted wheels lack `run_exports` and detailed
build metadata. Downstream packages that depend on the converted package will
not automatically inherit correct library dependencies.

### `universal2` macOS wheels

macOS `universal2` wheels (containing both x86_64 and arm64 code) are mapped
to `osx-arm64` only. There is currently no way to produce separate packages
for both architectures from a single universal2 wheel.

### No pre-compiled `.pyc` files

Conda-forge packages typically include pre-compiled Python bytecode (`.pyc`
files) for faster first imports. Converted wheels do not include these because
wheels themselves omit `.pyc` files per
[PEP 427](https://peps.python.org/pep-0427/), and cross-platform conversions
cannot generate valid bytecode for a different Python version than the one
running the conversion. Conda will compile `.pyc` files at install time, so
this only affects first-import performance.
