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
"""
Unit tests for converter module
"""

from __future__ import annotations

# standard
import shutil
import subprocess
from pathlib import Path
from typing import Generator, Optional, Sequence, Tuple, Union

# third party
import pytest

# this package
from whl2conda.api.converter import (
    Wheel2CondaConverter,
    Wheel2CondaError,
    CondaPackageFormat,
)
from whl2conda.cli.install import install_main
from .validator import PackageValidator

this_dir = Path(__file__).parent.absolute()
root_dir = this_dir.parent
projects_dir = this_dir.joinpath("projects")


class ConverterTestCase:
    """
    Runner for a test case
    """

    wheel_src: Union[Path, str]
    dependency_rename: Sequence[Tuple[str, str]]
    extra_dependencies: Sequence[str]
    package_name: str
    tmp_dir: Path

    _converter: Optional[Wheel2CondaConverter] = None
    _source_dir: Path
    _wheel_path: Path
    _out_dir: Path
    _validator_dir: Path
    _validator: PackageValidator

    @property
    def converter(self) -> Wheel2CondaConverter:
        """Converter instance. Only valid after build() is called"""
        assert self._converter is not None
        return self._converter

    def __init__(
        self,
        wheel_src: Union[Path, str],
        *,
        tmp_dir: Path,
        package_name: str = "",
        dependency_rename: Sequence[Tuple[str, str]] = (),
        extra_dependencies: Sequence[str] = (),
    ) -> None:
        if not str(wheel_src).startswith("pypi:"):
            wheel_src = Path(wheel_src)
            assert wheel_src.exists()
        self.wheel_src = wheel_src
        self.dependency_rename = tuple(dependency_rename)
        self.extra_dependencies = tuple(extra_dependencies)
        self.tmp_dir = tmp_dir
        self.package_name = package_name
        assert tmp_dir.is_dir()
        self._source_dir = self.tmp_dir.joinpath("source")
        self._source_dir.mkdir()
        self._wheel_path = self._source_dir.joinpath("?.whl")  # placeholder
        self._out_dir = self.tmp_dir.joinpath("out")
        self._out_dir.mkdir()
        self._validator_dir = self.tmp_dir.joinpath("validator")
        self._validator_dir.mkdir()
        self._validator = PackageValidator(self._validator_dir)

    def build(self, out_format: CondaPackageFormat = CondaPackageFormat.V2) -> Path:
        """Run the build test case"""
        self._clean()
        wheel_path = self._get_wheel()
        package_path = self._convert(wheel_path, out_format=out_format)
        self._validate(wheel_path, package_path)
        return package_path

    def install(self, pkg_file: Path) -> Path:
        """Install conda package file into new conda environment in test-env/ subdir"""
        test_env = self.tmp_dir.joinpath("test-env")
        install_main([str(pkg_file), "-p", str(test_env), "--yes", "--create"])
        return test_env

    def _clean(self) -> None:
        shutil.rmtree(self._source_dir, ignore_errors=True)
        self._source_dir.mkdir()
        shutil.rmtree(self._out_dir, ignore_errors=True)
        self._out_dir.mkdir()

    def _convert(self, wheel_path: Path, *, out_format: CondaPackageFormat) -> Path:
        converter = Wheel2CondaConverter(wheel_path, out_dir=self._out_dir)
        converter.dependency_rename = list(self.dependency_rename)
        converter.extra_dependencies = list(self.extra_dependencies)
        converter.package_name = self.package_name
        converter.out_format = out_format
        self._converter = converter
        return converter.convert()

    def _get_wheel(self) -> Path:
        if isinstance(self.wheel_src, Path):
            self._wheel_path = self._source_dir.joinpath(self.wheel_src.name)
            if self.wheel_src.is_file():
                shutil.copyfile(self.wheel_src, self._wheel_path)
            else:
                shutil.copytree(self.wheel_src, self._wheel_path)
        else:
            assert str(self.wheel_src).startswith("pypi:")
            spec = str(self.wheel_src)[5:]

            try:
                subprocess.check_call(
                    ["pip", "download", spec, "--no-deps", "-d", str(self._source_dir)]
                )
            except subprocess.CalledProcessError as ex:
                pytest.skip(f"Cannot download {spec} from pypi: {ex}")
            self._wheel_path = next(self._source_dir.glob("*.whl"))

        return self._wheel_path

    def _validate(self, wheel_path: Path, package_path: Path) -> None:
        converter = self._converter
        assert converter is not None
        self._validator(wheel_path, package_path, std_renames=converter.std_renames)


class ConverterTestCaseFactory:
    """
    Factory for generating test case runners
    """

    tmp_path_factory: pytest.TempPathFactory

    def __init__(self, tmp_path_factory: pytest.TempPathFactory) -> None:
        self.tmp_path_factory = tmp_path_factory

    def __call__(
        self,
        wheel_src: Union[Path, str],
        *,
        package_name: str = "",
        dependency_rename: Sequence[Tuple[str, str]] = (),
        extra_dependencies: Sequence[str] = (),
    ) -> ConverterTestCase:
        return ConverterTestCase(
            wheel_src,
            tmp_dir=self.tmp_path_factory.mktemp("whl2conda-test-case-"),
            package_name=package_name,
            dependency_rename=dependency_rename,
            extra_dependencies=extra_dependencies,
        )


@pytest.fixture
def test_case(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[ConverterTestCaseFactory, None, None]:
    """
    Yields a TestCaseFactory for creating test cases
    """
    yield ConverterTestCaseFactory(tmp_path_factory)


# pylint: disable=redefined-outer-name


def test_this(test_case: ConverterTestCaseFactory) -> None:
    """Test using this own project's wheel"""
    wheel_dir = test_case.tmp_path_factory.mktemp("test_this_wheel_dir")
    subprocess.check_call(
        [
            "pip",
            "wheel",
            str(root_dir),
            "--no-deps",
            "--no-build-isolation",
            "-w",
            str(wheel_dir),
        ]
    )

    wheel_path = list(wheel_dir.glob("*"))[0]
    assert wheel_path.is_file()

    case = test_case(wheel_path)

    for fmt in CondaPackageFormat:
        case.build(fmt)


# TODO support building wheel in test
# def test_simple(test_case: ConverterTestCaseFactory):
#     test_case(projects_dir.joinpath("simple")).build()


def test_pypi_tomlkit(test_case: ConverterTestCaseFactory):
    """
    Test tomlkit package from pypi
    """
    test_case("pypi:tomlkit").build()


def test_pypi_sphinx(test_case: ConverterTestCaseFactory):
    """
    Test sphinx package from pypi
    """
    test_case("pypi:sphinx").build()


def test_pypi_zstandard(test_case: ConverterTestCaseFactory):
    """
    Test zstandard package - not pure python
    """
    with pytest.raises(Wheel2CondaError, match="not pure python"):
        test_case("pypi:zstandard").build()


def test_pypi_colorama(test_case: ConverterTestCaseFactory):
    """
    Test colorama package
    """
    test_case(
        "pypi:colorama",
    ).build()


@pytest.mark.slow
def test_pypi_orix(test_case: ConverterTestCaseFactory) -> None:
    """
    Test orix package
    """
    case = test_case("pypi:orix")
    orix_pkg = case.build()
    assert orix_pkg.is_file()

    test_env = case.install(orix_pkg)

    subprocess.check_call(["conda", "install", "-p", str(test_env), "pytest", "--yes"])

    subprocess.check_call(
        [
            "conda",
            "run",
            "-p",
            str(test_env),
            "pytest",
            "--pyargs",
            "orix.tests",
            "-k",
            "not test_restrict_to_fundamental_sector",
        ]
    )
