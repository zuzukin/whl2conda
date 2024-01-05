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
import subprocess
from pathlib import Path
from time import sleep
from typing import Iterator

# third party
import pytest
from wheel.wheelfile import WheelFile

# this package
from whl2conda.api.converter import (
    CondaPackageFormat,
    DependencyRename,
    RequiresDistEntry,
    Wheel2CondaError, Wheel2CondaConverter,
)
from whl2conda.cli.convert import do_build_wheel
from .converter import ConverterTestCaseFactory
from .converter import test_case  # pylint: disable=unused-import

from ..test_packages import (  # pylint: disable=unused-import
    markers_wheel,
    setup_wheel,
    simple_wheel,
)

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
        messages: list[str] = []
        for record in caplog.records:
            if record.levelno == logging.DEBUG:
                messages.append(record.message)
        return "\n".join(messages)

    debug_out = get_debug_out()
    assert not debug_out

    caplog.set_level("DEBUG")

    case.build()

    debug_out = get_debug_out()

    assert re.search(r"Extracted.*METADATA", debug_out)
    assert "Packaging info/about.json" in debug_out
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
        messages: list[str] = []
        for record in caplog.records:
            if record.levelno == logging.WARNING:
                messages.append(record.message)
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
    metadata_file.write_text(contents)
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
    WHEEL_msg = Wheel2CondaConverter.read_metadata_file(WHEEL_file)

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
    METADATA_msg = Wheel2CondaConverter.read_metadata_file(METADATA_file)
    METADATA_msg.replace_header("Metadata-Version", "999.2")
    METADATA_file.write_text(METADATA_msg.as_string())

    bad_md_version_wheel = tmp_path / "bad-md-version" / simple_wheel.name
    bad_md_version_wheel.parent.mkdir(parents=True)
    with WheelFile(str(bad_md_version_wheel), "w") as wf:
        wf.write_files(str(extract_dir))

    with pytest.raises(Wheel2CondaError, match="unsupported metadata version"):
        test_case(bad_md_version_wheel).build()


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
        assert re.search(
            expected_prompt, prompt
        ), f"'{expected_prompt}' does not match prompt '{prompt}'"
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


def test_version_translation(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture
) -> None:
    """Test for Wheel2CondaConverter.translate_version_spec"""
    converter = Wheel2CondaConverter(tmp_path, tmp_path)
    for spec, expected in {
        "~= 1.2.3" : ">=1.2.3,==1.2.*",
        "~=1" : ">=1",
        ">=3.2 , ~=1.2.4.dev4" : ">=3.2,>=1.2.4.dev4,==1.2.*",
        " >=1.2.3 , <4.0" : ">=1.2.3,<4.0",
        " >v1.2+foo" : ">1.2+foo"
    }.items():
        assert converter.translate_version_spec(spec) == expected

    caplog.clear()
    assert converter.translate_version_spec("bad-version") =="bad-version"
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
