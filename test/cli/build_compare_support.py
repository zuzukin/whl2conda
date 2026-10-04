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
Support for the external `whl2conda build` comparison test suite.

Provides the manifest of open-source projects whose conda-forge
feedstock recipes are built with `whl2conda build`, and the logic for
fetching a project's feedstock recipe and source.
"""

from __future__ import annotations

import hashlib
import shutil
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from whl2conda.impl.recipe import RenderedRecipe, python_variant_indices

__all__ = [
    "BUILD_PROJECTS",
    "BuildCategory",
    "BuildProject",
    "SkipProject",
    "fetch_feedstock",
    "fetch_source",
    "select_variant_file",
]


#: Kind of binary package built by a project.
BuildCategory = Literal["c-ext", "c++", "cython"]


@dataclass(frozen=True)
class BuildProject:
    """A project in the external build comparison manifest."""

    feedstock: str
    """Feedstock name: the recipe comes from conda-forge/<feedstock>-feedstock."""

    category: BuildCategory

    ref: str = "main"
    """Git ref of the feedstock repository to build."""

    build_args: tuple[str, ...] = ()
    """Extra `whl2conda build` arguments."""

    extra_run_exports: tuple[str, ...] = ()
    """Reference-only deps to treat as benign (e.g. statically linked libs)."""

    ignore: tuple[str, ...] = ()
    """Difference categories to ignore for this project."""

    ignore_paths: tuple[str, ...] = ()
    """Glob patterns for difference keys (e.g. file paths) to ignore."""

    xfail_reason: str = ""
    """If set, a failed build or unexpected differences are expected."""

    notes: str = ""


#: Sample of projects with binary conda-forge feedstock recipes whose
#: build script is a single `pip install .`, in both recipe formats.
BUILD_PROJECTS: tuple[BuildProject, ...] = (
    # v1 recipe.yaml feedstocks
    BuildProject("wrapt", "c-ext"),
    BuildProject("ujson", "c-ext"),
    BuildProject("msgpack-python", "cython"),
    BuildProject("lazy-object-proxy", "c-ext"),
    BuildProject("bitarray", "c-ext"),
    BuildProject("zope.interface", "c-ext"),
    BuildProject(
        "kiwisolver",
        "c++",
        build_args=("--build-isolation",),
        notes="needs the cppy build requirement from the recipe's host environment",
    ),
    # classic meta.yaml feedstocks
    BuildProject("regex", "c-ext"),
    BuildProject("tornado", "c-ext"),
    BuildProject(
        "pyrsistent",
        "c-ext",
        ignore_paths=("site-packages/pvectorc.*",),
        notes="the optional C extension uses a private function that"
        " python 3.13 does not declare: compilers that only warn about"
        " that build it, but those that reject it, like conda-forge's,"
        " leave it out",
    ),
    BuildProject("cytoolz", "cython"),
    BuildProject("multidict", "c-ext"),
    BuildProject("frozenlist", "cython"),
    BuildProject("simplejson", "c-ext"),
    BuildProject("markupsafe", "c-ext"),
)


class SkipProject(Exception):
    """The project cannot be built and compared in this environment."""


def _download(url: str, target: Path, timeout: float = 60.0) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=timeout) as response:
        target.write_bytes(response.read())
    return target


def _unpack(archive: Path, dest: Path) -> Path:
    """Unpack an archive, returning its single top level directory if any."""
    dest.mkdir(parents=True, exist_ok=True)
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive) as tar:
            tar.extractall(dest, filter="data")
    else:
        shutil.unpack_archive(archive, dest)
    entries = list(dest.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return dest


def fetch_feedstock(project: BuildProject, dest: Path) -> Path:
    """Download and unpack the project's conda-forge feedstock.

    Args:
        project: the project
        dest: directory in which to unpack the feedstock

    Returns:
        The root directory of the feedstock, which contains the
        `recipe/` and `.ci_support/` directories.
    """
    url = (
        f"https://github.com/conda-forge/{project.feedstock}-feedstock"
        f"/archive/{project.ref}.tar.gz"
    )
    archive = _download(url, dest / "feedstock.tar.gz")
    return _unpack(archive, dest / "feedstock")


def _is_free_threaded(python: str) -> bool:
    return python.strip().endswith("t")


def select_variant_file(feedstock_dir: Path, subdir: str) -> Path | None:
    """Select the feedstock's variant config file for this build.

    conda-forge feedstocks have variant config files in `.ci_support`
    for each platform. Python version specific packages either have a
    file for each python version, or a single file listing all of them.

    Args:
        feedstock_dir: root directory of the feedstock
        subdir: conda subdir to build for, e.g. `linux-64`

    Returns:
        The variant file for the subdir that includes the python version
        that builds the wheel, or is python version independent, or None
        if there is no such file. Files that select a noarch build of the
        package (`use_noarch`) are only used if there is no other.
    """
    prefix = subdir.replace("-", "_") + "_"
    candidates: list[tuple[bool, Path]] = []
    for config_file in sorted(feedstock_dir.joinpath(".ci_support").glob("*.yaml")):
        if not config_file.name.startswith(prefix) or "python_rc" in config_file.name:
            continue
        config = yaml.safe_load(config_file.read_text("utf8")) or {}
        pythons = [
            python
            for python in map(str, config.get("python") or ())
            if not _is_free_threaded(python)
        ]
        if config.get("python") and not python_variant_indices(pythons):
            continue
        use_noarch = any(
            str(value).lower() == "true" for value in config.get("use_noarch") or ()
        )
        candidates.append((use_noarch, config_file))
    # sorts files that do not select a noarch build first
    return min(candidates, default=(False, None))[1]


def _recipe_sources(rendered: RenderedRecipe) -> list[dict[str, Any]]:
    sources = rendered.raw.get("source") or ()
    if isinstance(sources, dict):
        sources = (sources,)
    return [source for source in sources if isinstance(source, dict)]


def fetch_source(rendered: RenderedRecipe, cache_dir: Path, dest: Path) -> Path:
    """Download and unpack the source of a rendered feedstock recipe.

    `whl2conda build` does not fetch recipe sources itself; it builds
    from the current directory when the recipe has no local source.

    Args:
        rendered: the rendered recipe
        cache_dir: directory in which source archives are cached
        dest: directory in which to unpack the source

    Returns:
        The root directory of the project source.

    Raises:
        SkipProject: if the recipe's source cannot be used.
    """
    sources = _recipe_sources(rendered)
    if len(sources) != 1 or not sources[0].get("url"):
        raise SkipProject("recipe does not have a single url source")
    source = sources[0]
    if source.get("patches"):
        raise SkipProject("recipe applies patches to its source")

    url = source["url"]
    if not isinstance(url, str):
        url = url[0]
    archive = cache_dir / url.rpartition("/")[2]
    if not archive.is_file():
        _download(url, archive)
    if sha256 := source.get("sha256"):
        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        if actual != str(sha256):
            archive.unlink()
            raise SkipProject(f"sha256 mismatch for {url}")
    return _unpack(archive, dest)
