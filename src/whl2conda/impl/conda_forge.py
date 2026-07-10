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
Utilities for querying and downloading conda-forge packages.

Uses the anaconda.org REST API, which avoids downloading full channel
repodata and does not require conda/mamba.
"""

from __future__ import annotations

# standard
import json
import platform
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "CondaForgeBuild",
    "download_conda_forge_package",
    "native_conda_subdir",
    "query_conda_forge_builds",
]

ANACONDA_API_URL = "https://api.anaconda.org"


@dataclass(frozen=True, slots=True)
class CondaForgeBuild:
    """A single package build available on the conda-forge channel."""

    name: str
    version: str
    build: str
    build_number: int
    subdir: str
    filename: str
    url: str


def query_conda_forge_builds(
    name: str,
    *,
    timeout: float = 30.0,
) -> list[CondaForgeBuild]:
    """Query available conda-forge builds of a package.

    Args:
        name: conda package name
        timeout: HTTP timeout in seconds

    Returns:
        List of available builds, in the order reported by anaconda.org
        (oldest first).

    Raises:
        urllib.error.HTTPError: on HTTP errors, e.g. 404 for an
            unknown package.
    """
    url = f"{ANACONDA_API_URL}/package/conda-forge/{name}/files"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        files = json.loads(response.read().decode("utf8"))

    builds: list[CondaForgeBuild] = []
    for entry in files:
        attrs = entry.get("attrs", {})
        subdir = attrs.get("subdir", "")
        basename = entry.get("basename", "")
        download_url = entry.get("download_url", "")
        if download_url.startswith("//"):
            download_url = "https:" + download_url
        builds.append(
            CondaForgeBuild(
                name=name,
                version=str(entry.get("version", "")),
                build=str(attrs.get("build", "")),
                build_number=int(attrs.get("build_number", 0)),
                subdir=subdir,
                filename=basename.rpartition("/")[2],
                url=download_url,
            )
        )
    return builds


def download_conda_forge_package(
    build: CondaForgeBuild,
    into: Path,
    *,
    timeout: float = 60.0,
) -> Path:
    """Download a conda-forge package file.

    Args:
        build: build to download, from [query_conda_forge_builds][(m).]
        into: directory into which the package file is written
        timeout: HTTP timeout in seconds

    Returns:
        Path of the downloaded package file.
    """
    into.mkdir(parents=True, exist_ok=True)
    target = into / build.filename
    with urllib.request.urlopen(build.url, timeout=timeout) as response:
        target.write_bytes(response.read())
    return target


def native_conda_subdir() -> str:
    """The conda subdir matching the current platform, e.g. `osx-arm64`."""
    machine = platform.machine().lower()
    if sys.platform.startswith("linux"):
        return {
            "x86_64": "linux-64",
            "aarch64": "linux-aarch64",
            "ppc64le": "linux-ppc64le",
        }.get(machine, f"linux-{machine}")
    if sys.platform == "darwin":
        return "osx-arm64" if machine == "arm64" else "osx-64"
    if sys.platform == "win32":
        return "win-arm64" if machine == "arm64" else "win-64"
    return f"{sys.platform}-{machine}"
