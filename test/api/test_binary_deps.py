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
Unit tests for binary/abi3 wheel conversion and dependencies
"""

from __future__ import annotations

# standard
import json
import logging
from pathlib import Path

# third party
import pytest
from wheel.wheelfile import WheelFile

# this package
from whl2conda.api.converter import (
    CondaPackageFormat,
    CondaTargetInfo,
    Wheel2CondaConverter,
    Wheel2CondaError,
)

from .converter_support import ConverterTestCaseFactory

this_dir = Path(__file__).parent.absolute()
root_dir = this_dir.parent.parent
test_projects = root_dir / "test-projects"


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


def test_add_binary_dependencies_abi3() -> None:
    """Test _add_binary_dependencies python floor for abi3 wheels (#183)."""
    converter = Wheel2CondaConverter(Path("fake.whl"), Path("."))
    converter.logger = logging.getLogger(__name__)

    target = CondaTargetInfo(
        subdir="osx-arm64",
        arch="arm64",
        platform="osx",
        build_string="py312_abi3_0",
        is_noarch=False,
        site_packages_prefix="site-packages",
        python_version="3.12",
        is_abi3=True,
    )

    deps = ["numpy >=1.20", "python >=3.12"]
    result = converter._add_binary_dependencies(deps, target, "macosx_11_0_arm64")

    # Only a floor pin, no upper bound and no python_abi, no duplicates
    assert result.count("python >=3.12") == 1
    assert not any("," in d for d in result if d.startswith("python "))
    assert not any(d.startswith("python_abi") for d in result)
    assert any("__osx" in d for d in result)

    # A tighter Requires-Python floor is preserved alongside the abi3 floor
    deps = ["python >=3.13"]
    result = converter._add_binary_dependencies(deps, target, "macosx_11_0_arm64")
    assert "python >=3.13" in result
    assert "python >=3.12" in result

    # Floor is added even if the wheel had no python dependency
    result = converter._add_binary_dependencies([], target, "macosx_11_0_arm64")
    assert "python >=3.12" in result


def test_add_binary_dependencies_abi3_conda_forge() -> None:
    """Test conda-forge CEP-20 pins for abi3 wheels (#194)."""
    converter = Wheel2CondaConverter(Path("fake.whl"), Path("."))
    converter.logger = logging.getLogger(__name__)
    converter.for_conda_forge = True

    abi3_target = CondaTargetInfo(
        subdir="osx-arm64",
        arch="arm64",
        platform="osx",
        build_string="py312_abi3_0",
        is_noarch=False,
        site_packages_prefix="site-packages",
        python_version="3.12",
        is_abi3=True,
    )

    result = converter._add_binary_dependencies([], abi3_target, "macosx_11_0_arm64")
    assert "python >=3.12" in result
    assert "cpython >=3.12" in result
    assert "_python_abi3_support 1.*" in result

    # cpython pin mirrors an explicit python version override
    converter.python_version = ">=3.13"
    result = converter._add_binary_dependencies(
        ["python >=3.13"], abi3_target, "macosx_11_0_arm64"
    )
    assert "cpython >=3.13" in result
    assert "_python_abi3_support 1.*" in result

    # no effect on non-abi3 binary wheels, whose python_abi pin already
    # restricts the package to cpython
    converter.python_version = ""
    non_abi3_target = CondaTargetInfo(
        subdir="linux-64",
        arch="x86_64",
        platform="linux",
        build_string="py312_0",
        is_noarch=False,
        site_packages_prefix="lib/python3.12/site-packages",
        python_version="3.12",
    )
    result = converter._add_binary_dependencies([], non_abi3_target, "linux_x86_64")
    assert not any(d.startswith("cpython") for d in result)
    assert not any(d.startswith("_python_abi3_support") for d in result)


def test_add_binary_dependencies_python_override() -> None:
    """Test that an explicit python version overrides binary pins (#183)."""
    converter = Wheel2CondaConverter(Path("fake.whl"), Path("."))
    converter.logger = logging.getLogger(__name__)
    converter.python_version = ">=3.10"

    target = CondaTargetInfo(
        subdir="linux-64",
        arch="x86_64",
        platform="linux",
        build_string="py312_0",
        is_noarch=False,
        site_packages_prefix="lib/python3.12/site-packages",
        python_version="3.12",
    )

    # The override was already applied by _compute_conda_dependencies;
    # no tight pin or python_abi should be added on top of it
    deps = ["numpy >=1.20", "python >=3.10"]
    result = converter._add_binary_dependencies(deps, target, "manylinux2014_x86_64")
    assert [d for d in result if d.startswith("python")] == ["python >=3.10"]

    # Same for abi3 targets: no additional floor is added
    abi3_target = CondaTargetInfo(
        subdir="linux-64",
        arch="x86_64",
        platform="linux",
        build_string="py312_abi3_0",
        is_noarch=False,
        site_packages_prefix="site-packages",
        python_version="3.12",
        is_abi3=True,
    )
    result = converter._add_binary_dependencies(
        ["python >=3.10"], abi3_target, "manylinux2014_x86_64"
    )
    assert [d for d in result if d.startswith("python")] == ["python >=3.10"]


def test_convert_abi3_wheel(
    test_case: ConverterTestCaseFactory,
    simple_wheel: Path,
    tmp_path: Path,
) -> None:
    """Test end-to-end conversion of an abi3 (stable ABI) wheel (#183)."""
    good_wheel = WheelFile(simple_wheel)
    extract_dir = tmp_path / "extract"
    good_wheel.extractall(str(extract_dir))
    extract_info_dir = next(extract_dir.glob("*.dist-info"))

    WHEEL_file = extract_info_dir / "WHEEL"
    WHEEL_msg = Wheel2CondaConverter.read_metadata_file(WHEEL_file)
    WHEEL_msg.replace_header("Root-Is-Purelib", "False")
    WHEEL_msg.replace_header("Tag", "cp312-abi3-macosx_11_0_arm64")
    WHEEL_file.write_text(WHEEL_msg.as_string(), encoding="utf8")

    abi3_wheel_name = simple_wheel.name.replace(
        "py3-none-any", "cp312-abi3-macosx_11_0_arm64"
    )
    abi3_wheel = tmp_path / "abi3" / abi3_wheel_name
    abi3_wheel.parent.mkdir(parents=True)
    with WheelFile(str(abi3_wheel), "w") as wf:
        wf.write_files(str(extract_dir))

    case = test_case(abi3_wheel)
    case.allow_impure = True
    pkg_path = case.build()
    assert "py312_abi3_0" in pkg_path.name


# tags of a multi-platform ("fat") macosx wheel, in orjson's order (#201)
FAT_WHEEL_TAGS = [
    "cp313-cp313-macosx_10_15_x86_64",
    "cp313-cp313-macosx_11_0_arm64",
    "cp313-cp313-macosx_10_15_universal2",
]


def test_select_wheel_tag(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test platform tag selection for fat wheels (#201)."""
    converter = Wheel2CondaConverter(Path("fake.whl"), Path("."))
    converter.logger = logging.getLogger(__name__)

    # single tag: chosen without further ado
    assert (
        converter._select_wheel_tag(["cp313-cp313-manylinux_2_17_x86_64"])
        == "cp313-cp313-manylinux_2_17_x86_64"
    )

    # fat wheel: the current platform is preferred, with a warning
    for native, expected in [
        ("osx-arm64", "cp313-cp313-macosx_11_0_arm64"),
        ("osx-64", "cp313-cp313-macosx_10_15_x86_64"),
        # non-mac host: the universal2 rule selects osx-arm64, and the
        # arch-specific arm64 tag is preferred within that subdir
        ("linux-64", "cp313-cp313-macosx_11_0_arm64"),
    ]:
        monkeypatch.setattr(
            "whl2conda.api.converter.native_conda_subdir", lambda sub=native: sub
        )
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            assert converter._select_wheel_tag(FAT_WHEEL_TAGS) == expected
        assert "multiple platforms" in caplog.text
        assert "osx-arm64" in caplog.text and "osx-64" in caplog.text

    # multiple tags for the same subdir: no warning, arch-specific preferred
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert (
            converter._select_wheel_tag([
                "cp39-abi3-macosx_10_15_universal2",
                "cp39-abi3-macosx_11_0_arm64",
            ])
            == "cp39-abi3-macosx_11_0_arm64"
        )
        assert (
            converter._select_wheel_tag([
                "cp313-cp313-manylinux_2_17_x86_64",
                "cp313-cp313-manylinux2014_x86_64",
            ])
            == "cp313-cp313-manylinux_2_17_x86_64"
        )
        # a group with only universal2 tags falls back to the first
        assert (
            converter._select_wheel_tag([
                "cp39-abi3-macosx_10_15_universal2",
                "cp310-abi3-macosx_11_0_universal2",
            ])
            == "cp39-abi3-macosx_10_15_universal2"
        )
    assert not caplog.text

    # unsupported platform tags group separately; supported host tag wins
    monkeypatch.setattr(
        "whl2conda.api.converter.native_conda_subdir", lambda: "osx-arm64"
    )
    assert (
        converter._select_wheel_tag([
            "cp313-cp313-freebsd_14_x86_64",
            "cp313-cp313-macosx_11_0_arm64",
        ])
        == "cp313-cp313-macosx_11_0_arm64"
    )

    # no host match and no universal2 component: first tag wins
    monkeypatch.setattr(
        "whl2conda.api.converter.native_conda_subdir", lambda: "linux-64"
    )
    assert (
        converter._select_wheel_tag([
            "cp313-cp313-macosx_10_15_x86_64",
            "cp313-cp313-macosx_11_0_arm64",
        ])
        == "cp313-cp313-macosx_10_15_x86_64"
    )


def test_select_wheel_tag_override(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test explicit platform_tag override (#201)."""
    converter = Wheel2CondaConverter(Path("fake.whl"), Path("."))
    converter.logger = logging.getLogger(__name__)

    converter.platform_tag = "macosx_10_15_x86_64"
    with caplog.at_level(logging.WARNING):
        assert (
            converter._select_wheel_tag(FAT_WHEEL_TAGS)
            == "cp313-cp313-macosx_10_15_x86_64"
        )
    assert not caplog.text

    # case insensitive
    converter.platform_tag = "MACOSX_10_15_UNIVERSAL2"
    assert (
        converter._select_wheel_tag(FAT_WHEEL_TAGS)
        == "cp313-cp313-macosx_10_15_universal2"
    )

    converter.platform_tag = "win_amd64"
    with pytest.raises(Wheel2CondaError, match=r"available:.*macosx_10_15_x86_64"):
        converter._select_wheel_tag(FAT_WHEEL_TAGS)


def _rebuild_wheel_tags(
    simple_wheel: Path,
    work_dir: Path,
    tags: list[str],
    label: str,
    *,
    purelib: bool = False,
) -> Path:
    """Rebuild the simple wheel with the given WHEEL tags."""
    good_wheel = WheelFile(simple_wheel)
    extract_dir = work_dir / f"extract-{label}"
    good_wheel.extractall(str(extract_dir))
    extract_info_dir = next(extract_dir.glob("*.dist-info"))

    WHEEL_file = extract_info_dir / "WHEEL"
    WHEEL_msg = Wheel2CondaConverter.read_metadata_file(WHEEL_file)
    WHEEL_msg.replace_header("Root-Is-Purelib", str(purelib))
    del WHEEL_msg["Tag"]
    for tag in tags:
        WHEEL_msg["Tag"] = tag
    WHEEL_file.write_text(WHEEL_msg.as_string(), encoding="utf8")

    wheel_name = simple_wheel.name.replace("py3-none-any", tags[0])
    wheel = work_dir / label / wheel_name
    wheel.parent.mkdir(parents=True)
    with WheelFile(str(wheel), "w") as wf:
        wf.write_files(str(extract_dir))
    return wheel


def _build_fat_wheel(simple_wheel: Path, work_dir: Path) -> Path:
    """Rebuild the simple wheel as a fat macosx binary wheel."""
    return _rebuild_wheel_tags(simple_wheel, work_dir, FAT_WHEEL_TAGS, "fat")


def test_convert_fat_wheel(
    simple_wheel: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test end-to-end conversion of a fat macosx wheel (#201)."""
    fat_wheel = _build_fat_wheel(simple_wheel, tmp_path)

    monkeypatch.setattr(
        "whl2conda.api.converter.native_conda_subdir", lambda: "osx-arm64"
    )

    converter = Wheel2CondaConverter(fat_wheel, tmp_path / "out1")
    converter.allow_impure = True
    converter.convert()
    assert converter.conda_target is not None
    assert converter.conda_target.subdir == "osx-arm64"

    # explicit override selects the other platform, with its __osx floor
    converter = Wheel2CondaConverter(fat_wheel, tmp_path / "out2")
    converter.allow_impure = True
    converter.platform_tag = "macosx_10_15_x86_64"
    converter.out_format = CondaPackageFormat.TREE
    pkg_tree = converter.convert()
    assert converter.conda_target is not None
    assert converter.conda_target.subdir == "osx-64"
    index = json.loads((pkg_tree / "info" / "index.json").read_text("utf8"))
    assert index["subdir"] == "osx-64"
    assert "__osx >=10.15" in index["depends"]


def test_convert_all_platforms(
    simple_wheel: Path,
    tmp_path: Path,
) -> None:
    """Test conversion of a fat wheel for all platforms (#204)."""
    fat_wheel = _build_fat_wheel(simple_wheel, tmp_path)

    converter = Wheel2CondaConverter(fat_wheel, tmp_path / "all")
    converter.allow_impure = True
    converter.out_format = CondaPackageFormat.TREE
    packages = converter.convert_all()

    assert [pkg.parent.name for pkg in packages] == ["osx-64", "osx-arm64"]
    for pkg, subdir, osx_constraint in [
        (packages[0], "osx-64", "__osx >=10.15"),
        (packages[1], "osx-arm64", "__osx >=11.0"),
    ]:
        assert pkg.parent.parent == tmp_path / "all"
        index = json.loads((pkg / "info" / "index.json").read_text("utf8"))
        assert index["subdir"] == subdir
        assert osx_constraint in index["depends"]

    # converter settings are restored afterwards
    assert converter.out_dir == tmp_path / "all"
    assert converter.platform_tag == ""

    # pure python wheel: a single package under noarch/
    converter = Wheel2CondaConverter(simple_wheel, tmp_path / "pure")
    converter.out_format = CondaPackageFormat.TREE
    packages = converter.convert_all()
    assert len(packages) == 1
    assert packages[0].parent == tmp_path / "pure" / "noarch"
    index = json.loads((packages[0] / "info" / "index.json").read_text("utf8"))
    assert index["subdir"] == "noarch"


def test_vendored_library_warning(
    simple_wheel: Path,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test warning for wheels bundling vendored shared libraries."""
    # rebuild the simple wheel with an auditwheel-style .libs directory
    good_wheel = WheelFile(simple_wheel)
    extract_dir = tmp_path / "extract"
    good_wheel.extractall(str(extract_dir))
    extract_info_dir = next(extract_dir.glob("*.dist-info"))

    WHEEL_file = extract_info_dir / "WHEEL"
    WHEEL_msg = Wheel2CondaConverter.read_metadata_file(WHEEL_file)
    WHEEL_msg.replace_header("Root-Is-Purelib", "False")
    WHEEL_msg.replace_header("Tag", "cp312-cp312-manylinux_2_17_x86_64")
    WHEEL_file.write_text(WHEEL_msg.as_string(), encoding="utf8")

    libs_dir = extract_dir / "simple.libs"
    libs_dir.mkdir()
    (libs_dir / "libfoo-1234abcd.so.1").write_bytes(b"\x7fELF-fake")

    wheel_name = simple_wheel.name.replace(
        "py3-none-any", "cp312-cp312-manylinux_2_17_x86_64"
    )
    vendored_wheel = tmp_path / "vendored" / wheel_name
    vendored_wheel.parent.mkdir(parents=True)
    with WheelFile(str(vendored_wheel), "w") as wf:
        wf.write_files(str(extract_dir))

    converter = Wheel2CondaConverter(vendored_wheel, tmp_path / "out")
    converter.allow_impure = True
    with caplog.at_level(logging.WARNING):
        converter.convert()
    assert "bundles shared libraries" in caplog.text
    assert "simple.libs" in caplog.text

    # no warning for a binary wheel without vendored libraries
    caplog.clear()
    fat_wheel = _build_fat_wheel(simple_wheel, tmp_path / "plain")
    converter = Wheel2CondaConverter(fat_wheel, tmp_path / "out2")
    converter.allow_impure = True
    converter.platform_tag = "macosx_11_0_arm64"
    with caplog.at_level(logging.WARNING):
        converter.convert()
    assert "bundles shared libraries" not in caplog.text


def test_platform_groups(
    simple_wheel: Path,
    tmp_path: Path,
) -> None:
    """Test _platform_groups tag handling (#204)."""
    # non-python-3 tags are skipped; pure wheels map to noarch
    wheel = _rebuild_wheel_tags(
        simple_wheel,
        tmp_path,
        ["py2-none-any", "py3-none-any"],
        "mixed",
        purelib=True,
    )
    converter = Wheel2CondaConverter(wheel, tmp_path)
    assert converter._platform_groups() == {"noarch": "any"}

    # unsupported platform tags are kept in their own group
    wheel = _rebuild_wheel_tags(
        simple_wheel,
        tmp_path,
        ["cp313-cp313-freebsd_14_x86_64", "cp313-cp313-macosx_11_0_arm64"],
        "exotic",
    )
    converter = Wheel2CondaConverter(wheel, tmp_path)
    assert converter._platform_groups() == {
        "freebsd_14_x86_64": "freebsd_14_x86_64",
        "osx-arm64": "macosx_11_0_arm64",
    }

    # no python 3 compatible tag at all
    wheel = _rebuild_wheel_tags(
        simple_wheel, tmp_path, ["py2-none-any"], "py2", purelib=True
    )
    converter = Wheel2CondaConverter(wheel, tmp_path)
    with pytest.raises(Wheel2CondaError, match="no Python 3 compatible tag"):
        converter._platform_groups()
