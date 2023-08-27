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
Unit tests for whl2conda.pyproject module
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import tomlkit
from textwrap import dedent

from whl2conda.pyproject import CondaPackageFormat, read_pyproject


def test_conda_package_format():
    """Unit tests for CondaPackageFormat"""
    for val in CondaPackageFormat:
        assert CondaPackageFormat.from_string(val.name) is val
        assert CondaPackageFormat.from_string(val.name.lower()) is val
        assert CondaPackageFormat.from_string(val.value) is val
        assert CondaPackageFormat.from_string(val.value.upper()) is val

    with pytest.raises(ValueError):
        CondaPackageFormat.from_string("invalid")


def test_read_pyproject(tmp_path: Path) -> None:
    """Unit test for read_pyproject function"""
    proj_file = tmp_path.joinpath("pyproject.toml")
    with pytest.raises(FileNotFoundError):
        read_pyproject(proj_file)

    with pytest.raises(FileNotFoundError):
        read_pyproject(tmp_path)

    with pytest.raises(ValueError, match="lacks .toml"):
        read_pyproject(tmp_path.joinpath("pyproject.txt"))

    # test empty projectfile
    proj_file.write_text("")
    pyproj = read_pyproject(proj_file)
    assert pyproj.project_dir == tmp_path
    assert pyproj.toml_file == proj_file
    assert pyproj.toml == tomlkit.TOMLDocument()  # type: ignore
    assert pyproj.build_backend == ""
    assert pyproj.conda_name == ""
    assert pyproj.conda_format is None
    assert pyproj.wheel_dir is None
    assert pyproj.out_dir is None
    assert pyproj.dependency_rename == ()
    assert pyproj.extra_dependencies == ()

    pyproj2 = read_pyproject(tmp_path)
    assert pyproj2 == pyproj

    # write a sample file
    proj_file.write_text(
        dedent(
            r"""
            [build-system]
            requires = ["hatchling"]
            build-backend = "hatchling"
            
            [project]
            name = "widget"
            version = "1.2.3"
            
            [tool.whl2conda]
            conda-name = "pywidget"
            wheel-dir = "mydist"
            out-dir = "conda-dist"
            dependency-rename = [
                ["acme-(.*)", "acme.\\1"]
            ]
            extra-dependencies = [ "conda-only" ]
            conda-format = ".tar.bz2"
            """
        ),
        encoding="ascii",
    )

    pyproj3 = read_pyproject(tmp_path)
    assert pyproj3 != pyproj
    assert pyproj3.project_dir == tmp_path
    assert pyproj3.toml_file == proj_file
    assert pyproj3.toml is not None
    assert pyproj3.toml["project"]["name"] == "widget"  # type: ignore
    assert pyproj3.build_backend == "hatchling"
    assert pyproj3.conda_name == "pywidget"
    assert pyproj3.wheel_dir == tmp_path.joinpath("mydist")
    assert pyproj3.out_dir == tmp_path.joinpath("conda-dist")
    assert pyproj3.dependency_rename == (("acme-(.*)", r"acme.\1"),)
    assert pyproj3.extra_dependencies == ("conda-only",)
    assert pyproj3.conda_format is CondaPackageFormat.V1

    assert re.sub(*pyproj3.dependency_rename[0], "acme-frob") == "acme.frob"

    #
    # Test bad value warnings
    #

    def test_ignored(key: str, value: Any, expected_warning: str, is_value: bool = False) -> None:
        proj_file.write_text(
            dedent(
                f"""
                [tool.whl2conda]
                {key} = {repr(value)}
                """
            )
        )
        inval = "value in " if is_value else ""
        full_expected_warning = re.compile(
            f"Ignoring {inval}.*tool.whl2conda.{key}.*{expected_warning}",
            flags=re.MULTILINE | re.DOTALL,
        )
        with pytest.warns(match=full_expected_warning):
            read_pyproject(proj_file)

    for key in ["conda-name", "wheel-dir", "out-dir", "conda-format"]:
        test_ignored(key, 123, "value is not a string")

    test_ignored("conda-format", "V0", "not a valid conda output format")

    test_ignored(
        "dependency-rename",
        [123],
        "Expected pair of strings",
        is_value=True,
    )
    test_ignored(
        "dependency-rename",
        [["one", "two"], ["foo"]],
        "Expected pair of strings.*foo",
        is_value=True,
    )
    test_ignored(
        "dependency-rename",
        [["one", "two"], ["three", 4]],
        "Expected pair of strings.*4",
        is_value=True,
    )

    test_ignored("extra-dependencies", ["one", 42], "Expected string but got.*42", is_value=True)
