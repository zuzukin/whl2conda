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
import email
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from time import sleep
from typing import Generator, Optional, Sequence, Union

# third party
import pytest
from wheel.wheelfile import WheelFile

# this package
from whl2conda.api.converter import (
    Wheel2CondaConverter,
    CondaPackageFormat,
    DependencyRename,
    RequiresDistEntry,
    Wheel2CondaError,
)
from whl2conda.cli.convert import do_build_wheel
from whl2conda.cli.install import install_main
from .validator import PackageValidator

from ..test_packages import (  # pylint: disable=unused-import
    setup_wheel,
    simple_wheel,
)

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

    if not entry.extra_marker_name:
        entry_with_extra = entry.with_extra('original')
        assert entry_with_extra != entry
        assert entry_with_extra.extra_marker_name == 'original'
        assert entry_with_extra.generic == entry.generic
        assert entry_with_extra.name == entry.name
        assert entry_with_extra.version == entry.version
        assert entry.marker in entry_with_extra.marker


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

    entry5 = RequiresDistEntry.parse("sam ; python_version >= '3.10'  ")
    assert entry5.name == "sam"
    assert entry5.marker == "python_version >= '3.10'"
    assert not entry5.extra_marker_name
    assert not entry5.version
    assert not entry5.extras
    assert not entry5.generic
    check_dist_entry(entry5)

    entry6 = RequiresDistEntry.parse(
        "bilbo ~=23.2 ; sys_platform=='win32' and extra=='dev'  "
    )
    assert entry6.name == "bilbo"
    assert entry6.version == "~=23.2"
    assert not entry6.extras
    assert entry6.marker == "sys_platform=='win32' and extra=='dev'"
    assert entry6.extra_marker_name == "dev"
    assert not entry6.generic
    check_dist_entry(entry6)

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

# TODO: test interactive ovewrite prompt
# TODO: test build number override
# TODO: test non-generic dependency warning
# TODO: test dropped dependency debug log
# TODO: test bad Requires-Dist entry (shouldn't happen in real life)
# TODO: test adding extra == original clause to non generic dist entry


def test_this(test_case: ConverterTestCaseFactory) -> None:
    """Test using this own project's wheel"""
    wheel_dir = test_case.tmp_path_factory.mktemp("test_this_wjheel_dir")
    do_build_wheel(root_dir, wheel_dir, no_build_isolation=True, capture_output=True)

    wheel_path = list(wheel_dir.glob("*"))[0]
    assert wheel_path.is_file()

    case = test_case(wheel_path)

    for fmt in CondaPackageFormat:
        case.build(fmt)


def test_setup_wheel(
    test_case: ConverterTestCaseFactory,
    setup_wheel: Path,
) -> None:
    """Tests converting wheel from 'setup' project"""
    v2pkg = test_case(setup_wheel).build()
    assert v2pkg.suffix == ".conda"


def test_keep_pip_dependencies(
    test_case: ConverterTestCaseFactory,
    setup_wheel: Path,
) -> None:
    """Test keeping pip dependencies in dist-info"""
    case = test_case(setup_wheel)
    case.converter.keep_pip_dependencies = True
    v1pkg = case.build(out_format=CondaPackageFormat.V1)
    assert v1pkg.name.endswith(".tar.bz2")


def test_simple_wheel(
    test_case: ConverterTestCaseFactory,
    simple_wheel: Path,
) -> None:
    """Test converting wheel from 'simple' project"""

    # Dry run should not create package
    case = test_case(simple_wheel)
    case.converter.dry_run = True
    v2pkg_dr = case.build()
    assert v2pkg_dr.suffix == ".conda"
    assert not v2pkg_dr.exists()

    # Normal run
    v2pkg = test_case(simple_wheel).build()
    assert v2pkg == v2pkg_dr

    # Do another dry run, show that old package not removed
    mtime = v2pkg.stat().st_mtime_ns
    sleep(0.01)
    case = test_case(simple_wheel, overwrite=True)
    case.converter.dry_run = True
    assert case.build() == v2pkg
    assert v2pkg.stat().st_mtime_ns == mtime

    with pytest.raises(FileExistsError):
        test_case(simple_wheel).build()

    assert test_case(simple_wheel, overwrite=True).build() == v2pkg

    v1pkg = test_case(simple_wheel).build(CondaPackageFormat.V1)
    assert v1pkg.name.endswith(".tar.bz2")

    treepkg = test_case(simple_wheel).build(CondaPackageFormat.TREE)
    assert treepkg.is_dir()
    with pytest.raises(FileExistsError):
        test_case(simple_wheel).build(CondaPackageFormat.TREE)
    test_case(simple_wheel, overwrite=True).build(CondaPackageFormat.TREE)

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

    test_case(
        simple_wheel,
        dependency_rename=[("numpy-quaternion", "quaternion2")],
        overwrite=True,
    ).build()


def test_debug_log(
    test_case: ConverterTestCaseFactory,
    simple_wheel: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test debug logging during conversion"""
    caplog.set_level("DEBUG")

    test_case(
        simple_wheel,
        extra_dependencies=["mypy"],
    ).build()

    messages: list[str] = []
    for record in caplog.records:
        if record.levelno == logging.DEBUG:
            messages.append(record.message)
    assert messages
    debug_out = "\n".join(messages)

    assert re.search(r"Extracted.*METADATA", debug_out)
    assert "Packaging info/about.json" in debug_out
    assert re.search(r"Skipping extra dependency.*pylint", debug_out)
    assert re.search(r"Dependency copied.*black", debug_out)
    assert re.search(r"Dependency renamed.*numpy-quaternion.*quaternion", debug_out)
    assert re.search(r"Dependency added.*mypy", debug_out)


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


def test_bad_wheels(
    test_case: ConverterTestCaseFactory,
    simple_wheel: Path,
    tmp_path: Path,
) -> None:
    """
    Test wheels that cannot be converter
    """
    good_wheel = WheelFile(simple_wheel)
    extract_dir = tmp_path / "extraxt"
    good_wheel.extractall(str(extract_dir))
    extract_info_dir = next(extract_dir.glob("*.dist-info"))

    WHEEL_file = extract_info_dir / 'WHEEL'
    WHEEL_msg = email.message_from_string(WHEEL_file.read_text("utf8"))

    #
    # write bad wheelversion
    #

    WHEEL_msg.replace_header("Wheel-Version", "999.0")
    WHEEL_file.write_text(WHEEL_msg.as_string())

    bad_version_wheel = tmp_path / "bad-version" / simple_wheel.name
    bad_version_wheel.parent.mkdir(parents=True)
    with WheelFile(str(bad_version_wheel), "w") as wf:
        wf.write_files(str(extract_dir))

    with pytest.raises(Wheel2CondaError, match="unsupported wheel version"):
        test_case(bad_version_wheel).build()

    case = test_case(bad_version_wheel)
    case.converter.dry_run = True
    with pytest.raises(Wheel2CondaError, match="unsupported wheel version"):
        case.build()

    #
    # impure wheel
    #

    WHEEL_msg.replace_header("Wheel-Version", "1.0")
    WHEEL_msg.replace_header("Root-Is-Purelib", "False")
    WHEEL_file.write_text(WHEEL_msg.as_string())

    impure_wheel = tmp_path / "impure" / simple_wheel.name
    impure_wheel.parent.mkdir(parents=True)
    with WheelFile(str(impure_wheel), "w") as wf:
        wf.write_files(str(extract_dir))

    with pytest.raises(Wheel2CondaError, match="not pure python"):
        test_case(impure_wheel).build()

    #
    # bad metadata version
    #

    WHEEL_msg.replace_header("Root-Is-Purelib", "True")
    WHEEL_file.write_text(WHEEL_msg.as_string())

    METADATA_file = extract_info_dir / 'METADATA'
    METADATA_msg = email.message_from_string(METADATA_file.read_text("utf8"))
    METADATA_msg.replace_header("Metadata-Version", "999.2")
    METADATA_file.write_text(METADATA_msg.as_string())

    bad_md_version_wheel = tmp_path / "bad-md-version" / simple_wheel.name
    bad_md_version_wheel.parent.mkdir(parents=True)
    with WheelFile(str(bad_md_version_wheel), "w") as wf:
        wf.write_files(str(extract_dir))

    with pytest.raises(Wheel2CondaError, match="unsupported metadata version"):
        test_case(bad_md_version_wheel).build()
