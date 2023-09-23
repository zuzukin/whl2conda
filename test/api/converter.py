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
Test fixtures for the converter module
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Union, Sequence, Optional, Generator

import pytest

from whl2conda.api.converter import DependencyRename, Wheel2CondaConverter
from whl2conda.cli.install import install_main
from whl2conda.impl.pyproject import CondaPackageFormat

from ..api.validator import PackageValidator

this_dir = Path(__file__).parent.absolute()
root_dir = this_dir.parent.parent
test_projects = root_dir / "test-projects"


class ConverterTestCase:
    """
    Runner for a test case
    """

    wheel_src: Union[Path, str]
    dependency_rename: Sequence[DependencyRename]
    extra_dependencies: Sequence[str]
    overwrite: bool
    package_name: str
    tmp_dir: Path
    project_dir: Path
    out_dir: Path
    pip_downloads: Path
    was_run: bool = False

    _converter: Optional[Wheel2CondaConverter] = None
    _validator_dir: Path
    _validator: PackageValidator

    @property
    def converter(self) -> Wheel2CondaConverter:
        """Converter instance, constructed on demand."""
        if self._converter is None:
            self._converter = Wheel2CondaConverter(self._get_wheel(), self.out_dir)
        assert self._converter is not None
        return self._converter

    def __init__(
        self,
        wheel_src: Union[Path, str],
        *,
        tmp_dir: Path,
        project_dir: Path,
        package_name: str = "",
        dependency_rename: Sequence[tuple[str, str]] = (),
        extra_dependencies: Sequence[str] = (),
        overwrite: bool = False,
    ) -> None:
        if not str(wheel_src).startswith("pypi:"):
            wheel_src = Path(wheel_src)
            assert wheel_src.exists()
        self.wheel_src = wheel_src
        self.dependency_rename = tuple(
            DependencyRename.from_strings(*dr) for dr in dependency_rename
        )
        self.extra_dependencies = tuple(extra_dependencies)
        self.overwrite = overwrite
        self.tmp_dir = tmp_dir
        self.project_dir = project_dir
        self.package_name = package_name
        assert tmp_dir.is_dir()
        self.out_dir = self.tmp_dir.joinpath("out")
        self.pip_downloads = self.tmp_dir / "pip-downloads"
        self.pip_downloads.mkdir(exist_ok=True)
        self._validator_dir = self.tmp_dir.joinpath("validator")
        if self._validator_dir.exists():
            shutil.rmtree(self._validator_dir)
        self._validator_dir.mkdir()
        self._validator = PackageValidator(self._validator_dir)

    def build(self, out_format: CondaPackageFormat = CondaPackageFormat.V2) -> Path:
        """Run the build test case"""
        self.was_run = True
        wheel_path = self._get_wheel()
        package_path = self._convert(out_format=out_format)
        self._validate(wheel_path, package_path)
        return package_path

    def install(self, pkg_file: Path) -> Path:
        """Install conda package file into new conda environment in test-env/ subdir"""
        test_env = self.tmp_dir.joinpath("test-env")
        install_main([str(pkg_file), "-p", str(test_env), "--yes", "--create"])
        return test_env

    def _convert(self, *, out_format: CondaPackageFormat) -> Path:
        converter = self.converter
        converter.dependency_rename = list(self.dependency_rename)
        converter.extra_dependencies = list(self.extra_dependencies)
        converter.package_name = self.package_name
        converter.overwrite = self.overwrite
        converter.out_format = out_format
        self._converter = converter
        return converter.convert()

    def _get_wheel(self) -> Path:
        if isinstance(self.wheel_src, Path):
            return self.wheel_src

        assert str(self.wheel_src).startswith("pypi:")
        spec = str(self.wheel_src)[5:]

        with tempfile.TemporaryDirectory(dir=self.pip_downloads) as tmpdir:
            download_dir = Path(tmpdir)
            try:
                subprocess.check_call(
                    ["pip", "download", spec, "--no-deps", "-d", str(download_dir)]
                )
            except subprocess.CalledProcessError as ex:
                pytest.skip(f"Cannot download {spec} from pypi: {ex}")
            downloaded_wheel = next(download_dir.glob("*.whl"))
            target_wheel = self.pip_downloads / downloaded_wheel.name
            if target_wheel.exists():
                target_wheel.unlink()
            shutil.copyfile(downloaded_wheel, target_wheel)

        return target_wheel

    def _validate(self, wheel_path: Path, package_path: Path) -> None:
        converter = self._converter
        assert converter is not None
        if not converter.dry_run:
            self._validator.validate(
                wheel_path,
                package_path,
                std_renames=converter.std_renames,
                renamed={
                    r.pattern.pattern: r.replacement for r in self.dependency_rename
                },
                extra=converter.extra_dependencies,
                keep_pip_dependencies=converter.keep_pip_dependencies,
                build_number=converter.build_number,
            )


class ConverterTestCaseFactory:
    """
    Factory for generating test case runners
    """

    tmp_path_factory: pytest.TempPathFactory
    tmp_path: Path
    project_dir: Path
    _cases: list[ConverterTestCase]

    def __init__(self, tmp_path_factory: pytest.TempPathFactory) -> None:
        self.tmp_path_factory = tmp_path_factory
        self.tmp_path = tmp_path_factory.mktemp("converter-test-cases-")
        orig_project_dir = root_dir.joinpath("test-projects")
        self.project_dir = self.tmp_path.joinpath("projects")
        shutil.copytree(orig_project_dir, self.project_dir, dirs_exist_ok=True)
        self._cases = []

    def __call__(
        self,
        wheel_src: Union[Path, str],
        *,
        package_name: str = "",
        dependency_rename: Sequence[tuple[str, str]] = (),
        extra_dependencies: Sequence[str] = (),
        overwrite: bool = False,
    ) -> ConverterTestCase:
        case = ConverterTestCase(
            wheel_src,
            tmp_dir=self.tmp_path,
            package_name=package_name,
            project_dir=self.project_dir,
            dependency_rename=dependency_rename,
            extra_dependencies=extra_dependencies,
            overwrite=overwrite,
        )
        self._cases.append(case)
        return case

    def teardown(self) -> None:
        """Make sure all test cases were actually run"""
        for i, case in enumerate(self._cases):
            assert case.was_run, f"Test case #{i} was not run"


@pytest.fixture
def test_case(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[ConverterTestCaseFactory, None, None]:
    """
    Yields a TestCaseFactory for creating test cases
    """
    factory = ConverterTestCaseFactory(tmp_path_factory)
    yield factory
    factory.teardown()
