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

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from platformdirs import user_cache_path

from whl2conda.api.compare import (
    CompareOptions,
    ComparisonResult,
    DiffCategory,
    compare_conda_packages,
)
from whl2conda.api.converter import Wheel2CondaConverter
from whl2conda.impl.conda_forge import download_conda_forge_package

from .compare_support import (
    COMPARISON_PACKAGES,
    ComparisonPackage,
    NoCommonVersion,
    find_common_version,
)


@dataclass
class ComparisonReport:
    """Accumulates per-package comparison outcomes."""

    entries: list[dict[str, Any]] = field(default_factory=list)

    def add(
        self,
        package: ComparisonPackage,
        *,
        status: str,
        version: str = "",
        detail: str = "",
        result: ComparisonResult | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "package": package.pypi_name,
            "category": package.category,
            "status": status,
            "version": version,
            "detail": detail,
        }
        if package.xfail_reason:
            entry["xfail_reason"] = package.xfail_reason
        if result is not None:
            entry["errors"] = len(result.errors)
            entry["notices"] = sum(
                1 for d in result.differences if d.severity.name == "NOTICE"
            )
            entry["comparison"] = result.to_json()
        self.entries.append(entry)

    def write(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        json_file = out_dir / "compare-report.json"
        json_file.write_text(json.dumps(self.entries, indent=2), "utf8")

        lines = [
            "# conda-forge comparison report",
            "",
            "| package | category | version | status | errors | notices |",
            "|---------|----------|---------|--------|--------|---------|",
        ]
        columns = ("package", "category", "version", "status", "errors", "notices")
        lines.extend(
            "| " + " | ".join(str(entry.get(col, "")) for col in columns) + " |"
            for entry in self.entries
        )
        md_file = out_dir / "compare-report.md"
        md_file.write_text("\n".join(lines) + "\n", "utf8")
        print(f"\nComparison report written to {json_file} and {md_file}")


@pytest.fixture(scope="session")
def compare_report() -> Any:
    """Session report, written to disk after the suite finishes."""
    report = ComparisonReport()
    yield report
    if report.entries:
        out_dir = Path(os.environ.get("WHL2CONDA_COMPARE_REPORT_DIR", "."))
        report.write(out_dir)


@pytest.fixture(scope="session")
def download_cache() -> Path:
    """Persistent cross-run download cache directory."""
    if override := os.environ.get("WHL2CONDA_TEST_CACHE"):
        cache_dir = Path(override)
    else:
        cache_dir = user_cache_path("whl2conda-tests") / "compare"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _cached_download(url: str, filename: str, cache_dir: Path) -> Path:
    target = cache_dir / filename
    if not target.is_file():
        with urllib.request.urlopen(url, timeout=60.0) as response:
            target.write_bytes(response.read())
    return target


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
        compare_report.add(entry, status="skipped", detail=str(ex))
        pytest.skip(str(ex))
    except urllib.error.URLError as ex:  # pragma: no cover - network
        pytest.skip(f"network error querying {entry.pypi_name}: {ex}")

    try:
        wheel_file = _cached_download(
            common.wheel.url, common.wheel.filename, download_cache
        )
        conda_file = download_cache / common.conda_build.filename
        if not conda_file.is_file():
            conda_file = download_conda_forge_package(
                common.conda_build, download_cache
            )
    except urllib.error.URLError as ex:  # pragma: no cover - network
        pytest.skip(f"network error downloading {entry.pypi_name}: {ex}")

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
    status = "ok" if result.ok else "unexpected-differences"
    compare_report.add(entry, status=status, version=common.version, result=result)

    if not result.ok:
        if entry.xfail_reason:
            pytest.xfail(
                f"{entry.xfail_reason} ({len(result.errors)} unexpected differences)"
            )
        pytest.fail(result.report())
