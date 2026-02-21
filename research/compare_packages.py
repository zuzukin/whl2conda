#!/usr/bin/env python3
"""
Compare binary wheel packages from PyPI with their conda-forge equivalents.

Downloads and extracts both formats, then reports on structural differences
in file layout, metadata, platform encoding, and dependencies.

Usage:
    pixi run python research/compare_packages.py [package_names...]

If no packages specified, compares a default set of binary packages.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# Default packages to compare - diverse mix of binary package types
DEFAULT_PACKAGES = [
    "markupsafe",   # simple C extension
    "wrapt",        # simple C extension
    "pyyaml",       # Cython-based
    "msgpack",      # Cython-based
    "ujson",        # simple C extension, no deps
    "lxml",         # complex, links external libs
]


@dataclass
class WheelInfo:
    """Extracted information from a wheel package."""
    path: Path
    filename: str
    name: str
    version: str
    python_tag: str
    abi_tag: str
    platform_tag: str
    files: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    wheel_metadata: dict[str, str] = field(default_factory=dict)
    record: list[str] = field(default_factory=list)
    binary_files: list[str] = field(default_factory=list)
    data_dirs: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class CondaInfo:
    """Extracted information from a conda package."""
    path: Path
    filename: str
    name: str
    version: str
    build: str
    subdir: str
    index: dict = field(default_factory=dict)
    about: dict = field(default_factory=dict)
    files: list[str] = field(default_factory=list)
    binary_files: list[str] = field(default_factory=list)
    paths_json: dict = field(default_factory=dict)


def download_wheel(package: str, dest_dir: Path) -> Optional[Path]:
    """Download a binary wheel from PyPI for the current platform."""
    result = subprocess.run(
        [
            sys.executable, "-m", "pip", "download",
            "--no-deps",
            "--only-binary", ":all:",
            "--dest", str(dest_dir),
            package,
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  ERROR downloading wheel: {result.stderr.strip()}")
        return None

    # Find the downloaded wheel
    wheels = list(dest_dir.glob("*.whl"))
    if not wheels:
        print(f"  ERROR: no wheel found after download")
        return None
    return wheels[0]


def download_conda(package: str, dest_dir: Path) -> Optional[Path]:
    """Download a conda package from conda-forge for the current platform."""
    import platform as plat
    import urllib.request

    # Determine conda subdir from current platform
    machine = plat.machine()
    system = plat.system()
    if system == "Darwin" and machine == "arm64":
        subdir = "osx-arm64"
    elif system == "Darwin":
        subdir = "osx-64"
    elif system == "Linux" and machine == "x86_64":
        subdir = "linux-64"
    elif system == "Linux" and machine == "aarch64":
        subdir = "linux-aarch64"
    elif system == "Windows":
        subdir = "win-64"
    else:
        subdir = f"{system.lower()}-{machine}"

    # Use mamba repoquery to find the latest package URL
    result = subprocess.run(
        ["mamba", "repoquery", "search", package, "-c", "conda-forge", "--json"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  ERROR searching conda: {result.stderr.strip()}")
        return None

    try:
        data = json.loads(result.stdout)
        pkgs = data["result"]["pkgs"]
        # Filter to current subdir and py312
        py_ver = f"py{sys.version_info.major}{sys.version_info.minor}"
        candidates = [
            p for p in pkgs
            if p.get("subdir") == subdir and py_ver in p.get("build", "")
        ]
        if not candidates:
            # Fall back to any build for this subdir
            candidates = [p for p in pkgs if p.get("subdir") == subdir]
        if not candidates:
            print(f"  ERROR: no {subdir} package found for {package}")
            return None

        pkg_info = candidates[-1]  # latest
        url = pkg_info.get("url")
        fn = pkg_info.get("fn", "package.conda")

        if not url:
            # Construct URL from channel info
            url = f"https://conda.anaconda.org/conda-forge/{subdir}/{fn}"

        print(f"  Downloading: {fn}")
        dest_path = dest_dir / fn
        urllib.request.urlretrieve(url, dest_path)
        return dest_path

    except (json.JSONDecodeError, KeyError) as e:
        print(f"  ERROR parsing conda search results: {e}")
        return None


def extract_wheel_info(wheel_path: Path, extract_dir: Path) -> WheelInfo:
    """Extract and analyze a wheel package."""
    fname = wheel_path.name
    # Parse wheel filename: name-version(-build)?-pytag-abitag-platform.whl
    parts = fname.removesuffix(".whl").split("-")
    # Handle names with hyphens converted to underscores
    if len(parts) >= 5:
        platform_tag = parts[-1]
        abi_tag = parts[-2]
        python_tag = parts[-3]
        version = parts[-4]
        name = "-".join(parts[:-4])
    else:
        name = parts[0]
        version = parts[1] if len(parts) > 1 else "unknown"
        python_tag = parts[2] if len(parts) > 2 else "unknown"
        abi_tag = parts[3] if len(parts) > 3 else "unknown"
        platform_tag = parts[4] if len(parts) > 4 else "unknown"

    info = WheelInfo(
        path=wheel_path, filename=fname,
        name=name, version=version,
        python_tag=python_tag, abi_tag=abi_tag, platform_tag=platform_tag,
    )

    with zipfile.ZipFile(wheel_path) as zf:
        zf.extractall(extract_dir)
        info.files = sorted(zf.namelist())

    # Identify binary files
    binary_exts = {".so", ".dylib", ".dll", ".pyd"}
    info.binary_files = [
        f for f in info.files
        if any(f.endswith(ext) for ext in binary_exts)
        or ".cpython-" in f and f.endswith(".so")
    ]

    # Parse WHEEL metadata
    wheel_meta_files = [f for f in info.files if f.endswith("/WHEEL")]
    if wheel_meta_files:
        wheel_meta_path = extract_dir / wheel_meta_files[0]
        info.wheel_metadata = _parse_email_metadata(wheel_meta_path)

    # Parse METADATA
    metadata_files = [f for f in info.files if f.endswith("/METADATA")]
    if metadata_files:
        meta_path = extract_dir / metadata_files[0]
        info.metadata = _parse_email_metadata(meta_path)

    # Identify .data directories
    data_dirs = [f for f in info.files if ".data/" in f]
    for f in data_dirs:
        # e.g., package-1.0.data/scripts/foo -> scripts: [foo]
        match = re.search(r"\.data/([^/]+)/(.*)", f)
        if match:
            category = match.group(1)
            subpath = match.group(2)
            info.data_dirs.setdefault(category, []).append(subpath)

    return info


def extract_conda_info(conda_path: Path, extract_dir: Path) -> CondaInfo:
    """Extract and analyze a conda package."""
    fname = conda_path.name

    if fname.endswith(".conda"):
        _extract_conda_v2(conda_path, extract_dir)
    elif fname.endswith(".tar.bz2"):
        with tarfile.open(conda_path, "r:bz2") as tf:
            tf.extractall(extract_dir)
    else:
        raise ValueError(f"Unknown conda format: {fname}")

    # Parse filename
    base = fname.removesuffix(".conda").removesuffix(".tar.bz2")
    parts = base.rsplit("-", 2)
    name = parts[0] if len(parts) > 0 else "unknown"
    version = parts[1] if len(parts) > 1 else "unknown"
    build = parts[2] if len(parts) > 2 else "unknown"

    info = CondaInfo(
        path=conda_path, filename=fname,
        name=name, version=version, build=build,
        subdir="unknown",
    )

    # List all files
    info.files = sorted(
        str(p.relative_to(extract_dir))
        for p in extract_dir.rglob("*") if p.is_file()
    )

    # Binary files
    binary_exts = {".so", ".dylib", ".dll", ".pyd"}
    info.binary_files = [
        f for f in info.files
        if any(f.endswith(ext) for ext in binary_exts)
        or ".cpython-" in f and f.endswith(".so")
    ]

    # Parse index.json
    index_path = extract_dir / "info" / "index.json"
    if index_path.exists():
        info.index = json.loads(index_path.read_text())
        info.subdir = info.index.get("subdir", "unknown")

    # Parse about.json
    about_path = extract_dir / "info" / "about.json"
    if about_path.exists():
        info.about = json.loads(about_path.read_text())

    # Parse paths.json
    paths_path = extract_dir / "info" / "paths.json"
    if paths_path.exists():
        info.paths_json = json.loads(paths_path.read_text())

    return info


def _extract_conda_v2(conda_path: Path, extract_dir: Path) -> None:
    """Extract a .conda (v2) format package."""
    with zipfile.ZipFile(conda_path) as outer:
        for name in outer.namelist():
            if name.endswith(".tar.zst"):
                import zstandard
                data = outer.read(name)
                dctx = zstandard.ZstdDecompressor()
                decompressed = dctx.decompress(data, max_output_size=500_000_000)
                with tarfile.open(fileobj=__import__("io").BytesIO(decompressed)) as tf:
                    tf.extractall(extract_dir)
            elif name == "metadata.json":
                (extract_dir / name).write_bytes(outer.read(name))


def _parse_email_metadata(path: Path) -> dict[str, str]:
    """Parse RFC 822-style metadata file into a dict."""
    result: dict[str, str] = {}
    current_key = None
    for line in path.read_text().splitlines():
        if line.startswith(" ") or line.startswith("\t"):
            if current_key:
                result[current_key] += "\n" + line.strip()
        elif ":" in line:
            key, _, value = line.partition(":")
            current_key = key.strip()
            # Accumulate multi-valued headers
            if current_key in result:
                result[current_key] += "\n" + value.strip()
            else:
                result[current_key] = value.strip()
    return result


def compare_package(package: str, work_dir: Path) -> Optional[dict]:
    """Download and compare wheel vs conda package."""
    print(f"\n{'='*70}")
    print(f"Package: {package}")
    print(f"{'='*70}")

    pkg_dir = work_dir / package
    wheel_dir = pkg_dir / "wheel"
    conda_dir = pkg_dir / "conda"
    wheel_extract = pkg_dir / "wheel_extracted"
    conda_extract = pkg_dir / "conda_extracted"

    for d in [wheel_dir, conda_dir, wheel_extract, conda_extract]:
        d.mkdir(parents=True, exist_ok=True)

    # Download
    print(f"\nDownloading wheel from PyPI...")
    wheel_path = download_wheel(package, wheel_dir)
    if not wheel_path:
        return None

    print(f"Downloading conda package from conda-forge...")
    conda_path = download_conda(package, conda_dir)
    if not conda_path:
        return None

    # Extract and analyze
    print(f"\nAnalyzing wheel: {wheel_path.name}")
    wheel_info = extract_wheel_info(wheel_path, wheel_extract)

    print(f"Analyzing conda:  {conda_path.name}")
    conda_info = extract_conda_info(conda_path, conda_extract)

    # Report
    report = {}

    print(f"\n--- Wheel Tags ---")
    print(f"  Python: {wheel_info.python_tag}")
    print(f"  ABI:    {wheel_info.abi_tag}")
    print(f"  Platform: {wheel_info.platform_tag}")
    report["wheel_tags"] = {
        "python": wheel_info.python_tag,
        "abi": wheel_info.abi_tag,
        "platform": wheel_info.platform_tag,
    }

    print(f"\n--- Conda Metadata (index.json) ---")
    for key in ["name", "version", "build", "build_number", "subdir",
                "arch", "platform", "noarch", "depends", "constrains",
                "license", "timestamp"]:
        val = conda_info.index.get(key)
        if val is not None:
            print(f"  {key}: {val}")
    report["conda_index"] = conda_info.index

    print(f"\n--- Wheel Metadata ---")
    print(f"  Root-Is-Purelib: {wheel_info.wheel_metadata.get('Root-Is-Purelib', 'N/A')}")
    print(f"  Tag: {wheel_info.wheel_metadata.get('Tag', 'N/A')}")
    report["wheel_metadata"] = {
        "root_is_purelib": wheel_info.wheel_metadata.get("Root-Is-Purelib"),
        "tag": wheel_info.wheel_metadata.get("Tag"),
    }

    print(f"\n--- Binary Files ---")
    print(f"  Wheel ({len(wheel_info.binary_files)}):")
    for f in wheel_info.binary_files[:10]:
        print(f"    {f}")
    print(f"  Conda ({len(conda_info.binary_files)}):")
    for f in conda_info.binary_files[:10]:
        print(f"    {f}")
    report["binary_files"] = {
        "wheel": wheel_info.binary_files,
        "conda": conda_info.binary_files,
    }

    if wheel_info.data_dirs:
        print(f"\n--- Wheel .data Directories ---")
        for cat, files in wheel_info.data_dirs.items():
            print(f"  {cat}/: {len(files)} files")
            for f in files[:5]:
                print(f"    {f}")
        report["data_dirs"] = wheel_info.data_dirs

    print(f"\n--- Dependencies ---")
    wheel_deps = [
        line for line in (wheel_info.metadata.get("Requires-Dist", "") or "").split("\n")
        if line.strip()
    ]
    conda_deps = conda_info.index.get("depends", [])
    print(f"  Wheel Requires-Dist ({len(wheel_deps)}):")
    for d in wheel_deps[:10]:
        print(f"    {d}")
    print(f"  Conda depends ({len(conda_deps)}):")
    for d in conda_deps[:10]:
        print(f"    {d}")
    report["dependencies"] = {
        "wheel": wheel_deps,
        "conda": conda_deps,
    }

    # File count summary
    print(f"\n--- File Counts ---")
    print(f"  Wheel: {len(wheel_info.files)} files")
    print(f"  Conda: {len(conda_info.files)} files")

    # Show conda file layout (non-info)
    conda_content_files = [f for f in conda_info.files if not f.startswith("info/")]
    print(f"\n--- Conda Content Layout (non-info/) ---")
    # Show directory structure
    dirs = set()
    for f in conda_content_files:
        parts = Path(f).parts
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))
    for d in sorted(dirs)[:20]:
        count = sum(1 for f in conda_content_files if f.startswith(d + "/") or f == d)
        print(f"  {d}/ ({count} files)")

    report["file_counts"] = {
        "wheel": len(wheel_info.files),
        "conda": len(conda_info.files),
    }

    return report


def main():
    packages = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_PACKAGES

    work_dir = Path(tempfile.mkdtemp(prefix="whl2conda_research_"))
    print(f"Working directory: {work_dir}")

    results = {}
    for package in packages:
        try:
            result = compare_package(package, work_dir)
            if result:
                results[package] = result
        except Exception as e:
            print(f"\n  ERROR processing {package}: {e}")
            import traceback
            traceback.print_exc()

    # Summary
    print(f"\n\n{'='*70}")
    print(f"SUMMARY")
    print(f"{'='*70}")

    print(f"\nPlatform Tag Mapping (wheel -> conda):")
    for pkg, result in results.items():
        wt = result.get("wheel_tags", {})
        ci = result.get("conda_index", {})
        print(f"  {pkg}:")
        print(f"    wheel: {wt.get('python', '?')}-{wt.get('abi', '?')}-{wt.get('platform', '?')}")
        print(f"    conda: subdir={ci.get('subdir', '?')} arch={ci.get('arch', '?')} platform={ci.get('platform', '?')}")
        print(f"    conda build: {ci.get('build', '?')}")

    # Save full results
    results_path = work_dir / "results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull results saved to: {results_path}")
    print(f"Working directory: {work_dir}")


if __name__ == "__main__":
    main()
