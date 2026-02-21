# Binary Wheel → Conda Conversion: Research Findings

## Packages Compared

| Package | Type | Wheel Binary Files | Conda Binary Files | External Lib Deps |
|---------|------|-------------------|--------------------|-------------------|
| markupsafe | Simple C ext | 1 `.so` | 1 `.so` | None |
| wrapt | Simple C ext | 1 `.so` | 1 `.so` | None |
| pyyaml | Cython | 1 `.so` | 1 `.so` | `yaml >=0.2.5` |
| ujson | Simple C ext | 1 `.so` | 1 `.so` | `libcxx >=19` |
| lxml | Complex C ext | 7 `.so` | 7 `.so` | `libxml2`, `libxslt`, `libzlib` |

**Note:** `msgpack` on PyPI vs `msgpack-python` on conda-forge — the pip package `msgpack-python`
is a pure-python shim (0.5.0), while the real binary package is `msgpack`. The conda package
`msgpack-python` contains the actual C extension. This is a name mapping edge case.

## File Layout Mapping

### Key Finding: Simple prefix transformation

Wheel layout (flat under package name):
```
markupsafe/__init__.py
markupsafe/_speedups.cpython-313-darwin.so
MarkupSafe-3.0.3.dist-info/METADATA
```

Conda layout (prefixed with `lib/pythonX.Y/site-packages/`):
```
lib/python3.13/site-packages/markupsafe/__init__.py
lib/python3.13/site-packages/markupsafe/_speedups.cpython-313-darwin.so
lib/python3.13/site-packages/markupsafe-3.0.3.dist-info/METADATA
```

**Rule**: For non-pure packages, all wheel content goes into
`lib/python{major}.{minor}/site-packages/` (macOS/Linux) or
`Lib/site-packages/` (Windows), instead of the current noarch
behavior of placing files directly under `site-packages/`.

### `.data/` directory mapping

None of the examined packages used `.data/` directories in their wheels.
When present, the standard mapping would be:
- `{name}.data/scripts/*` → `bin/` (Unix) / `Scripts/` (Windows)  
- `{name}.data/headers/*` → `include/`
- `{name}.data/data/*` → root prefix

### Conda `__pycache__/` files

Conda packages include pre-compiled `.pyc` files in `__pycache__/` directories.
Wheels do not. The converter could optionally pre-compile `.py` files, or leave
this to the conda install process.

## Platform Tag Mapping

### Wheel tag → Conda `subdir`

| Wheel Platform Tag | Conda `subdir` | Conda `arch` | Conda `platform` |
|-------------------|----------------|-------------|------------------|
| `macosx_*_arm64` | `osx-arm64` | `arm64` | `osx` |
| `macosx_*_x86_64` | `osx-64` | `x86_64` | `osx` |
| `macosx_*_universal2` | `osx-arm64` OR `osx-64`* | varies | `osx` |
| `manylinux*_x86_64` | `linux-64` | `x86_64` | `linux` |
| `manylinux*_aarch64` | `linux-aarch64` | `aarch64` | `linux` |
| `win_amd64` | `win-64` | `x86_64` | `win` |

*`universal2` wheels contain both architectures — would need to pick the appropriate one
based on the target subdir, or convert for both.

### Wheel ABI/Python tag → Conda build string

Wheel tags: `cp313-cp313-macosx_11_0_arm64`  
Conda build: `py313h7d74516_0`

The conda build string pattern is `py{ver}{hash}_{build_number}` where:
- `{ver}` = Python major+minor (e.g., `313`)
- `{hash}` = 8-char hash (conda-build computes from dependencies; for whl2conda this can be arbitrary or computed)
- `{build_number}` = build iteration number (default `0`)

## Dependency Differences

### Python version pinning
Conda packages pin Python tightly:
```
python >=3.13,<3.14.0a0
python >=3.13,<3.14.0a0 *_cp313
python_abi 3.13.* *_cp313
```

For converted packages, we should derive this from the wheel's `cp3XX` tag:
- `cpXYZ` → `python >=X.Y,<X.(Y+1).0a0`
- Add `python_abi X.Y.* *_cpXYZ`

### Platform constraints
Conda packages include OS minimum version constraints:
- `__osx >=11.0` (from `macosx_11_0_*` tag)

### External library dependencies
Conda packages declare shared library deps that wheels bundle statically:
- pyyaml: `yaml >=0.2.5,<0.3.0a0` (libyaml)
- ujson: `libcxx >=19`
- lxml: `libxml2`, `libxslt`, `libzlib`

**Important**: Wheels typically bundle these libraries or link statically. The conda package
relies on conda-forge's shared library packages. When converting from wheel, we should NOT
add these dependencies since the wheel already has its libraries bundled.

## Conda `index.json` Fields for Binary Packages

For noarch (current):
```json
{
  "noarch": "python",
  "subdir": "noarch",
  "arch": null,
  "platform": null,
  "build": "py_0"
}
```

For binary (needed):
```json
{
  "subdir": "osx-arm64",
  "arch": "arm64",
  "platform": "osx",
  "build": "py313h0000000_0",
  "depends": [
    "python >=3.13,<3.14.0a0",
    "python_abi 3.13.* *_cp313"
  ]
}
```

Note: no `"noarch"` field should be present for binary packages.

## Conda `paths.json` for Binary Packages

Each file entry includes:
```json
{
  "_path": "lib/python3.13/site-packages/markupsafe/_speedups.cpython-313-darwin.so",
  "path_type": "hardlink",
  "sha256": "...",
  "size_in_bytes": 12345
}
```

Binary `.so` files have the same `path_type: "hardlink"` as Python files — no special handling needed.

## Proposed Mapping Rules for Implementation

### 1. Detect binary wheel
- Check `Root-Is-Purelib: false` in WHEEL metadata
- Parse platform tags from filename: `{name}-{ver}-{pytag}-{abitag}-{plattag}.whl`

### 2. Map platform
```python
PLATFORM_MAP = {
    "macosx_*_arm64": ("osx-arm64", "arm64", "osx"),
    "macosx_*_x86_64": ("osx-64", "x86_64", "osx"),
    "manylinux*_x86_64": ("linux-64", "x86_64", "linux"),
    "manylinux*_aarch64": ("linux-aarch64", "aarch64", "linux"),
    "musllinux*_x86_64": ("linux-64", "x86_64", "linux"),
    "musllinux*_aarch64": ("linux-aarch64", "aarch64", "linux"),
    "win_amd64": ("win-64", "x86_64", "win"),
    "win32": ("win-32", "x86", "win"),
}
```

### 3. Compute build string
```python
def build_string(python_tag: str, build_number: int = 0) -> str:
    # e.g., cp313 -> py313
    py_ver = python_tag.replace("cp", "py")
    hash_str = compute_hash(...)  # or use a placeholder like "h0000000"
    return f"{py_ver}{hash_str}_{build_number}"
```

### 4. File layout
- All wheel content → `lib/python{X.Y}/site-packages/` (Unix)
- All wheel content → `Lib/site-packages/` (Windows)
- `.data/scripts/*` → `bin/` (Unix) / `Scripts/` (Windows)
- `.data/headers/*` → `include/`

### 5. Python dependency generation
From `cp313` tag:
```python
depends = [
    f"python >={major}.{minor},<{major}.{minor+1}.0a0",
    f"python_abi {major}.{minor}.* *_cp{major}{minor}",
]
```
Plus any OS constraint from the platform tag (e.g., `__osx >=11.0` from `macosx_11_0`).
