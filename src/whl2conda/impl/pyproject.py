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
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

import tomlkit

__all__ = [
    "CondaPackageFormat",
    "PyProjInfo",
    "add_pyproject_defaults",
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
            return cls(name.lower())


@dataclass
class PyProjInfo:
    """
    Information parsed from pyproject.toml file
    """

    project_dir: Optional[Path] = None
    """Project root directory, if any."""

    toml_file: Optional[Path] = None
    """Path to pyproject.toml file, if any"""

    toml: Optional[tomlkit.TOMLDocument] = None
    """raw toml dictionary"""

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


def warn_ignored_key(file: Path, key: str, msg: str) -> None:
    """Warn about ignored key in pyproject.toml config"""
    warnings.warn(
        f"Ignoring pyproject key 'tool.whl2conda.{key}':\n {msg}\n from {file}",
        UserWarning,
    )


def warn_ignored_value(file: Path, key: str, msg: str) -> None:
    """Warn about ignored value in key in pyproject.toml config"""
    warnings.warn(
        f"Ignoring value in pyproject key 'tool.whl2conda.{key}':\n {msg}\n from {file}",
        UserWarning,
    )


TOOL_DEFAULTS = {
    "conda-name": {
        "default": "",
        "comment": [
            "Overrides name of conda package generated by whl2conda",
            "If empty, default is taken from project.name",
        ],
    },
    "wheel-dir": {
        "default": "dist",
        "comment": [
            "The default directory for whl2conda to look for wheels.",
            "Specified relative to the project root.",
        ],
    },
    "out-dir": {
        "default": "",
        "comment": [
            "The default directory for writing conda packages",
            "If not specified, this will be the wheel directory.",
        ],
    },
    "conda-format": {
        "default": "V2",
        "comment": [
            "The default output conda package format.",
            "Valid values are:"
            '   "V1" / ".tar.bz2": original .tar.bz2 package format',
            '   "V2" / ".conda": new V2 .conda package format',
            '   "TREE":  output package as directory tree (debug)',
        ],
    },
    "dependency-rename": {
        "default": [],
        "comment": [
            "An optional list of pypi/conda rename patterns",
            'Each entry should be a two element list of the form',
            '   ["<pypi-name-pattern>", "<conda-name>"]',
            'Where <pypi-name-pattern> may either just be the pypi package name',
            'or is a Python regular expression that will match the full name,'
            'and where <conda-name> can contain subsitution expression,',
            'For example, to rename all `acme-<foo>` packages to `acme.<foo>`:',
            '   ["acme-(.*)", "acme.\\1]',
        ],
    },
    "extra-dependencies": {
        "default": [],
        "comment": ["An optional list of extra conda dependencies."],
    },
}


def add_pyproject_defaults(path: Union[Path, str]) -> None:
    """
    Add default tool.whl2conda entries to pyproject

    Args:
        path: path to directory or toml file. The special
            value 'out' will write to stdout. If a directory,
            will look for pyproject.toml in that direcdtory,
            if a file, must end in .toml.
    """
    toml = tomlkit.TOMLDocument()
    pyproj_file: Optional[Path] = None
    if path in {"out", "stdout"}:
        pyproj_file = None
    else:
        pyproj_file = Path(path).expanduser()
        if pyproj_file.is_dir():
            pyproj_file = pyproj_file.joinpath("pyproject.toml")
        if pyproj_file.suffix != ".toml":
            raise ValueError(f"Cannot write to non .toml file {pyproj_file}")
        if pyproj_file.is_file():
            toml = tomlkit.loads(pyproj_file.read_text("utf8"))

    tool = toml.setdefault("tool", tomlkit.table())
    whl2conda = tool.setdefault("whl2conda", tomlkit.table())
    for k, v in TOOL_DEFAULTS.items():
        if k not in whl2conda:  # pragma: no branch
            comments = v.get("comment")  # type: ignore
            if comments:  # pragma: no branch
                for comment in comments:
                    whl2conda.add(tomlkit.comment(comment))
            whl2conda.add(k, v.get("default"))  # type: ignore

    new_contents = tomlkit.dumps(toml)
    if pyproj_file:
        pyproj_file.write_text(new_contents, "utf8")
    else:
        print(new_contents)


# pylint: disable=too-many-branches,too-many-locals
def read_pyproject(path: Path) -> PyProjInfo:
    """
    Reads project information

    Args:
        path: a directory containing a `pyproject.toml` file or the file itself

    Returns:
        Parsed information from the pyproject file or else one with defaults.
    """
    if path.is_dir():
        project_dir = path
        toml_file = path.joinpath("pyproject.toml")
    else:
        toml_file = path
        project_dir = path.parent
        if toml_file.suffix != ".toml":
            raise ValueError(f"'{path}' lacks .toml suffix")

    toml = tomlkit.loads(toml_file.read_text("utf8"))
    pyproj = PyProjInfo(toml=toml, toml_file=toml_file, project_dir=project_dir)

    pyproj.build_backend = str(toml.get("build-system", {}).get("build-backend", ""))

    whl2conda = toml.get("tool", {}).get("whl2conda", {})

    def _read_str(key: str) -> str:
        s = whl2conda.get(key, "")
        if isinstance(s, str):
            return s
        warn_ignored_key(toml_file, key, f"value is not a string: {s}")
        return ""

    pyproj.conda_name = _read_str("conda-name")

    if wheel_dir := _read_str("wheel-dir"):
        pyproj.wheel_dir = project_dir.joinpath(wheel_dir).absolute()

    if out_dir := _read_str("out-dir"):
        pyproj.out_dir = project_dir.joinpath(out_dir).absolute()

    if renames := whl2conda.get("dependency-rename", ()):
        _renames: List[Tuple[str, str]] = []
        for entry in renames:
            try:
                k, v = entry
                if isinstance(k, str) and isinstance(v, str):
                    _renames.append((k, v))
                    continue
            except (TypeError, ValueError):
                pass
            warn_ignored_value(
                toml_file,
                "dependency-rename",
                f"Expected pair of strings but got '{entry}'",
            )
        pyproj.dependency_rename = tuple(_renames)

    if extra_deps := whl2conda.get("extra-dependencies", ()):
        _extra_deps: List[str] = []
        for dep in extra_deps:
            if isinstance(dep, str):
                _extra_deps.append(dep)
            else:
                warn_ignored_value(
                    toml_file, "extra-dependencies", f"Expected string but got '{dep}'"
                )
        pyproj.extra_dependencies = tuple(_extra_deps)

    if conda_format := _read_str("conda-format"):
        try:
            pyproj.conda_format = CondaPackageFormat.from_string(conda_format)
        except ValueError:
            warn_ignored_key(
                toml_file,
                "conda-format",
                f"{conda_format} is not a valid conda output format",
            )

    return pyproj
