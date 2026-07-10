#  Copyright 2026 Christopher Barber
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
Unit tests for whl2conda.api.compare
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path

from whl2conda.api.compare import (
    CompareOptions,
    ComparisonResult,
    DiffCategory,
    Difference,
    Severity,
    compare_conda_packages,
)

# pylint: disable=unused-import
from ..test_packages import simple_conda_package, simple_wheel  # noqa: F401

# pylint: disable=redefined-outer-name

NO_RENAMES: dict[str, str] = {}


def make_pkg(
    root: Path,
    *,
    name: str = "simple",
    version: str = "1.0",
    depends: Sequence[str] = ("python >=3.10",),
    files: Mapping[str, str | bytes] | None = None,
    entry_points: Sequence[str] = (),
    subdir: str = "noarch",
    noarch: str | None = "python",
    build: str = "py_0",
    build_number: int = 0,
    license: str = "MIT",  # pylint: disable=redefined-builtin
    timestamp: int = 1234567890000,
    about: dict | None = None,
    extra_info_files: Sequence[str] = (),
    paths_override: Sequence[str] | None = None,
) -> Path:
    """Write a synthetic extracted conda package directory."""
    root.mkdir(parents=True, exist_ok=True)
    info_dir = root / "info"
    info_dir.mkdir(exist_ok=True)

    index: dict = {
        "name": name,
        "version": version,
        "depends": list(depends),
        "subdir": subdir,
        "build": build,
        "build_number": build_number,
        "license": license,
        "timestamp": timestamp,
    }
    if noarch:
        index["noarch"] = noarch
    (info_dir / "index.json").write_text(json.dumps(index))

    (info_dir / "about.json").write_text(json.dumps(about or {"summary": "test"}))

    if entry_points:
        link = {
            "noarch": {"type": "python", "entry_points": list(entry_points)},
            "package_metadata_version": 1,
        }
        (info_dir / "link.json").write_text(json.dumps(link))

    files = files or {}
    path_entries = []
    for relpath, content in files.items():
        file_path = root / relpath
        file_path.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf8") if isinstance(content, str) else content
        file_path.write_bytes(data)
        path_entries.append({
            "_path": relpath,
            "path_type": "hardlink",
            "sha256": sha256(data).hexdigest(),
            "size_in_bytes": len(data),
        })
    if paths_override is not None:
        path_entries = [
            {
                "_path": p,
                "path_type": "hardlink",
                "sha256": "0" * 64,
                "size_in_bytes": 0,
            }
            for p in paths_override
        ]
    (info_dir / "paths.json").write_text(
        json.dumps({"paths": path_entries, "paths_version": 1})
    )

    for relpath in extra_info_files:
        extra = root / relpath
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text("")

    return root


def compare(
    pkg1: Path,
    pkg2: Path,
    *,
    strict: bool = False,
    ignore: set[DiffCategory] | None = None,
    extra_run_exports: set[str] | None = None,
    renames: dict[str, str] | None = None,
) -> ComparisonResult:
    """Compare with hermetic defaults (no user-cache rename lookup)."""
    options = CompareOptions(
        strict=strict,
        ignore=ignore or set(),
        extra_run_exports=extra_run_exports or set(),
        renames=NO_RENAMES if renames is None else renames,
    )
    return compare_conda_packages(pkg1, pkg2, options=options)


def find(
    result: ComparisonResult, category: DiffCategory, severity: Severity | None = None
) -> list[Difference]:
    """All differences with given category (and severity, if given)."""
    return [
        d
        for d in result.differences
        if d.category is category and (severity is None or d.severity is severity)
    ]


def test_identical_packages(tmp_path: Path) -> None:
    """Identical packages produce no differences at all"""
    files = {"site-packages/foo/__init__.py": "x = 1\n"}
    pkg1 = make_pkg(tmp_path / "pkg1", files=files)
    pkg2 = make_pkg(tmp_path / "pkg2", files=files)
    result = compare(pkg1, pkg2)
    assert result.ok
    assert not result.differences
    assert "0 errors, 0 notices" in result.report()


def test_name_version_mismatch(tmp_path: Path) -> None:
    """Differing name/version are errors"""
    pkg1 = make_pkg(tmp_path / "pkg1", name="foo", version="1.0")
    pkg2 = make_pkg(tmp_path / "pkg2", name="bar", version="2.0")
    result = compare(pkg1, pkg2)
    assert not result.ok
    assert find(result, DiffCategory.PACKAGE_NAME, Severity.ERROR)
    assert find(result, DiffCategory.PACKAGE_VERSION, Severity.ERROR)


def test_build_string_and_number(tmp_path: Path) -> None:
    """Build string differences expected, build number notable"""
    pkg1 = make_pkg(tmp_path / "pkg1", build="py_0", build_number=0)
    pkg2 = make_pkg(tmp_path / "pkg2", build="pyhd8ed1ab_2", build_number=2)
    result = compare(pkg1, pkg2)
    assert result.ok
    assert find(result, DiffCategory.BUILD_STRING, Severity.EXPECTED)
    assert find(result, DiffCategory.BUILD_NUMBER, Severity.NOTICE)


def test_abi3_subdir_difference_expected(tmp_path: Path) -> None:
    """noarch abi3 vs platform-specific build is an expected difference"""
    pkg1 = make_pkg(
        tmp_path / "pkg1", subdir="osx-arm64", noarch="python", build="py312_abi3_0"
    )
    pkg2 = make_pkg(
        tmp_path / "pkg2", subdir="osx-arm64", noarch=None, build="py312_h1234567_0"
    )
    result = compare(pkg1, pkg2)
    assert find(result, DiffCategory.NOARCH_VS_PLATFORM, Severity.EXPECTED)
    assert result.ok


def test_subdir_mismatch_error(tmp_path: Path) -> None:
    """Non-abi3 noarch/subdir difference is an error"""
    pkg1 = make_pkg(tmp_path / "pkg1", subdir="noarch", noarch="python")
    pkg2 = make_pkg(tmp_path / "pkg2", subdir="linux-64", noarch=None, build="py312_0")
    result = compare(pkg1, pkg2)
    assert find(result, DiffCategory.NOARCH_VS_PLATFORM, Severity.ERROR)


def test_license_difference(tmp_path: Path) -> None:
    """License format differences are notable"""
    pkg1 = make_pkg(tmp_path / "pkg1", license="Apache License Version 2.0 ...")
    pkg2 = make_pkg(tmp_path / "pkg2", license="Apache-2.0")
    result = compare(pkg1, pkg2)
    assert find(result, DiffCategory.LICENSE, Severity.NOTICE)
    assert result.ok


def test_dep_run_export(tmp_path: Path) -> None:
    """Standard run-export deps in reference package are expected"""
    pkg1 = make_pkg(tmp_path / "pkg1", depends=["python >=3.10"])
    pkg2 = make_pkg(
        tmp_path / "pkg2",
        depends=["python", "libcxx >=17", "cpython >=3.10", "custom-export 1.*"],
    )
    result = compare(pkg1, pkg2, extra_run_exports={"custom-export"})
    run_exports = find(result, DiffCategory.DEP_RUN_EXPORT, Severity.EXPECTED)
    assert {d.right.split()[0] for d in run_exports} == {
        "libcxx",
        "cpython",
        "custom-export",
    }
    # the unconstrained python dep in the reference is expected
    assert find(result, DiffCategory.PYTHON_PIN, Severity.EXPECTED)
    assert result.ok


def test_dep_missing(tmp_path: Path) -> None:
    """Non run-export dep only in reference package is an error"""
    pkg1 = make_pkg(tmp_path / "pkg1", depends=["python >=3.10"])
    pkg2 = make_pkg(tmp_path / "pkg2", depends=["python >=3.10", "numpy >=1.20"])
    result = compare(pkg1, pkg2)
    missing = find(result, DiffCategory.DEP_MISSING, Severity.ERROR)
    assert len(missing) == 1
    assert missing[0].right == "numpy >=1.20"
    assert not result.ok


def test_dep_extra_and_version(tmp_path: Path) -> None:
    """Extra deps and constraint differences are notable"""
    pkg1 = make_pkg(tmp_path / "pkg1", depends=["python >=3.10", "extra-dep >=1"])
    pkg2 = make_pkg(tmp_path / "pkg2", depends=["python >=3.10,<3.14"])
    result = compare(pkg1, pkg2)
    assert find(result, DiffCategory.DEP_EXTRA, Severity.NOTICE)
    assert find(result, DiffCategory.PYTHON_PIN, Severity.NOTICE)
    assert result.ok

    pkg3 = make_pkg(tmp_path / "pkg3", depends=["python >=3.10", "numpy >=1.20"])
    pkg4 = make_pkg(tmp_path / "pkg4", depends=["python >=3.10", "numpy >=1.24"])
    result = compare(pkg3, pkg4)
    assert find(result, DiffCategory.DEP_VERSION, Severity.NOTICE)


def test_dep_unrenamed(tmp_path: Path) -> None:
    """Unrenamed dependency detected via rename table"""
    pkg1 = make_pkg(tmp_path / "pkg1", depends=["python >=3.10", "foo-bar >=1"])
    pkg2 = make_pkg(tmp_path / "pkg2", depends=["python >=3.10", "foo_bar >=1"])
    result = compare(pkg1, pkg2, renames={"foo-bar": "foo_bar"})
    unrenamed = find(result, DiffCategory.DEP_UNRENAMED, Severity.ERROR)
    assert len(unrenamed) == 1
    assert "foo_bar" in unrenamed[0].description
    # without the rename table this is just extra+missing
    result = compare(pkg1, pkg2)
    assert not find(result, DiffCategory.DEP_UNRENAMED)
    assert find(result, DiffCategory.DEP_MISSING)


def test_file_layout_normalization(tmp_path: Path) -> None:
    """site-packages layouts are normalized before comparison"""
    pkg1 = make_pkg(
        tmp_path / "pkg1",
        files={
            "site-packages/foo/__init__.py": "x = 1\n",
            "python-scripts/foo-cli": "#!/usr/bin/env python\n",
        },
    )
    pkg2 = make_pkg(
        tmp_path / "pkg2",
        files={
            "lib/python3.12/site-packages/foo/__init__.py": "x = 1\n",
            "bin/foo-cli": "#!/opt/placeholder/bin/python\n",
        },
    )
    result = compare(pkg1, pkg2)
    assert not find(result, DiffCategory.FILE_MISSING)
    assert not find(result, DiffCategory.FILE_EXTRA)
    # script content differences are ignored (regenerated at install)
    assert not find(result, DiffCategory.FILE_CONTENT)
    assert result.ok


def test_file_content_difference(tmp_path: Path) -> None:
    """Differing text payload content is an error, binary is expected"""
    pkg1 = make_pkg(
        tmp_path / "pkg1",
        files={
            "site-packages/foo/__init__.py": "x = 1\n",
            "site-packages/foo/_native.abi3.so": b"\x7fELF-one",
        },
    )
    pkg2 = make_pkg(
        tmp_path / "pkg2",
        files={
            "site-packages/foo/__init__.py": "x = 2\n",
            "site-packages/foo/_native.abi3.so": b"\x7fELF-two",
        },
    )
    result = compare(pkg1, pkg2)
    assert find(result, DiffCategory.FILE_CONTENT, Severity.ERROR)
    assert find(result, DiffCategory.BINARY_CONTENT, Severity.EXPECTED)


def test_file_missing_and_extra(tmp_path: Path) -> None:
    """One-sided payload files are errors, except benign categories"""
    pkg1 = make_pkg(
        tmp_path / "pkg1",
        files={
            "site-packages/foo/extra.py": "",
        },
    )
    pkg2 = make_pkg(
        tmp_path / "pkg2",
        files={
            "site-packages/foo/missing.py": "",
            "site-packages/foo/__pycache__/foo.cpython-312.pyc": b"\x00",
            "licenses/foo/LICENSE.txt": "MIT",
        },
    )
    result = compare(pkg1, pkg2)
    extra = find(result, DiffCategory.FILE_EXTRA, Severity.ERROR)
    assert [d.key for d in extra] == ["site-packages/foo/extra.py"]
    missing = find(result, DiffCategory.FILE_MISSING, Severity.ERROR)
    assert [d.key for d in missing] == ["site-packages/foo/missing.py"]
    assert find(result, DiffCategory.PYCACHE, Severity.EXPECTED)
    assert find(result, DiffCategory.FILE_MISSING, Severity.EXPECTED)  # license


def test_extension_module_abi_tags(tmp_path: Path) -> None:
    """Extension modules pair up across differing ABI tag file names"""
    pkg1 = make_pkg(
        tmp_path / "pkg1",
        files={
            "site-packages/foo/_native.abi3.so": b"\x7fELF-abi3",
            "site-packages/foo/_other.cpython-313-darwin.so": b"\x7fELF-one",
        },
    )
    pkg2 = make_pkg(
        tmp_path / "pkg2",
        files={
            "lib/python3.13/site-packages/foo/_native.cpython-313-darwin.so": (
                b"\x7fELF-cp313"
            ),
            "lib/python3.13/site-packages/foo/_other.cp313-win_amd64.pyd": (
                b"\x7fELF-two"
            ),
        },
    )
    result = compare(pkg1, pkg2)
    # _native pairs up as an expected binary difference; _other still
    # differs in the real suffix (.so vs .pyd) so remains one-sided
    binary = find(result, DiffCategory.BINARY_CONTENT, Severity.EXPECTED)
    assert [d.key for d in binary] == ["site-packages/foo/_native.so"]
    missing = find(result, DiffCategory.FILE_MISSING)
    assert [d.key for d in missing] == ["site-packages/foo/_other.pyd"]


def test_recipe_test_files_expected(tmp_path: Path) -> None:
    """Recipe test data under etc/conda/test-files is expected"""
    pkg1 = make_pkg(tmp_path / "pkg1")
    pkg2 = make_pkg(
        tmp_path / "pkg2",
        files={"etc/conda/test-files/foo/1/tests/test_foo.py": "def test(): pass\n"},
    )
    result = compare(pkg1, pkg2)
    assert result.ok
    assert find(result, DiffCategory.INFO_EXTRA_FILE, Severity.EXPECTED)


def test_entry_points(tmp_path: Path) -> None:
    """Entry points matched by name across delivery mechanisms"""
    pkg1 = make_pkg(
        tmp_path / "pkg1", entry_points=["foo-cli=foo.cli:main", "foo-x = foo.x:main"]
    )
    pkg2 = make_pkg(
        tmp_path / "pkg2",
        files={"bin/foo-cli": "#!python\n", "bin/foo-other": "#!python\n"},
    )
    result = compare(pkg1, pkg2)
    errors = find(result, DiffCategory.ENTRY_POINT, Severity.ERROR)
    assert {d.key for d in errors} == {
        "entry-points:foo-x",
        "entry-points:foo-other",
    }


def test_dist_info_metadata(tmp_path: Path) -> None:
    """METADATA requirements compared semantically with unhiding"""
    metadata1 = (
        "Metadata-Version: 2.1\n"
        "Name: foo\n"
        "Version: 1.0\n"
        "Requires-Dist: numpy >=1.20 ; extra == 'original'\n"
        "Requires-Dist: pywin32 ; (os_name == 'nt') and extra == 'original'\n"
        "Provides-Extra: original\n"
    )
    metadata2 = (
        "Metadata-Version: 2.1\n"
        "Name: foo\n"
        "Version: 1.0\n"
        "Requires-Dist: numpy>=1.20\n"
        "Requires-Dist: pywin32 ; os_name == 'nt'\n"
    )
    pkg1 = make_pkg(
        tmp_path / "pkg1",
        files={"site-packages/foo-1.0.dist-info/METADATA": metadata1},
    )
    pkg2 = make_pkg(
        tmp_path / "pkg2",
        files={"site-packages/foo-1.0.dist-info/METADATA": metadata2},
    )
    result = compare(pkg1, pkg2)
    assert not find(result, DiffCategory.DIST_INFO_METADATA)
    assert result.ok

    # different requirements are notable
    metadata3 = metadata2.replace("numpy>=1.20", "numpy>=1.24")
    pkg3 = make_pkg(
        tmp_path / "pkg3",
        files={"site-packages/foo-1.0.dist-info/METADATA": metadata3},
    )
    result = compare(pkg1, pkg3)
    assert find(result, DiffCategory.DIST_INFO_METADATA, Severity.NOTICE)


def test_info_extra_files(tmp_path: Path) -> None:
    """One-sided info bookkeeping files are expected"""
    pkg1 = make_pkg(tmp_path / "pkg1", extra_info_files=["info/files", "info/git"])
    pkg2 = make_pkg(
        tmp_path / "pkg2",
        extra_info_files=["info/recipe/meta.yaml", "info/tests/tests.yaml"],
    )
    result = compare(pkg1, pkg2)
    assert result.ok
    one_sided = find(result, DiffCategory.INFO_EXTRA_FILE, Severity.EXPECTED)
    assert len(one_sided) == 4


def test_paths_consistency(tmp_path: Path) -> None:
    """paths.json inconsistencies within a package are errors"""
    pkg1 = make_pkg(
        tmp_path / "pkg1",
        files={"site-packages/foo.py": ""},
        paths_override=["site-packages/foo.py", "site-packages/ghost.py"],
    )
    pkg2 = make_pkg(tmp_path / "pkg2", files={"site-packages/foo.py": ""})
    result = compare(pkg1, pkg2)
    missing = [
        d
        for d in find(result, DiffCategory.FILE_MISSING, Severity.ERROR)
        if d.key.startswith("paths.json:")
    ]
    assert len(missing) == 1
    assert "ghost.py" in missing[0].key


def test_strict_and_ignore(tmp_path: Path) -> None:
    """strict promotes notices; ignore demotes categories"""
    pkg1 = make_pkg(tmp_path / "pkg1", depends=["python >=3.10", "extra-dep >=1"])
    pkg2 = make_pkg(tmp_path / "pkg2", depends=["python >=3.10"])
    assert compare(pkg1, pkg2).ok
    assert not compare(pkg1, pkg2, strict=True).ok
    result = compare(pkg1, pkg2, strict=True, ignore={DiffCategory.DEP_EXTRA})
    assert result.ok
    assert find(result, DiffCategory.DEP_EXTRA, Severity.EXPECTED)


def test_to_json(tmp_path: Path) -> None:
    """JSON output is valid and complete"""
    pkg1 = make_pkg(tmp_path / "pkg1", depends=["python >=3.10"])
    pkg2 = make_pkg(tmp_path / "pkg2", depends=["python >=3.10", "numpy >=1.20"])
    result = compare(pkg1, pkg2)
    jobj = json.loads(json.dumps(result.to_json()))
    assert jobj["ok"] is False
    assert jobj["package1"] == str(pkg1)
    categories = {d["category"] for d in jobj["differences"]}
    assert "dep-missing" in categories
    severities = {d["severity"] for d in jobj["differences"]}
    assert severities <= {"EXPECTED", "NOTICE", "ERROR"}


def test_about_and_timestamp(tmp_path: Path) -> None:
    """One-sided about fields and timestamp differences are expected"""
    pkg1 = make_pkg(
        tmp_path / "pkg1",
        timestamp=1,
        about={"summary": "test", "home": "https://example.com"},
    )
    pkg2 = make_pkg(tmp_path / "pkg2", timestamp=2, about={"summary": "TEST  "})
    result = compare(pkg1, pkg2)
    assert result.ok
    # one-sided home field is expected; summary equal modulo case/whitespace
    assert find(result, DiffCategory.ABOUT_FIELD, Severity.EXPECTED)
    assert not find(result, DiffCategory.ABOUT_FIELD, Severity.NOTICE)
    assert find(result, DiffCategory.TIMESTAMP, Severity.EXPECTED)


def test_paths_json_unlisted_file(tmp_path: Path) -> None:
    """File not listed in own paths.json is an error; missing paths.json ok"""
    pkg1 = make_pkg(
        tmp_path / "pkg1", files={"site-packages/foo.py": ""}, paths_override=[]
    )
    pkg2 = make_pkg(tmp_path / "pkg2", files={"site-packages/foo.py": ""})
    (pkg2 / "info" / "paths.json").unlink()
    result = compare(pkg1, pkg2)
    unlisted = [
        d
        for d in find(result, DiffCategory.FILE_EXTRA, Severity.ERROR)
        if d.key.startswith("paths.json:")
    ]
    assert len(unlisted) == 1
    assert "foo.py" in unlisted[0].key


SIMPLE_METADATA = "Metadata-Version: 2.1\nName: foo\nVersion: 1.0\n"


def test_pkg1_only_benign_files(tmp_path: Path) -> None:
    """pycache and dist-info files only in package1 are expected"""
    pkg1 = make_pkg(
        tmp_path / "pkg1",
        files={
            "site-packages/foo/__pycache__/x.cpython-312.pyc": b"\x00",
            "site-packages/foo-1.0.dist-info/METADATA": SIMPLE_METADATA,
            "site-packages/foo-1.0.dist-info/INSTALLER": "whl2conda",
        },
    )
    pkg2 = make_pkg(
        tmp_path / "pkg2",
        files={"site-packages/foo-1.0.dist-info/METADATA": SIMPLE_METADATA},
    )
    result = compare(pkg1, pkg2)
    assert result.ok
    assert find(result, DiffCategory.PYCACHE, Severity.EXPECTED)
    assert find(result, DiffCategory.DIST_INFO_OTHER, Severity.EXPECTED)


def test_dist_info_one_sided(tmp_path: Path) -> None:
    """dist-info directory present on only one side is notable"""
    pkg1 = make_pkg(
        tmp_path / "pkg1",
        files={"site-packages/foo-1.0.dist-info/METADATA": SIMPLE_METADATA},
    )
    pkg2 = make_pkg(tmp_path / "pkg2")
    result = compare(pkg1, pkg2)
    notices = find(result, DiffCategory.DIST_INFO_OTHER, Severity.NOTICE)
    assert len(notices) == 1
    assert "package1" in notices[0].description


def test_dist_info_name_version_and_bad_requirement(tmp_path: Path) -> None:
    """METADATA name/version mismatch and unparsable requirements"""
    metadata1 = SIMPLE_METADATA + "Requires-Dist: ???unparsable\n"
    metadata2 = "Metadata-Version: 2.1\nName: bar\nVersion: 2.0\n"
    pkg1 = make_pkg(
        tmp_path / "pkg1",
        files={"site-packages/foo-1.0.dist-info/METADATA": metadata1},
    )
    pkg2 = make_pkg(
        tmp_path / "pkg2",
        files={"site-packages/bar-2.0.dist-info/METADATA": metadata2},
    )
    result = compare(pkg1, pkg2)
    errors = find(result, DiffCategory.DIST_INFO_METADATA, Severity.ERROR)
    assert {d.key for d in errors} == {
        "dist-info:METADATA:Name",
        "dist-info:METADATA:Version",
    }
    requirements = find(result, DiffCategory.DIST_INFO_METADATA, Severity.NOTICE)
    assert len(requirements) == 1
    assert "???unparsable" in requirements[0].left

    # missing METADATA file in one dist-info: no METADATA comparison
    pkg3 = make_pkg(
        tmp_path / "pkg3",
        files={"site-packages/foo-1.0.dist-info/INSTALLER": "conda"},
    )
    result = compare(pkg1, pkg3)
    assert not find(result, DiffCategory.DIST_INFO_METADATA)


def test_report_and_json_details(tmp_path: Path) -> None:
    """Report includes values; to_json handles list values"""
    pkg1 = make_pkg(tmp_path / "pkg1", depends=["python >=3.10", "numpy >=1.20"])
    pkg2 = make_pkg(tmp_path / "pkg2", depends=["python >=3.10", "numpy >=1.24"])
    result = compare(pkg1, pkg2)
    report = result.report()
    assert "package1: numpy >=1.20" in report
    assert "package2: numpy >=1.24" in report

    # list-valued left/right fields serialize to sorted string lists
    metadata1 = SIMPLE_METADATA + "Requires-Dist: numpy>=1.20\n"
    metadata2 = SIMPLE_METADATA + "Requires-Dist: numpy>=1.24\n"
    pkg3 = make_pkg(
        tmp_path / "pkg3",
        files={"site-packages/foo-1.0.dist-info/METADATA": metadata1},
    )
    pkg4 = make_pkg(
        tmp_path / "pkg4",
        files={"site-packages/foo-1.0.dist-info/METADATA": metadata2},
    )
    jobj = compare(pkg3, pkg4).to_json()
    md_diffs = [d for d in jobj["differences"] if d["category"] == "dist-info-metadata"]
    assert md_diffs and md_diffs[0]["left"] == ["numpy >=1.20"]


def test_about_field_notice(tmp_path: Path) -> None:
    """Genuinely differing about fields are notable"""
    pkg1 = make_pkg(tmp_path / "pkg1", about={"summary": "one thing"})
    pkg2 = make_pkg(tmp_path / "pkg2", about={"summary": "another thing"})
    result = compare(pkg1, pkg2)
    assert find(result, DiffCategory.ABOUT_FIELD, Severity.NOTICE)


def test_to_json_fallback_value(tmp_path: Path) -> None:
    """Non-primitive difference values serialize via str"""
    diff = Difference(
        DiffCategory.FILE_CONTENT,
        Severity.ERROR,
        "site-packages/foo.py",
        "test",
        left=Path("some/path"),
    )
    jobj = ComparisonResult(tmp_path, tmp_path, [diff]).to_json()
    assert jobj["differences"][0]["left"] == "some/path"


def test_default_renames(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Rename table defaults to the standard table (metadata keys dropped)"""
    monkeypatch.setattr(
        "whl2conda.api.compare.load_std_renames",
        lambda: {"foo-bar": "foo_bar", "$date": "whenever"},
    )
    pkg1 = make_pkg(tmp_path / "pkg1", depends=["python >=3.10", "foo-bar >=1"])
    pkg2 = make_pkg(tmp_path / "pkg2", depends=["python >=3.10", "foo_bar >=1"])
    result = compare_conda_packages(pkg1, pkg2, options=CompareOptions())
    assert find(result, DiffCategory.DEP_UNRENAMED, Severity.ERROR)


def test_bare_package_dir(tmp_path: Path) -> None:
    """Comparison tolerates a package directory without an info dir"""
    pkg1 = make_pkg(tmp_path / "pkg1")
    pkg2 = tmp_path / "pkg2"
    (pkg2 / "site-packages").mkdir(parents=True)
    (pkg2 / "site-packages" / "foo.py").write_text("")
    result = compare(pkg1, pkg2)
    assert not result.ok  # missing name/version/file
    assert find(result, DiffCategory.PACKAGE_NAME, Severity.ERROR)


def test_compare_package_files(
    simple_conda_package: Path,
    tmp_path: Path,
) -> None:
    """Real package files are extracted and compared"""
    result = compare(simple_conda_package, simple_conda_package)
    assert result.ok, result.report(min_severity=Severity.EXPECTED)
    assert not result.differences, result.report(min_severity=Severity.EXPECTED)

    # mutated extracted copy triggers findings
    import conda_package_handling.api as cphapi

    mutated = tmp_path / "mutated"
    cphapi.extract(str(simple_conda_package), mutated)
    index_file = mutated / "info" / "index.json"
    index = json.loads(index_file.read_text("utf8"))
    index["depends"].append("added-dep >=1")
    index_file.write_text(json.dumps(index))

    result = compare(simple_conda_package, mutated)
    assert not result.ok
    missing = find(result, DiffCategory.DEP_MISSING, Severity.ERROR)
    assert len(missing) == 1
    assert missing[0].right == "added-dep >=1"
