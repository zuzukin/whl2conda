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
External build test suite building conda-forge feedstock recipes.

For each project in the manifest, this downloads the project's
conda-forge feedstock recipe and source, builds the package with
`whl2conda build` using the local toolchain, and semantically compares
the result against the real conda-forge package of the same version.

These tests only run on demand:

    pixi run build-compare

A summary report is written to build-compare-report.json / .md
(directory overridden with WHL2CONDA_COMPARE_REPORT_DIR). Downloads are
cached across runs (override location with WHL2CONDA_TEST_CACHE).
"""

from __future__ import annotations

import urllib.error
from pathlib import Path
from typing import Any, NoReturn

import pytest

from whl2conda.api.compare import (
    CompareOptions,
    DiffCategory,
    compare_conda_packages,
)
from whl2conda.cli import main
from whl2conda.impl.conda_forge import (
    CondaForgeBuild,
    download_conda_forge_package,
    native_conda_subdir,
    query_conda_forge_builds,
)
from whl2conda.impl.recipe import render_recipe

from ..api.compare_support import (
    ComparisonReport,
    download_cache_dir,
    ignore_paths,
    select_conda_build,
)
from .build_compare_support import (
    BUILD_PROJECTS,
    BuildProject,
    SkipProject,
    fetch_feedstock,
    fetch_source,
    select_variant_file,
)


@pytest.fixture(scope="session")
def build_report() -> Any:
    """Session report, written to disk after the suite finishes."""
    report = ComparisonReport(
        basename="build-compare-report",
        title="whl2conda build vs conda-forge comparison report",
    )
    yield report
    report.write_to_report_dir()


def _select_reference(
    builds: list[CondaForgeBuild], version: str, pkg: Path
) -> CondaForgeBuild | None:
    """The conda-forge build to compare the built package against."""
    subdir = pkg.parent.name
    if subdir == "noarch":
        noarch = [b for b in builds if b.version == version and b.subdir == subdir]
        return max(noarch, key=lambda b: b.build_number, default=None)
    return select_conda_build(builds, version, subdir, abi3="_abi3_" in pkg.name)


@pytest.mark.external_build
@pytest.mark.parametrize("project", BUILD_PROJECTS, ids=lambda p: p.feedstock)
def test_build_conda_forge_feedstock(
    project: BuildProject,
    build_report: ComparisonReport,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """Build a conda-forge feedstock recipe and compare against conda-forge"""
    version = ""

    def record(status: str, detail: str = "", **kwargs: Any) -> None:
        build_report.add(
            project.feedstock,
            project.category,
            status=status,
            version=version,
            detail=detail,
            xfail_reason=project.xfail_reason,
            **kwargs,
        )

    def skip(detail: str) -> NoReturn:
        record("skipped", detail)
        pytest.skip(detail)

    def fail(status: str, detail: str) -> NoReturn:
        record(status, detail)
        if project.xfail_reason:
            pytest.xfail(f"{project.xfail_reason} ({status})")
        pytest.fail(f"{status}: {detail}")

    cache_dir = download_cache_dir()
    subdir = native_conda_subdir()

    #
    # Fetch and render the recipe
    #

    try:
        feedstock_dir = fetch_feedstock(project, tmp_path)
    except urllib.error.URLError as ex:  # pragma: no cover - network
        skip(f"network error fetching feedstock: {ex}")
    recipe_dir = feedstock_dir / "recipe"
    variant_file = select_variant_file(feedstock_dir, subdir)
    if variant_file is None:
        skip(f"feedstock has no variant config for {subdir} and this python")
    variant_args = ["-m", str(variant_file)]

    try:
        rendered = render_recipe(
            recipe_dir, work_dir=tmp_path / "render", variant_config=[variant_file]
        )
    except Exception as ex:
        fail("render-failed", str(ex))
    version = rendered.version

    try:
        builds = query_conda_forge_builds(rendered.name)
    except urllib.error.URLError as ex:  # pragma: no cover - network
        skip(f"network error querying {rendered.name}: {ex}")
    if not any(b.version == version for b in builds):
        skip(f"{rendered.name} {version} is not on conda-forge")

    #
    # Build the package from the project source
    #

    try:
        source_dir = fetch_source(rendered, cache_dir, tmp_path / "source")
    except SkipProject as ex:
        skip(str(ex))
    except urllib.error.URLError as ex:  # pragma: no cover - network
        skip(f"network error fetching source: {ex}")

    out_folder = tmp_path / "out"
    monkeypatch.chdir(source_dir)
    capsys.readouterr()
    try:
        main([
            "build",
            str(recipe_dir),
            *variant_args,
            "--output-folder",
            str(out_folder),
            "--no-test",
            *project.build_args,
        ])
    except (Exception, SystemExit) as ex:
        _out, err = capsys.readouterr()
        detail = str(ex) if not isinstance(ex, SystemExit) else ""
        detail = detail or "\n".join(err.strip().splitlines()[-3:])
        fail("build-failed", f"{type(ex).__name__}: {detail}")

    pkgs = [*out_folder.glob("*/*.conda"), *out_folder.glob("*/*.tar.bz2")]
    assert len(pkgs) == 1
    pkg = pkgs[0]

    #
    # Compare against the conda-forge package
    #

    reference = _select_reference(builds, version, pkg)
    if reference is None:
        skip(f"no conda-forge build of {rendered.name} {version} to match {pkg.name}")
    try:
        reference_file = cache_dir / reference.filename
        if not reference_file.is_file():
            reference_file = download_conda_forge_package(reference, cache_dir)
    except urllib.error.URLError as ex:  # pragma: no cover - network
        skip(f"network error downloading {reference.filename}: {ex}")

    options = CompareOptions(
        ignore={DiffCategory(cat) for cat in project.ignore},
        extra_run_exports=set(project.extra_run_exports),
    )
    result = compare_conda_packages(pkg, reference_file, options=options)
    ignore_paths(result, project.ignore_paths)
    detail = f"{pkg.name} vs {reference.filename}"
    if result.ok:
        record("ok", detail, result=result)
        return

    record("unexpected-differences", detail, result=result)
    if project.xfail_reason:
        pytest.xfail(
            f"{project.xfail_reason} ({len(result.errors)} unexpected differences)"
        )
    pytest.fail(result.report())
