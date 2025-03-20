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
from typing import Any, Mapping

import pytest
import tomlkit
from textwrap import dedent

from whl2conda.impl.pyproject import (
    CondaPackageFormat,
    read_pyproject,
    add_pyproject_defaults,
    PyProjInfo,
)


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
        dedent(r"""
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
                ["acme-(.*)", "acme.$1"]
            ]
            extra-dependencies = [ "conda-only" ]
            conda-format = ".tar.bz2"
            """),
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
    assert pyproj3.dependency_rename == (("acme-(.*)", r"acme.$1"),)
    assert pyproj3.extra_dependencies == ("conda-only",)
    assert pyproj3.conda_format is CondaPackageFormat.V1

    #
    # Test poetry name
    #
    proj_file.write_text(
        dedent(r"""
            [build-system]
            requires = ["poetry-core<2.0","setuptools"]
            build-backend = "poetry.core.masonry.api"
            
            [tool.poetry]
            name = "poetry.example"
            version = "1.0.2"
            """),
        encoding="ascii",
    )
    pyproj4 = read_pyproject(tmp_path)
    assert pyproj4.name == "poetry.example"

    proj_file.write_text(
        dedent(r"""
            [build-system]
            requires = ["poetry-core>=.0","setuptools"]
            build-backend = "poetry.core.masonry.api"

            [project]
            name = "poetry.example"
            version = "1.0.2"

            [tool.poetry]
            name = "obsolete-name"
            version = "1.0.2"
            """),
        encoding="ascii",
    )
    pyproj5 = read_pyproject(tmp_path)
    assert pyproj5.name == "poetry.example"

    #
    # Test bad value warnings
    #

    def test_ignored(
        key: str, value: Any, expected_warning: str, is_value: bool = False
    ) -> None:
        proj_file.write_text(
            dedent(f"""
                [tool.whl2conda]
                {key} = {repr(value)}
                """)
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

    test_ignored(
        "extra-dependencies", ["one", 42], "Expected string but got.*42", is_value=True
    )


def test_add_pyproject_defaults(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Unit test for add_pyproject_defaults functions="""

    add_pyproject_defaults('out')
    out, err = capsys.readouterr()
    assert not err

    out_file = tmp_path.joinpath("out.toml")
    out_file.write_text(out)

    pyproj_out = read_pyproject(out_file)

    def _assert_all_defaults(pyproj: PyProjInfo):
        assert not pyproj.conda_name
        assert not pyproj.out_dir
        assert pyproj.wheel_dir == tmp_path.joinpath("dist")
        assert pyproj.conda_format == CondaPackageFormat.V2
        assert not pyproj.dependency_rename
        assert not pyproj.extra_dependencies

        section = pyproj.toml["tool"]["whl2conda"]  # type: ignore
        assert isinstance(section, Mapping)
        assert "conda-name" in section
        assert "wheel-dir" in section
        assert "out-dir" in section
        assert "conda-format" in section
        assert "dependency-rename" in section
        assert "extra-dependencies" in section

    _assert_all_defaults(pyproj_out)

    add_pyproject_defaults(tmp_path)
    pyproj_file = tmp_path.joinpath("pyproject.toml")
    assert pyproj_file.is_file()

    pyproj2 = read_pyproject(pyproj_file)
    _assert_all_defaults(pyproj2)

    assert pyproj2.toml is not None
    pyproj2.toml["tool"]["whl2conda"]["conda-name"] = "foobar"  # type: ignore
    del pyproj2.toml["tool"]["whl2conda"]["wheel-dir"]  # type: ignore
    pyproj_file.write_text(tomlkit.dumps(pyproj2.toml))

    pyproj3 = read_pyproject(pyproj_file)
    assert pyproj3.conda_name == "foobar"
    assert not pyproj3.wheel_dir

    add_pyproject_defaults(str(pyproj_file))
    pyproj4 = read_pyproject(pyproj_file)
    assert pyproj4.conda_name == "foobar"
    assert pyproj4.wheel_dir == tmp_path.joinpath("dist")

    with pytest.raises(ValueError):
        add_pyproject_defaults("foo.not-toml")
