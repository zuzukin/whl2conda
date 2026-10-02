#  Copyright 2026 Christopher Barber
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
"""
Support for the conda-forge comparison test suite.

Provides the curated manifest of representative binary PyPI packages
and the logic for finding the newest version with both a compatible
binary wheel on PyPI and a matching conda-forge build.
"""

from __future__ import annotations

import dataclasses
import json
import re
import sys
import urllib.request
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import NamedTuple

from packaging.version import InvalidVersion, Version

from whl2conda.api.compare import ComparisonResult, Severity
from whl2conda.api.stdrename import load_std_renames
from whl2conda.impl.conda_forge import (
    CondaForgeBuild,
    native_conda_subdir,
    query_conda_forge_builds,
)

__all__ = [
    "COMPARISON_PACKAGES",
    "CommonVersion",
    "ComparisonPackage",
    "NoCommonVersion",
    "find_common_version",
    "ignore_paths",
]


@dataclass(frozen=True)
class ComparisonPackage:
    """A package in the conda-forge comparison manifest."""

    pypi_name: str
    category: str
    """One of: c-ext, cython, abi3, rust, bundled-libs, entry-points."""

    conda_name: str = ""
    """Conda package name; defaults via the stdrename table."""

    pinned_version: str = ""
    """Optional exact version to compare, overriding discovery."""

    xfail_reason: str = ""
    """If set, unexpected differences are expected (known limitation)."""

    extra_run_exports: tuple[str, ...] = ()
    """Reference-only deps to treat as benign (e.g. statically linked libs)."""

    ignore: tuple[str, ...] = ()
    """Difference categories to ignore for this package."""

    ignore_paths: tuple[str, ...] = ()
    """Glob patterns for difference keys (e.g. file paths) to ignore."""

    notes: str = ""

    def resolve_conda_name(self) -> str:
        """The conda-forge package name for this package."""
        if self.conda_name:
            return self.conda_name
        renames = load_std_renames()
        return renames.get(self.pypi_name, self.pypi_name)


#: Curated sample of binary packages that also exist on conda-forge,
#: covering the main kinds of binary wheels whl2conda may encounter.
COMPARISON_PACKAGES: tuple[ComparisonPackage, ...] = (
    ComparisonPackage("markupsafe", "c-ext"),
    ComparisonPackage("wrapt", "c-ext"),
    ComparisonPackage(
        "ujson",
        "c-ext",
        ignore_paths=("site-packages/ujson-stubs/__init__.py",),
        notes="the win_amd64 wheels ship a ujson-stubs/__init__.py"
        " that is not in the sdist-based conda-forge build",
    ),
    ComparisonPackage(
        "psutil",
        "c-ext",
        ignore=("file-content",),
        notes="conda-forge patches upstream python sources",
    ),
    ComparisonPackage(
        "pyyaml",
        "cython",
        extra_run_exports=("yaml",),
        notes="the wheel statically links libyaml",
    ),
    ComparisonPackage("msgpack", "cython"),
    ComparisonPackage(
        "cryptography",
        "abi3",
        extra_run_exports=("openssl",),
        notes="the wheel statically links OpenSSL",
    ),
    ComparisonPackage("bcrypt", "abi3"),
    ComparisonPackage("orjson", "rust"),
    ComparisonPackage("rpds-py", "rust"),
    ComparisonPackage(
        "lxml",
        "bundled-libs",
        xfail_reason="bundles libxml2/libxslt; conda-forge links shared libs",
    ),
    ComparisonPackage(
        "pillow",
        "bundled-libs",
        xfail_reason="bundles image libraries; conda-forge links shared libs",
    ),
)


def ignore_paths(result: ComparisonResult, patterns: tuple[str, ...]) -> None:
    """Demote differences whose key matches a pattern to EXPECTED."""
    if not patterns:
        return
    result.differences = [
        dataclasses.replace(d, severity=Severity.EXPECTED)
        if any(fnmatchcase(d.key, pattern) for pattern in patterns)
        else d
        for d in result.differences
    ]


class PyPIWheel(NamedTuple):
    """A binary wheel available on PyPI."""

    version: str
    filename: str
    url: str


class CommonVersion(NamedTuple):
    """A version available from both PyPI and conda-forge."""

    version: str
    wheel: PyPIWheel
    conda_build: CondaForgeBuild


class NoCommonVersion(Exception):
    """No version with both a compatible wheel and conda-forge build."""


# wheel platform tag patterns compatible with each conda subdir
_SUBDIR_WHEEL_PLATFORMS = {
    "linux-64": r"manylinux[\w.]*_x86_64",
    "linux-aarch64": r"manylinux[\w.]*_aarch64",
    "osx-64": r"macosx_\d+_\d+_(x86_64|universal2|intel)",
    "osx-arm64": r"macosx_\d+_\d+_(arm64|universal2)",
    "win-64": r"win_amd64",
    "win-arm64": r"win_arm64",
}

_WHEEL_FNAME_RE = re.compile(
    r"(?P<name>[^-]+(?:-[^-]+)*?)-(?P<version>[^-]+)(-(?P<build>\d[^-]*))?"
    r"-(?P<python>[^-]+)-(?P<abi>[^-]+)-(?P<platform>[^-]+)\.whl"
)


def _wheel_is_compatible(filename: str, subdir: str) -> bool:
    """True if the wheel runs on the current interpreter and subdir."""
    m = _WHEEL_FNAME_RE.fullmatch(filename)
    if not m:
        return False
    platform_re = _SUBDIR_WHEEL_PLATFORMS.get(subdir)
    if not platform_re or not any(
        re.fullmatch(platform_re, tag) for tag in m.group("platform").split(".")
    ):
        return False

    major, minor = sys.version_info[:2]
    python_tags = m.group("python").split(".")
    abi_tags = m.group("abi").split(".")
    if "abi3" in abi_tags:
        # stable ABI: works on any python >= the tagged version
        for tag in python_tags:
            if tm := re.fullmatch(r"cp(\d)(\d+)", tag):
                if (int(tm.group(1)), int(tm.group(2))) <= (major, minor):
                    return True
        return False
    # regular binary wheel: require an exact ABI match with the running
    # interpreter; this excludes free-threaded (cp313t) wheels
    return f"cp{major}{minor}" in abi_tags


def _pypi_wheels(pypi_name: str, subdir: str, timeout: float) -> dict[str, PyPIWheel]:
    """Map of version to a compatible binary wheel on PyPI."""
    url = f"https://pypi.org/pypi/{pypi_name}/json"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf8"))

    result: dict[str, PyPIWheel] = {}
    for version, files in data.get("releases", {}).items():
        for file_info in files:
            filename = file_info.get("filename", "")
            if file_info.get("yanked") or not filename.endswith(".whl"):
                continue
            if _wheel_is_compatible(filename, subdir):
                result[version] = PyPIWheel(version, filename, file_info["url"])
                break
    return result


def _wheel_is_abi3(filename: str) -> bool:
    """True if the wheel targets the stable ABI."""
    m = _WHEEL_FNAME_RE.fullmatch(filename)
    return m is not None and "abi3" in m.group("abi").split(".")


def _dep_spec(build: CondaForgeBuild, name: str) -> str | None:
    """Version/build part of the build's dependency on `name`, if any."""
    for dep in build.depends:
        dep_name, _, spec = dep.partition(" ")
        if dep_name == name:
            return spec
    return None


def _python_abi_tag(build: CondaForgeBuild) -> str | None:
    """The python_abi build tag of a build, e.g. `cp312` or `cp314t`."""
    spec = _dep_spec(build, "python_abi")
    if spec is None:
        return None
    return spec.rpartition("_")[2] or None


def _is_compatible_abi3_build(build: CondaForgeBuild) -> bool:
    """True for a CEP-20 abi3 build installable on the running python."""
    if _dep_spec(build, "_python_abi3_support") is None:
        return False
    cpython = _dep_spec(build, "cpython") or ""
    if m := re.search(r">=\s*(\d+)\.(\d+)", cpython):
        return (int(m.group(1)), int(m.group(2))) <= sys.version_info[:2]
    return True


def _select_conda_build(
    builds: list[CondaForgeBuild], version: str, subdir: str, *, abi3: bool = False
) -> CondaForgeBuild | None:
    """Best conda-forge build of the given version for the subdir.

    Only builds for the running python are considered: for regular wheels
    the build's python_abi must match the running (non-free-threaded)
    interpreter exactly. For abi3 wheels, CEP-20 abi3 builds installable
    on the running python are preferred, falling back to an exact
    python_abi match for packages built per python version.
    """
    candidates = [b for b in builds if b.version == version and b.subdir == subdir]
    py_abi = "cp{}{}".format(*sys.version_info[:2])
    matches = [b for b in candidates if _python_abi_tag(b) == py_abi]
    if abi3:
        matches = [b for b in candidates if _is_compatible_abi3_build(b)] or matches
    if not matches:
        return None
    return max(matches, key=lambda b: (b.build_number, b.filename))


def find_common_version(
    entry: ComparisonPackage,
    *,
    timeout: float = 30.0,
) -> CommonVersion:
    """Find the newest version on both PyPI and conda-forge.

    Only PyPI versions with a binary wheel compatible with the running
    interpreter and platform are considered, and only conda-forge
    builds for the native subdir.

    Raises:
        NoCommonVersion: if there is no matching version.
    """
    subdir = native_conda_subdir()
    wheels = _pypi_wheels(entry.pypi_name, subdir, timeout)
    if not wheels:
        raise NoCommonVersion(
            f"no compatible {entry.pypi_name} wheel on PyPI for {subdir}"
        )

    conda_name = entry.resolve_conda_name()
    builds = query_conda_forge_builds(conda_name, timeout=timeout)

    if entry.pinned_version:
        versions = [entry.pinned_version]
    else:

        def _version_key(version: str) -> Version:
            try:
                return Version(version)
            except InvalidVersion:
                return Version("0")

        versions = sorted(wheels, key=_version_key, reverse=True)

    for version in versions:
        wheel = wheels.get(version)
        if not wheel:
            continue
        conda_build = _select_conda_build(
            builds, version, subdir, abi3=_wheel_is_abi3(wheel.filename)
        )
        if conda_build:
            return CommonVersion(version, wheel, conda_build)

    raise NoCommonVersion(
        f"no common {entry.pypi_name}/{conda_name} version with a"
        f" compatible wheel and a conda-forge build for {subdir}"
        " and python {}.{}".format(*sys.version_info[:2])
    )
