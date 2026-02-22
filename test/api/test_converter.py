#  Copyright 2023-2026 Christopher Barber
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
import logging
import platform
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path
from time import sleep

# third party
import pytest
from wheel.wheelfile import WheelFile

# this package
from whl2conda.api.converter import (
    CondaPackageFormat,
    CondaTargetInfo,
    DependencyRename,
    RequiresDistEntry,
    Wheel2CondaConverter,
    Wheel2CondaError,
    _os_constraint_from_platform_tag,
    _parse_platform_tag,
    _python_pin_from_version,
    _python_version_from_tag,
    normalize_pypi_name,
)
from whl2conda.api.stdrename import load_std_renames
from whl2conda.cli.convert import do_build_wheel

from ..test_packages import (  # noqa: F401
    markers_wheel,
    setup_wheel,
    simple_wheel,
)

# pylint: disable=unused-import
from .converter import (  # noqa: F401
    ConverterTestCaseFactory,
    test_case,
)

# pylint: enable=unused-import

this_dir = Path(__file__).parent.absolute()
root_dir = this_dir.parent.parent
test_projects = root_dir / "test-projects"

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

    # Test PEP 503 name normalization (#134)
    entry_underscore = RequiresDistEntry.parse("Foo_Bar >=1.0")
    assert entry_underscore.name == "foo-bar"

    entry_dot = RequiresDistEntry.parse("foo.bar.baz >=2.0")
    assert entry_dot.name == "foo-bar-baz"

    entry_mixed = RequiresDistEntry.parse("Foo_.Bar >=3.0")
    assert entry_mixed.name == "foo-bar"

    entry_upper = RequiresDistEntry.parse("MyPackage")
    assert entry_upper.name == "mypackage"


def test_normalize_pypi_name() -> None:
    """Test PEP 503 normalization of PyPI package names"""
    assert normalize_pypi_name("foo") == "foo"
    assert normalize_pypi_name("Foo-Bar") == "foo-bar"
    assert normalize_pypi_name("foo_bar") == "foo-bar"
    assert normalize_pypi_name("foo.bar") == "foo-bar"
    assert normalize_pypi_name("Foo_.Bar") == "foo-bar"
    assert normalize_pypi_name("FOO---BAR") == "foo-bar"
    assert normalize_pypi_name("typing_extensions") == "typing-extensions"


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

    # Test normalization in rename (#134)
    r = DependencyRename.from_strings("foo-bar", "conda-foo-bar")
    assert r.rename("foo_bar") == ("conda-foo-bar", True)
    assert r.rename("Foo.Bar") == ("conda-foo-bar", True)
    assert r.rename("foo-bar") == ("conda-foo-bar", True)

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

# ignore redefinition of test_case


def test_init(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test Whl2CondaConverter.__init__"""
    update_called = False

    def fake_update(*_args, **_kwargs) -> bool:
        nonlocal update_called
        update_called = True
        return True

    monkeypatch.setattr("whl2conda.api.stdrename.update_renames_file", fake_update)

    wheel_path = Path("wheel")
    out_dir = Path("out_dir")

    converter = Wheel2CondaConverter(wheel_path, out_dir)
    assert converter.wheel_path == wheel_path
    assert converter.out_dir == out_dir
    assert not converter.dependency_rename
    assert not converter.extra_dependencies
    assert not converter.package_name
    assert not converter.dry_run
    assert not converter.overwrite
    assert not converter.keep_pip_dependencies
    assert not converter.python_version
    assert not converter.interactive
    assert not converter.wheel_md
    assert not converter.conda_pkg_path
    assert converter.std_renames == load_std_renames(update=False)
    assert not update_called

    converter2 = Wheel2CondaConverter(wheel_path, out_dir, update_std_renames=True)
    assert converter2.wheel_path == wheel_path
    assert converter2.out_dir == out_dir
    assert update_called


def test_this(test_case: ConverterTestCaseFactory) -> None:
    """Test using this own project's wheel"""
    wheel_dir = test_case.tmp_path_factory.mktemp("test_this_wjheel_dir")
    do_build_wheel(root_dir, wheel_dir, no_build_isolation=True, capture_output=True)

    wheel_path = next(iter(wheel_dir.glob("*")))
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
    sleep_duration = 0.1 if platform.system() == "Windows" else 0.01
    sleep(sleep_duration)  # ensure mtime will be different if file is replaced
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
    subprocess.check_call([
        "wheel",
        "unpack",
        str(simple_wheel),
        "--dest",
        str(dest_dir),
    ])
    unpack_dir = next(dest_dir.glob("*"))
    assert unpack_dir.is_dir()
    subprocess.check_call([
        "wheel",
        "pack",
        str(unpack_dir),
        "--build-number",
        "42",
        "--dest",
        str(dest_dir),
    ])
    build42whl = next(dest_dir.glob("*.whl"))

    test_case(
        build42whl,
        overwrite=True,
    ).build()

    case = test_case(
        build42whl,
        overwrite=True,
    )
    case.converter.build_number = 23
    case.build()

    test_case(
        simple_wheel,
        dependency_rename=[("numpy-quaternion", "quaternion2")],
        overwrite=True,
    ).build()

    case = test_case(
        simple_wheel,
        overwrite=True,
    )
    case.converter.python_version = ">=3.9"
    case.build()


def test_debug_log(
    test_case: ConverterTestCaseFactory,
    simple_wheel: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test debug logging during conversion"""
    case = test_case(
        simple_wheel,
        extra_dependencies=["mypy"],
        dependency_rename=[("tables", "")],
        overwrite=True,
    )
    case.build()

    def get_debug_out() -> str:
        messages: list[str] = [
            record.message
            for record in caplog.records
            if record.levelno == logging.DEBUG
        ]
        return "\n".join(messages)

    debug_out = get_debug_out()
    assert not debug_out

    caplog.set_level("DEBUG")

    case.build()

    debug_out = get_debug_out()

    assert re.search(r"Extracted.*METADATA", debug_out)
    assert re.search(r"Packaging info[/\\]about\.json", debug_out)
    assert re.search(r"Skipping extra dependency.*pylint", debug_out)
    assert re.search(r"Dependency copied.*black", debug_out)
    assert re.search(r"Dependency renamed.*numpy-quaternion.*quaternion", debug_out)
    assert re.search(r"Dependency added.*mypy", debug_out)


def test_warnings(
    test_case: ConverterTestCaseFactory,
    markers_wheel: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Test conversion warnings
    """

    def get_warn_out() -> str:
        messages: list[str] = [
            record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
        ]
        return "\n".join(messages)

    test_case(markers_wheel).build()

    warn_out = get_warn_out()
    assert re.search(
        r"Skipping.*with.*marker.*typing-extensions ; python_version < '3.9'", warn_out
    )
    assert re.search(r"Skipping.*ntfsdump", warn_out)
    assert re.search(r"Skipping.*atomacos", warn_out)

    # Make wheel with bad Requires-Dist entries
    wheel = WheelFile(markers_wheel)
    bad_wheel_dir = test_case.tmp_path / "bad-wheel"
    wheel.extractall(bad_wheel_dir)
    distinfo_dir = next(bad_wheel_dir.glob("*.dist-info"))
    metadata_file = distinfo_dir / "METADATA"
    contents = metadata_file.read_text("utf8")
    # Add bogus !!! to Requires-Dist entries with markers
    contents = re.sub(r"Requires-Dist:(.*);", r"Requires-Dist:!!!\1;", contents)
    metadata_file.write_text(contents, encoding="utf8")
    bad_wheel_file = bad_wheel_dir / markers_wheel.name
    with WheelFile(str(bad_wheel_file), "w") as wf:
        wf.write_files(str(bad_wheel_dir))

    test_case(bad_wheel_file, overwrite=True).build()
    warn_out = get_warn_out()
    print(warn_out)


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
    assert pkg.name.startswith("poetry-example")


def test_poetry_2_1(
    test_case: ConverterTestCaseFactory,
    tmp_path: Path,
) -> None:
    """Unit test on simple poetry package"""
    poetry_dir = test_projects / "poetry-2.1"
    try:
        wheel = do_build_wheel(poetry_dir, tmp_path, capture_output=True)
    except subprocess.CalledProcessError as err:
        # TODO - look at captured output
        pytest.skip(str(err))
    pkg = test_case(wheel).build()
    # conda package name taken from project name
    assert pkg.name.startswith("poetry-example")


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
    WHEEL_msg = Wheel2CondaConverter.read_metadata_file(WHEEL_file)

    #
    # write bad wheelversion
    #

    WHEEL_msg.replace_header("Wheel-Version", "999.0")
    WHEEL_file.write_text(WHEEL_msg.as_string(), encoding="utf8")

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
    WHEEL_file.write_text(WHEEL_msg.as_string(), encoding="utf8")

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
    WHEEL_file.write_text(WHEEL_msg.as_string(), encoding="utf8")

    METADATA_file = extract_info_dir / 'METADATA'
    METADATA_msg = Wheel2CondaConverter.read_metadata_file(METADATA_file)
    METADATA_msg.replace_header("Metadata-Version", "999.2")
    METADATA_file.write_text(METADATA_msg.as_string(), encoding="utf8")

    bad_md_version_wheel = tmp_path / "bad-md-version" / simple_wheel.name
    bad_md_version_wheel.parent.mkdir(parents=True)
    with WheelFile(str(bad_md_version_wheel), "w") as wf:
        wf.write_files(str(extract_dir))

    with pytest.raises(Wheel2CondaError, match="unsupported metadata version"):
        test_case(bad_md_version_wheel).build()

    c = test_case(bad_md_version_wheel)
    c.converter.SUPPORTED_METADATA_VERSIONS += ("999.2",)
    c.build()

    #
    # Restore valid metadata for remaining tag tests
    #

    METADATA_msg.replace_header("Metadata-Version", "2.1")
    METADATA_file.write_text(METADATA_msg.as_string(), encoding="utf8")

    #
    # pure wheel with non-pure tag (e.g. cp312-cp312-linux_x86_64)
    #

    WHEEL_msg.replace_header("Tag", "cp312-cp312-linux_x86_64")
    WHEEL_file.write_text(WHEEL_msg.as_string(), encoding="utf8")

    non_any_tag_wheel = tmp_path / "non-any-tag" / simple_wheel.name
    non_any_tag_wheel.parent.mkdir(parents=True)
    with WheelFile(str(non_any_tag_wheel), "w") as wf:
        wf.write_files(str(extract_dir))

    with pytest.raises(Wheel2CondaError, match="unexpected tag"):
        test_case(non_any_tag_wheel).build()

    #
    # bad tag format (missing components)
    #

    WHEEL_msg.replace_header("Tag", "py3-none")  # only 2 parts
    WHEEL_file.write_text(WHEEL_msg.as_string(), encoding="utf8")

    bad_tag_wheel = tmp_path / "bad-tag" / simple_wheel.name
    bad_tag_wheel.parent.mkdir(parents=True)
    with WheelFile(str(bad_tag_wheel), "w") as wf:
        wf.write_files(str(extract_dir))

    case = test_case(bad_tag_wheel)
    case.allow_impure = True
    with pytest.raises(Wheel2CondaError, match="bad tag format"):
        case.build()


def test_overwrite_prompt(
    test_case: ConverterTestCaseFactory,
    simple_wheel: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Test interactive prompting for overwrite.
    """
    prompts: Iterator[str] = iter(())
    responses: Iterator[str] = iter(())

    # pylint: disable=duplicate-code
    def fake_input(prompt: str) -> str:
        expected_prompt = next(prompts)
        assert re.search(expected_prompt, prompt), (
            f"'{expected_prompt}' does not match prompt '{prompt}'"
        )
        return next(responses)

    monkeypatch.setattr("builtins.input", fake_input)

    case = test_case(simple_wheel)
    case.converter.interactive = False
    case.build()

    case.converter.interactive = True
    prompts = iter(["Overwrite?"])
    responses = iter(["no"])
    with pytest.raises(FileExistsError):
        case.build()

    case.converter.interactive = True
    prompts = iter(["Overwrite?"])
    responses = iter(["yes"])
    case.build()


def test_version_translation(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Test for Wheel2CondaConverter.translate_version_spec"""
    converter = Wheel2CondaConverter(tmp_path, tmp_path)
    for spec, expected in {
        "~= 1.2.3": ">=1.2.3,==1.2.*",
        "~=1": ">=1",
        ">=3.2 , ~=1.2.4.dev4": ">=3.2,>=1.2.4.dev4,==1.2.*",
        " >=1.2.3 , <4.0": ">=1.2.3,<4.0",
        " >v1.2+foo": ">1.2+foo",
    }.items():
        assert converter.translate_version_spec(spec) == expected

    caplog.clear()
    assert converter.translate_version_spec("bad-version") == "bad-version"
    assert len(caplog.records) == 1
    logrec = caplog.records[0]
    assert logrec.levelname == "WARNING"
    assert "Cannot convert bad version" in logrec.message

    caplog.clear()
    assert converter.translate_version_spec("===1.2.3") == "==1.2.3"
    assert len(caplog.records) == 1
    logrec = caplog.records[0]
    assert logrec.levelname == "WARNING"
    assert "Converted arbitrary equality" in logrec.message


#
# Binary conversion helper tests
#


def test_python_version_from_tag() -> None:
    """Test _python_version_from_tag helper."""
    assert _python_version_from_tag("cp313") == "3.13"
    assert _python_version_from_tag("cp39") == "3.9"
    assert _python_version_from_tag("cp310") == "3.10"
    assert _python_version_from_tag("py3") == "3"
    assert _python_version_from_tag("unknown") == "unknown"


def test_parse_platform_tag() -> None:
    """Test _parse_platform_tag helper."""
    assert _parse_platform_tag("macosx_11_0_arm64") == ("osx-arm64", "arm64", "osx")
    assert _parse_platform_tag("macosx_10_9_x86_64") == ("osx-64", "x86_64", "osx")
    assert _parse_platform_tag("macosx_11_0_universal2") == (
        "osx-arm64",
        "arm64",
        "osx",
    )
    assert _parse_platform_tag("manylinux2014_x86_64") == (
        "linux-64",
        "x86_64",
        "linux",
    )
    assert _parse_platform_tag("manylinux_2_17_aarch64") == (
        "linux-aarch64",
        "aarch64",
        "linux",
    )
    assert _parse_platform_tag("musllinux_1_1_x86_64") == (
        "linux-64",
        "x86_64",
        "linux",
    )
    assert _parse_platform_tag("win_amd64") == ("win-64", "x86_64", "win")
    assert _parse_platform_tag("win32") == ("win-32", "x86", "win")
    assert _parse_platform_tag("win_arm64") == ("win-arm64", "arm64", "win")

    with pytest.raises(Wheel2CondaError, match="Unsupported wheel platform tag"):
        _parse_platform_tag("unknown_platform")


def test_os_constraint_from_platform_tag() -> None:
    """Test _os_constraint_from_platform_tag helper."""
    assert _os_constraint_from_platform_tag("macosx_11_0_arm64") == "__osx >=11.0"
    assert _os_constraint_from_platform_tag("macosx_10_9_x86_64") == "__osx >=10.9"
    assert _os_constraint_from_platform_tag("macosx_14_0_arm64") == "__osx >=14.0"
    assert _os_constraint_from_platform_tag("manylinux2014_x86_64") == ""
    assert _os_constraint_from_platform_tag("win_amd64") == ""


def test_python_pin_from_version() -> None:
    """Test _python_pin_from_version helper."""
    pin = _python_pin_from_version("3.13")
    assert pin == [
        "python >=3.13,<3.14.0a0",
        "python_abi 3.13.* *_cp313",
    ]

    pin = _python_pin_from_version("3.9")
    assert pin == [
        "python >=3.9,<3.10.0a0",
        "python_abi 3.9.* *_cp39",
    ]

    # No minor version — no pin
    assert _python_pin_from_version("3") == []


def test_conda_target_info_noarch() -> None:
    """Test CondaTargetInfo for noarch packages."""
    from whl2conda.api.converter import MetadataFromWheel

    md = MetadataFromWheel(
        md={},
        package_name="test",
        version="1.0",
        wheel_build_number="",
        license=None,
        dependencies=[],
        wheel_info_dir=Path("."),
        is_pure_python=True,
        python_tag="py3",
        abi_tag="none",
        platform_tag="any",
    )
    target = CondaTargetInfo.from_wheel_metadata(md)
    assert target.is_noarch
    assert target.subdir == "noarch"
    assert target.arch is None
    assert target.platform is None
    assert target.build_string == "py_0"
    assert target.site_packages_prefix == "site-packages"
    assert target.python_version == ""


def test_conda_target_info_binary() -> None:
    """Test CondaTargetInfo for binary packages."""
    from whl2conda.api.converter import MetadataFromWheel

    md = MetadataFromWheel(
        md={},
        package_name="test",
        version="1.0",
        wheel_build_number="",
        license=None,
        dependencies=[],
        wheel_info_dir=Path("."),
        is_pure_python=False,
        python_tag="cp313",
        abi_tag="cp313",
        platform_tag="macosx_11_0_arm64",
    )
    target = CondaTargetInfo.from_wheel_metadata(md)
    assert not target.is_noarch
    assert target.subdir == "osx-arm64"
    assert target.arch == "arm64"
    assert target.platform == "osx"
    assert target.build_string == "py313_0"
    assert target.site_packages_prefix == "lib/python3.13/site-packages"
    assert target.python_version == "3.13"

    # Windows target
    md_win = MetadataFromWheel(
        md={},
        package_name="test",
        version="1.0",
        wheel_build_number="",
        license=None,
        dependencies=[],
        wheel_info_dir=Path("."),
        is_pure_python=False,
        python_tag="cp310",
        abi_tag="cp310",
        platform_tag="win_amd64",
    )
    target_win = CondaTargetInfo.from_wheel_metadata(md_win, build_number=2)
    assert target_win.subdir == "win-64"
    assert target_win.build_string == "py310_2"
    assert target_win.site_packages_prefix == "Lib/site-packages"
    assert target_win.python_version == "3.10"


def test_check_binary_conversion_local_version(tmp_path: Path) -> None:
    """Test that local version suffixes (e.g. +cu121) are rejected."""
    from whl2conda.api.converter import MetadataFromWheel

    converter = Wheel2CondaConverter(tmp_path / "fake.whl", tmp_path)
    converter.logger = logging.getLogger(__name__)

    wheel_md = MetadataFromWheel(
        md={},
        package_name="torch",
        version="2.3.0+cu121",
        wheel_build_number="",
        license=None,
        dependencies=[],
        wheel_info_dir=Path("."),
        is_pure_python=False,
        python_tag="cp312",
        abi_tag="cp312",
        platform_tag="manylinux_2_17_x86_64",
    )

    with pytest.raises(Wheel2CondaError, match=r"local version suffix '\+cu121'"):
        converter._check_binary_conversion(wheel_md)


def test_marker_evaluation_for_binary() -> None:
    """Test that platform markers are evaluated for binary conversions."""
    from whl2conda.api.converter import _evaluate_marker

    linux_env = CondaTargetInfo(
        subdir="linux-64",
        arch="x86_64",
        platform="linux",
        build_string="py312_0",
        is_noarch=False,
        site_packages_prefix="lib/python3.12/site-packages",
        python_version="3.12",
    ).marker_environment()

    mac_env = CondaTargetInfo(
        subdir="osx-arm64",
        arch="arm64",
        platform="osx",
        build_string="py312_0",
        is_noarch=False,
        site_packages_prefix="lib/python3.12/site-packages",
        python_version="3.12",
    ).marker_environment()

    # Linux-only dep should match linux env but not mac
    assert _evaluate_marker('platform_system == "Linux"', linux_env) is True
    assert _evaluate_marker('platform_system == "Linux"', mac_env) is False

    # macOS dep should match mac env
    assert _evaluate_marker('sys_platform == "darwin"', mac_env) is True
    assert _evaluate_marker('sys_platform == "darwin"', linux_env) is False

    # Windows check
    assert _evaluate_marker('os_name == "nt"', linux_env) is False

    # Invalid marker returns True (conservative)
    assert _evaluate_marker("this is not valid", linux_env) is True


def test_conda_target_marker_environment() -> None:
    """Test CondaTargetInfo.marker_environment for different platforms."""
    linux = CondaTargetInfo(
        subdir="linux-64",
        arch="x86_64",
        platform="linux",
        build_string="py312_0",
        is_noarch=False,
        site_packages_prefix="lib/python3.12/site-packages",
        python_version="3.12",
    )
    env = linux.marker_environment()
    assert env["os_name"] == "posix"
    assert env["sys_platform"] == "linux"
    assert env["platform_system"] == "Linux"
    assert env["platform_machine"] == "x86_64"
    assert env["python_version"] == "3.12"

    win = CondaTargetInfo(
        subdir="win-64",
        arch="x86_64",
        platform="win",
        build_string="py312_0",
        is_noarch=False,
        site_packages_prefix="Lib/site-packages",
        python_version="3.12",
    )
    env = win.marker_environment()
    assert env["os_name"] == "nt"
    assert env["sys_platform"] == "win32"
    assert env["platform_system"] == "Windows"

    noarch = CondaTargetInfo(
        subdir="noarch",
        arch=None,
        platform=None,
        build_string="py_0",
        is_noarch=True,
        site_packages_prefix="site-packages",
    )
    assert noarch.marker_environment() == {}


def test_check_binary_conversion_ok(tmp_path: Path) -> None:
    """Test that simple packages pass binary conversion checks."""
    from whl2conda.api.converter import MetadataFromWheel

    converter = Wheel2CondaConverter(tmp_path / "fake.whl", tmp_path)
    converter.logger = logging.getLogger(__name__)

    wheel_md = MetadataFromWheel(
        md={},
        package_name="markupsafe",
        version="3.0.3",
        wheel_build_number="",
        license=None,
        dependencies=[],
        wheel_info_dir=Path("."),
        is_pure_python=False,
        python_tag="cp312",
        abi_tag="cp312",
        platform_tag="macosx_11_0_arm64",
    )

    # Should not raise
    converter._check_binary_conversion(wheel_md)


def test_reject_py2_only_wheel(
    test_case: ConverterTestCaseFactory,
    simple_wheel: Path,
    tmp_path: Path,
) -> None:
    """Test that py2-only wheels are rejected."""
    good_wheel = WheelFile(simple_wheel)
    extract_dir = tmp_path / "extract"
    good_wheel.extractall(str(extract_dir))
    extract_info_dir = next(extract_dir.glob("*.dist-info"))

    WHEEL_file = extract_info_dir / "WHEEL"
    WHEEL_msg = Wheel2CondaConverter.read_metadata_file(WHEEL_file)

    # Replace tag with py2-only
    WHEEL_msg.replace_header("Tag", "py2-none-any")
    WHEEL_file.write_text(WHEEL_msg.as_string(), encoding="utf8")

    py2_wheel = tmp_path / "py2-only" / simple_wheel.name
    py2_wheel.parent.mkdir(parents=True)
    with WheelFile(str(py2_wheel), "w") as wf:
        wf.write_files(str(extract_dir))

    with pytest.raises(Wheel2CondaError, match="no Python 3 compatible tag"):
        test_case(py2_wheel).build()


def test_add_binary_dependencies() -> None:
    """Test _add_binary_dependencies adds python pin and OS constraint."""

    converter = Wheel2CondaConverter(Path("fake.whl"), Path("."))
    converter.logger = logging.getLogger(__name__)

    target = CondaTargetInfo(
        subdir="osx-arm64",
        arch="arm64",
        platform="osx",
        build_string="py312_0",
        is_noarch=False,
        site_packages_prefix="lib/python3.12/site-packages",
        python_version="3.12",
    )

    deps = ["numpy >=1.20", "python >=3.8"]
    result = converter._add_binary_dependencies(deps, target, "macosx_11_0_arm64")

    # Should have tight python pin instead of loose spec
    assert any("python >=3.12" in d for d in result)
    assert not any(d == "python >=3.8" for d in result)
    # Should have OS constraint
    assert any("__osx" in d for d in result)


def test_add_binary_dependencies_no_python_pin() -> None:
    """Test _add_binary_dependencies with unknown python version."""
    converter = Wheel2CondaConverter(Path("fake.whl"), Path("."))
    converter.logger = logging.getLogger(__name__)

    target = CondaTargetInfo(
        subdir="linux-64",
        arch="x86_64",
        platform="linux",
        build_string="py3_0",
        is_noarch=False,
        site_packages_prefix="lib/python3.12/site-packages",
        python_version="",
    )

    deps = ["numpy >=1.20"]
    result = converter._add_binary_dependencies(deps, target, "linux_x86_64")
    # No python pin added, original deps preserved
    assert "numpy >=1.20" in result


def test_compute_conda_deps_with_marker_env() -> None:
    """Test _compute_conda_dependencies with marker_env for binary conversion."""
    converter = Wheel2CondaConverter(Path("fake.whl"), Path("."))
    converter.logger = logging.getLogger(__name__)

    linux_env = CondaTargetInfo(
        subdir="linux-64",
        arch="x86_64",
        platform="linux",
        build_string="py312_0",
        is_noarch=False,
        site_packages_prefix="lib/python3.12/site-packages",
        python_version="3.12",
    ).marker_environment()

    deps = [
        RequiresDistEntry.parse("numpy >=1.20"),
        RequiresDistEntry.parse('pyobjc; sys_platform == "darwin"'),
        RequiresDistEntry.parse('pywin32; os_name == "nt"'),
        RequiresDistEntry.parse('readline; sys_platform == "linux"'),
    ]

    result = converter._compute_conda_dependencies(deps, marker_env=linux_env)
    dep_names = [d.split()[0] for d in result]
    assert "numpy" in dep_names
    assert "readline" in dep_names
    # Platform-specific deps should be filtered out
    assert "pyobjc" not in dep_names
    assert "pywin32" not in dep_names
