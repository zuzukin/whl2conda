#  Copyright 2023 Christopher Barber
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
#
"""
Test fixtures providing wheels and conda packages for tests
"""

import shutil
from pathlib import Path
from typing import Generator

import pytest

from whl2conda.cli.convert import convert_main, do_build_wheel

__all__ = [
    "markers_wheel",
    "project_dir",
    "setup_wheel",
    "simple_conda_package",
    "simple_wheel",
]

this_dir = Path(__file__).parent.absolute()
root_dir = this_dir.parent
project_dir = root_dir.joinpath("test-projects")
markers_project = project_dir.joinpath("markers")
simple_project = project_dir.joinpath("simple")
setup_project = project_dir.joinpath("setup")

# pylint: disable=redefined-outer-name


@pytest.fixture(scope="session")
def simple_wheel(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[Path, None, None]:
    """Provides pip wheel for "simple" test project"""
    distdir = tmp_path_factory.mktemp("dist")
    yield do_build_wheel(
        simple_project,
        distdir,
        no_deps=True,
        no_build_isolation=True,
        capture_output=True,
    )


@pytest.fixture(scope="session")
def simple_conda_package(
    simple_wheel: Path,
) -> Generator[Path, None, None]:
    """Provides conda package for "simple" test project"""
    # Use whl2conda build to create conda package
    convert_main([
        str(simple_wheel),
        "--batch",
        "--yes",
        "--quiet",
    ])
    yield list(simple_wheel.parent.glob("*.conda"))[0]


@pytest.fixture(scope="session")
def markers_wheel(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[Path, None, None]:
    """Provides pip wheel for "markers" test project"""
    distdir = tmp_path_factory.mktemp("dist")
    yield do_build_wheel(
        markers_project,
        distdir,
        no_deps=True,
        no_build_isolation=True,
        capture_output=True,
    )


@pytest.fixture(scope="session")
def setup_wheel(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[Path, None, None]:
    """Provides pip wheel for setup.py based test project"""
    # build in tmp dir to avoid leaving build cruft in source tree
    srcdir = tmp_path_factory.mktemp("setup-src")
    distdir = srcdir / "dist"
    shutil.copytree(setup_project, srcdir, dirs_exist_ok=True)
    yield do_build_wheel(
        srcdir,
        distdir,
        no_deps=True,
        no_build_isolation=False,
        capture_output=True,
    )
