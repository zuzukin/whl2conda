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
Unit tests for platform tag translation and conda target derivation
"""

from __future__ import annotations

# standard
import logging
from pathlib import Path

# third party
import pytest
from wheel.wheelfile import WheelFile

# this package
from whl2conda.api.converter import (
    CondaTargetInfo,
    Wheel2CondaConverter,
    Wheel2CondaError,
    _os_constraint_from_platform_tag,
    _parse_platform_tag,
    _python_pin_from_version,
    _python_version_from_tag,
)

from .converter_support import ConverterTestCaseFactory

this_dir = Path(__file__).parent.absolute()
root_dir = this_dir.parent.parent
test_projects = root_dir / "test-projects"


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

    assert not target.is_abi3
    assert not target.uses_noarch_python
    assert not target_win.is_abi3


def test_conda_target_info_abi3() -> None:
    """Test CondaTargetInfo for abi3 (stable ABI) packages (#183)."""
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
        python_tag="cp312",
        abi_tag="abi3",
        platform_tag="macosx_11_0_arm64",
    )
    target = CondaTargetInfo.from_wheel_metadata(md)
    assert not target.is_noarch
    assert target.is_abi3
    assert target.uses_noarch_python
    assert target.subdir == "osx-arm64"
    assert target.arch == "arm64"
    assert target.platform == "osx"
    assert target.build_string == "py312_abi3_0"
    # abi3 packages use the noarch python site-packages layout
    assert target.site_packages_prefix == "site-packages"
    assert target.python_version == "3.12"

    # Windows abi3 target also uses noarch layout
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
        abi_tag="abi3",
        platform_tag="win_amd64",
    )
    target_win = CondaTargetInfo.from_wheel_metadata(md_win, build_number=3)
    assert target_win.is_abi3
    assert target_win.subdir == "win-64"
    assert target_win.build_string == "py310_abi3_3"
    assert target_win.site_packages_prefix == "site-packages"


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
