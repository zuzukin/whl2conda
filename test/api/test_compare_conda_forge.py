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
External test suite comparing binary wheel conversions against conda-forge.

For each package in the curated manifest, this downloads the newest
version that has both a compatible binary wheel on PyPI and a matching
conda-forge build, converts the wheel with `--allow-impure`, and
semantically compares the result against the real conda-forge package.

Run with:

    pixi run compare-conda-forge

A summary report is written to compare-report.json / compare-report.md
(directory overridden with WHL2CONDA_COMPARE_REPORT_DIR). Downloads are
cached across runs (override location with WHL2CONDA_TEST_CACHE).
"""

from __future__ import annotations

import sys
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from whl2conda.api.compare import (
    CompareOptions,
    ComparisonResult,
    DiffCategory,
    Difference,
    Severity,
    compare_conda_packages,
)
from whl2conda.api.converter import Wheel2CondaConverter
from whl2conda.impl.conda_forge import CondaForgeBuild, download_conda_forge_package

from .compare_support import (
    COMPARISON_PACKAGES,
    ComparisonPackage,
    ComparisonReport,
    NoCommonVersion,
    cached_download,
    download_cache_dir,
    find_common_version,
    ignore_paths,
    select_conda_build,
    wheel_is_abi3,
)

_PY_MAJOR, _PY_MINOR = sys.version_info[:2]
_CP = f"cp{_PY_MAJOR}{_PY_MINOR}"
_PY_ABI = f"python_abi {_PY_MAJOR}.{_PY_MINOR}.* *_{_CP}"


def _build(build: str, *depends: str, build_number: int = 0) -> CondaForgeBuild:
    return CondaForgeBuild(
        name="foo",
        version="1.0",
        build=build,
        build_number=build_number,
        subdir="linux-64",
        filename=f"foo-1.0-{build}.conda",
        url="",
        depends=("python", *depends),
    )


def testwheel_is_abi3() -> None:
    """Unit test for wheel_is_abi3"""
    assert wheel_is_abi3("foo-1.0-cp39-abi3-manylinux_2_28_x86_64.whl")
    assert not wheel_is_abi3("foo-1.0-cp312-cp312-manylinux_2_28_x86_64.whl")
    assert not wheel_is_abi3("not-a-wheel.txt")


def testselect_conda_build() -> None:
    """Unit test for select_conda_build"""
    exact = _build("py_exact_0", _PY_ABI)
    exact2 = _build("py_exact_1", _PY_ABI, build_number=1)
    freethreaded = _build("py_ft_0", f"{_PY_ABI}t")
    other_py = _build("py_other_0", "python_abi 2.7.* *_cp27")
    abi3 = _build("py_abi3_0", "_python_abi3_support 1.*", "cpython >=3.0")
    abi3_too_new = _build(
        "py_abi3_new_0", "_python_abi3_support 1.*", "cpython >=3.999"
    )

    def select(*builds: CondaForgeBuild, abi3: bool = False):
        return select_conda_build(list(builds), "1.0", "linux-64", abi3=abi3)

    # regular wheels need an exact, non-free-threaded python match
    assert select(other_py, freethreaded, exact) is exact
    assert select(exact, exact2, other_py) is exact2
    assert select(other_py, freethreaded, abi3) is None
    assert select_conda_build([exact], "2.0", "linux-64") is None
    assert select_conda_build([exact], "1.0", "osx-arm64") is None

    # abi3 wheels prefer compatible CEP-20 abi3 builds
    assert select(freethreaded, exact, abi3, abi3=True) is abi3
    assert select(freethreaded, exact, abi3_too_new, abi3=True) is exact
    assert select(freethreaded, other_py, abi3_too_new, abi3=True) is None


def test_ignore_paths() -> None:
    """Unit test for ignore_paths"""

    def diff(key: str, severity: Severity = Severity.ERROR) -> Difference:
        return Difference(DiffCategory.FILE_EXTRA, severity, key, "")

    result = ComparisonResult(
        Path("a.conda"),
        Path("b.conda"),
        [diff("site-packages/foo/__init__.py"), diff("site-packages/bar.py")],
    )
    ignore_paths(result, ())
    assert len(result.errors) == 2

    ignore_paths(result, ("site-packages/foo/*",))
    assert [d.key for d in result.errors] == ["site-packages/bar.py"]
    assert result.differences[0].severity == Severity.EXPECTED

    ignore_paths(result, ("*/bar.py",))
    assert result.ok


@pytest.fixture(scope="session")
def compare_report() -> Any:
    """Session report, written to disk after the suite finishes."""
    report = ComparisonReport()
    yield report
    report.write_to_report_dir()


@pytest.fixture(scope="session")
def download_cache() -> Path:
    """Persistent cross-run download cache directory."""
    return download_cache_dir()


@pytest.mark.external
@pytest.mark.slow
@pytest.mark.parametrize("entry", COMPARISON_PACKAGES, ids=lambda e: e.pypi_name)
def test_compare_with_conda_forge(
    entry: ComparisonPackage,
    compare_report: ComparisonReport,
    download_cache: Path,
    tmp_path: Path,
) -> None:
    """Convert a binary PyPI wheel and compare against conda-forge"""
    try:
        common = find_common_version(entry)
    except NoCommonVersion as ex:
        compare_report.add_package(entry, status="skipped", detail=str(ex))
        pytest.skip(str(ex))
    except urllib.error.URLError as ex:  # pragma: no cover - network
        detail = f"network error querying {entry.pypi_name}: {ex}"
        compare_report.add_package(entry, status="skipped", detail=detail)
        pytest.skip(detail)

    try:
        wheel_file = cached_download(
            common.wheel.url, common.wheel.filename, download_cache
        )
        conda_file = download_cache / common.conda_build.filename
        if not conda_file.is_file():
            conda_file = download_conda_forge_package(
                common.conda_build, download_cache
            )
    except urllib.error.URLError as ex:  # pragma: no cover - network
        detail = f"network error downloading {entry.pypi_name}: {ex}"
        compare_report.add_package(entry, status="skipped", detail=detail)
        pytest.skip(detail)

    converter = Wheel2CondaConverter(wheel_file, out_dir=tmp_path)
    converter.allow_impure = True
    converter.overwrite = True
    converter.package_name = entry.resolve_conda_name()
    converted = converter.convert()

    options = CompareOptions(
        ignore={DiffCategory(cat) for cat in entry.ignore},
        extra_run_exports=set(entry.extra_run_exports),
    )
    result = compare_conda_packages(converted, conda_file, options=options)
    ignore_paths(result, entry.ignore_paths)
    status = "ok" if result.ok else "unexpected-differences"
    compare_report.add_package(
        entry, status=status, version=common.version, result=result
    )

    if not result.ok:
        if entry.xfail_reason:
            pytest.xfail(
                f"{entry.xfail_reason} ({len(result.errors)} unexpected differences)"
            )
        pytest.fail(result.report())
