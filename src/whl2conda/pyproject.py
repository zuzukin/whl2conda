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
Support for reading pyproject.toml file
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

import tomli

__all__ = [
    "CondaPackageFormat",
    "read_pyproject",
]


class CondaPackageFormat(enum.Enum):
    """
    Supported output package formats

    * V1: original conda format as .tar.bz2 file
    * V2: newer .conda format
    * TREE: dumps package out as a directory tree (for debugging)
    """

    V1 = ".tar.bz2"
    V2 = ".conda"
    TREE = ".tree"

    @classmethod
    def from_string(cls, name: str) -> CondaPackageFormat:
        """Convert string to CondaPackageFormat

        Arguments:
            name: either the enum name or a file extension, i.e.
                "V1"/".tar.bz2", "V2"/".conda", or "TREE"
        """
        try:
            return cls[name.upper()]
        except LookupError:
            return cls(name.lower)


@dataclass
class PyProjInfo:
    """
    Information parsed from pyproject.toml file
    """

    toml: Dict[str, Any]
    """raw toml dictionar"""

    build_backend: str = ""
    """build-system.build-backend value"""

    # whl2conda settings
    conda_name: str = ""
    """tool.whl2conda.conda-name - overrides name of conda package"""

    conda_format: Optional[CondaPackageFormat] = None
    """tool.whl2conda.conda-format - default conda package output format"""

    wheel_dir: Optional[Path] = None
    """tool.whl2conda.wheel-dir - override default wheel dist directory"""

    out_dir: Optional[Path] = None
    """tool.whl2conda.out-dir - override default package output directory"""

    dependency_rename: Sequence[Tuple[str, str]] = ()
    """tool.whl2conda.dependency-rename - map pip package names to conda package names
    
    This is a list of `<pattern>`/`<substitution>` strings, where `<pattern>` is
    a python regular expression to be applied to the wheel package name, and when
    matched is replaced using the `<substitution>` pattern which may refer to
    groups in the pattern.
    """
    extra_dependencies: Sequence[str] = ()
    """tool.whl2conda.extra-dependencies - additional conda dependencies
    """


def read_pyproject(path: Optional[Path]) -> PyProjInfo:
    """
    Reads information
    Args:
        path: a directory containing a `pyproject.toml` file or the file itself

    Returns:
        Parsed information from the pyproject file or else one with defaults.
    """
    if path is None:
        return PyProjInfo({})

    if path.is_dir():
        path = path.joinpath("pyproject.toml")
    if not path.is_file():
        return PyProjInfo({})

    toml = tomli.loads(path.read_text("utf8"))
    pyproj = PyProjInfo(toml)

    # TODO validate - values
    pyproj.build_backend = str(toml.get("build-system", {}).get("build-backend", ""))

    whl2conda = toml.get("tool", {}).get("whl2conda", {})
    pyproj.conda_name = whl2conda.get("conda-name", "")
    if wheel_dir := whl2conda.get("wheel-dir"):
        pyproj.wheel_dir = path.parent.joinpath(wheel_dir).absolute()
    if out_dir := whl2conda.get("out-dir"):
        pyproj.out_dir = path.parent.joinpath(out_dir).absolute()
    pyproj.dependency_rename = whl2conda.get("dependency-rename", ())
    pyproj.extra_dependencies = whl2conda.get("extra-dependencies", ())
    if conda_format := whl2conda.get("conda-format"):
        pyproj.conda_format = CondaPackageFormat(conda_format)

    return pyproj
