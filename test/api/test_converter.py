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
import tempfile
from pathlib import Path
from typing import Generator, Optional, Sequence, Union

# third party
import pytest

# this package
from whl2conda.api.converter import (
    Wheel2CondaConverter,
    Wheel2CondaError,
    CondaPackageFormat,
    DependencyRename,
    RequiresDistEntry,
)
from whl2conda.cli.convert import do_build_wheel
from whl2conda.cli.install import install_main
from .validator import PackageValidator

from ..test_packages import simple_wheel  # pylint: disable=unused-import

this_dir = Path(__file__).parent.absolute()
root_dir = this_dir.parent.parent
test_projects = root_dir / "test-projects"

#
# Converter test fixture
#


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
        """Converter instance. Only valid after build() is called"""
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
        package_path = self._convert(wheel_path, out_format=out_format)
        self._validate(wheel_path, package_path)
        return package_path

    def install(self, pkg_file: Path) -> Path:
        """Install conda package file into new conda environment in test-env/ subdir"""
        test_env = self.tmp_dir.joinpath("test-env")
        install_main([str(pkg_file), "-p", str(test_env), "--yes", "--create"])
        return test_env

    def _convert(self, wheel_path: Path, *, out_format: CondaPackageFormat) -> Path:
        converter = Wheel2CondaConverter(wheel_path, self.out_dir)
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
        self._validator(wheel_path, package_path, std_renames=converter.std_renames)


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


# pylint: disable=redefined-outer-name

#
# RequiresdistEntry test cases
#


def check_dist_entry(entry: RequiresDistEntry) -> None:
    """Check invariants on RequiresDistEntr"""
    if not entry.marker:
        assert entry.generic
    if entry.extra_marker_name:
        assert 'extra' in entry.marker
        assert entry.extra_marker_name in entry.marker
    else:
        # technically, there COULD be an extra in another environment
        # expression, but it wouldn't make much sense
        assert 'extra' not in entry.marker
        if entry.marker:
            assert not entry.generic

    raw = str(entry)
    entry2 = RequiresDistEntry.parse(raw)
    assert entry == entry2


def test_requires_dist_entry() -> None:
    """Test RequiresDistEntry data structure"""
    entry = RequiresDistEntry.parse("foo")
    assert entry.name == "foo"
    assert not entry.extras
    assert not entry.version
    assert not entry.marker
    check_dist_entry(entry)

    entry2 = RequiresDistEntry.parse("foo >=1.2")
    assert entry != entry2
    assert entry2.name == "foo"
    assert entry2.version == ">=1.2"
    assert not entry2.extras
    assert not entry2.marker
    check_dist_entry(entry2)

    entry3 = RequiresDistEntry.parse("foo-bar [baz,blah]")
    assert entry3.name == "foo-bar"
    assert entry3.extras == ("baz", "blah")
    assert not entry3.version
    assert not entry3.marker
    check_dist_entry(entry3)

    entry4 = RequiresDistEntry.parse("frodo ; extra=='LOTR'")
    assert entry4.name == "frodo"
    assert entry4.extra_marker_name == "LOTR"
    assert entry4.marker == "extra=='LOTR'"
    assert not entry4.version
    assert not entry4.extras
    check_dist_entry(entry4)

    with pytest.raises(SyntaxError):
        RequiresDistEntry.parse("=123 : bad")


#
# DependencyRename test cases
#


def test_dependency_rename() -> None:
    """Unit tests for DependencyRename class"""
    r = DependencyRename.from_strings("foot", "bar")
    assert r.rename("foo") == ("foo", False)
    assert r.rename("foot") == ("bar", True)

    r = DependencyRename.from_strings("foot", "foot")
    assert r.rename("foot") == ("foot", True)

    r = DependencyRename.from_strings("acme-(.*)", r"acme.\1")
    assert r.rename("acme-stuff") == ("acme.stuff", True)

    r = DependencyRename.from_strings("acme-(?P<name>.*)", r"acme.\g<name>")
    assert r.rename("acme-widgets") == ("acme.widgets", True)

    r = DependencyRename.from_strings("(acme-)?(.*)", r"acme.$2")
    assert r.rename("acme-stuff") == ("acme.stuff", True)
    assert r.rename("stuff") == ("acme.stuff", True)

    r = DependencyRename.from_strings("(?P<name>.*)", r"${name}-foo")
    assert r.rename("stuff") == ("stuff-foo", True)

    # error cases

    with pytest.raises(ValueError, match="Bad dependency rename pattern"):
        DependencyRename.from_strings("[foo", "bar")
    with pytest.raises(ValueError, match="Bad dependency replacement"):
        DependencyRename.from_strings("foo", r"\1")
    with pytest.raises(ValueError, match="Bad dependency replacement"):
        DependencyRename.from_strings("foo(.*)", r"$2")
    with pytest.raises(ValueError, match="Bad dependency replacement"):
        DependencyRename.from_strings("foo(.*)", r"${name}")


#
# Converter test cases
#


def test_this(test_case: ConverterTestCaseFactory) -> None:
    """Test using this own project's wheel"""
    wheel_dir = test_case.tmp_path_factory.mktemp("test_this_wjheel_dir")
    do_build_wheel(root_dir, wheel_dir, no_build_isolation=True, capture_output=True)

    wheel_path = list(wheel_dir.glob("*"))[0]
    assert wheel_path.is_file()

    case = test_case(wheel_path)

    for fmt in CondaPackageFormat:
        case.build(fmt)


def test_simple_wheel(
    test_case: ConverterTestCaseFactory,
    simple_wheel: Path,
) -> None:
    """Test converting wheel from 'simple' project"""

    v2pkg = test_case(simple_wheel).build()
    assert v2pkg.suffix == ".conda"

    with pytest.raises(FileExistsError):
        test_case(simple_wheel).build()

    assert test_case(simple_wheel, overwrite=True).build() == v2pkg

    v1pkg = test_case(simple_wheel).build(CondaPackageFormat.V1)
    assert v1pkg.name.endswith(".tar.bz2")

    # Repack wheel with build number
    dest_dir = test_case.tmp_path / "number"
    subprocess.check_call(
        ["wheel", "unpack", str(simple_wheel), "--dest", str(dest_dir)]
    )
    unpack_dir = next(dest_dir.glob("*"))
    assert unpack_dir.is_dir()
    subprocess.check_call(
        [
            "wheel",
            "pack",
            str(unpack_dir),
            "--build-number",
            "42",
            "--dest",
            str(dest_dir),
        ]
    )
    build42whl = next(dest_dir.glob("*.whl"))

    test_case(
        build42whl,
        overwrite=True,
    ).build()


def test_poetry(
    test_case: ConverterTestCaseFactory,
    tmp_path: Path,
) -> None:
    """Unit test on simple poetry package"""
    poetry_dir = test_projects / "poetry"
    try:
        wheel = do_build_wheel(poetry_dir, tmp_path, capture_output=True)
    except subprocess.CalledProcessError as err:
        # TODO - look at captured output
        pytest.skip(str(err))
    pkg = test_case(wheel).build()
    # conda package name taken from project name
    assert pkg.name.startswith("poetry.example")


#
# External pypi tests
#


@pytest.mark.external
def test_pypi_tomlkit(test_case: ConverterTestCaseFactory):
    """
    Test tomlkit package from pypi
    """
    test_case("pypi:tomlkit").build()


@pytest.mark.external
def test_pypi_sphinx(test_case: ConverterTestCaseFactory):
    """
    Test sphinx package from pypi
    """
    test_case("pypi:sphinx").build()


@pytest.mark.external
def test_pypi_zstandard(test_case: ConverterTestCaseFactory):
    """
    Test zstandard package - not pure python
    """
    with pytest.raises(Wheel2CondaError, match="not pure python"):
        test_case("pypi:zstandard").build()


@pytest.mark.external
def test_pypi_colorama(test_case: ConverterTestCaseFactory):
    """
    Test colorama package
    """
    test_case(
        "pypi:colorama",
    ).build()


@pytest.mark.external
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
