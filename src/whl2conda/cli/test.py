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
whl2conda test implementation
"""

from __future__ import annotations

# standard
import argparse
import dataclasses
import logging
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

# this project
from ..impl.pyproject import PyProjInfo, read_pyproject
from ..impl.recipe import (
    RecipeError,
    recipe_source_root,
    render_recipe,
)
from .common import (
    add_markdown_help,
    dedent,
    existing_dir,
    existing_path,
    setup_logging,
)
from .testenv import PackageTestError, PackageTestSpec, run_package_tests

__all__ = ["test_main"]

logger = logging.getLogger(__name__)


@dataclasses.dataclass(slots=True)
class TestArgs:
    """Parsed arguments for whl2conda test"""

    package_file: Path
    project_dir: Path
    channels: list[str]
    debug: bool
    dry_run: bool
    keep_test_env: bool
    prefix: Path | None
    python: list[str]
    quiet: int
    test_file: Path | None
    use_mamba: bool
    variant_config: list[Path]


def _create_argparser(prog: str | None = None) -> argparse.ArgumentParser:
    """Create the argument parser for whl2conda test."""
    parser = argparse.ArgumentParser(
        usage="%(prog)s <package-file> [<project-dir>] [options]",
        description=dedent("""
            Test a conda package file in a fresh conda environment.

            Installs the package into a new environment (along with any
            test requirements) and runs the tests specified by, in order
            of precedence: the --test-file option, the
            [tool.whl2conda.tests] section of a pyproject.toml, or the
            test section of a conda recipe (meta.yaml or recipe.yaml)
            found in the project directory.
            """),
        formatter_class=argparse.RawTextHelpFormatter,
        prog=prog,
        allow_abbrev=False,
    )

    parser.add_argument(
        "package_file",
        metavar="<package-file>",
        type=existing_path,
        help="Conda package file (.conda or .tar.bz2) to test",
    )
    parser.add_argument(
        "project_dir",
        metavar="<project-dir>",
        nargs="?",
        default=Path.cwd(),
        type=existing_dir,
        help=dedent("""
            Directory containing the test specification: either a
            pyproject.toml with a [tool.whl2conda.tests] section or a
            conda recipe. Defaults to the current directory.
            """),
    )

    test_opts = parser.add_argument_group("test options")
    test_opts.add_argument(
        "--test-file",
        metavar="<yaml-file>",
        type=existing_path,
        help=dedent("""
            Read tests from given YAML file containing a v1 recipe
            `tests` list (either a bare list or a mapping with a
            `tests` key), overriding any project test specification.
            """),
    )
    test_opts.add_argument(
        "-c",
        "--channel",
        action="append",
        dest="channels",
        default=[],
        metavar="<channel>",
        help="Additional channel for the test environment. May be repeated.",
    )
    test_opts.add_argument(
        "--python",
        action="append",
        default=[],
        metavar="<version>",
        help=dedent("""
            Python version to test against, e.g. '3.11'. May be
            repeated to test against multiple versions. Overrides
            any tool.whl2conda.test-python setting. If not specified,
            the solver chooses the version.
            """),
    )
    test_opts.add_argument(
        "-p",
        "--prefix",
        metavar="<env-path>",
        type=Path,
        help=dedent("""
            Path of test environment to create, instead of a
            location in a temporary work directory. Only allowed
            with a single python version. The environment is still
            removed after testing unless --keep-test-env is given.
            """),
    )
    test_opts.add_argument(
        "-m",
        "--variant-config-files",
        dest="variant_config",
        metavar="<file>",
        action="append",
        default=[],
        type=existing_path,
        help=dedent("""
            Additional variant configuration file passed to the recipe
            renderer when reading tests from a recipe. May be repeated.
            """),
    )
    test_opts.add_argument(
        "--keep-test-env",
        action="store_true",
        help="Do not delete the test environment (for debugging).",
    )
    test_opts.add_argument(
        "--mamba",
        dest="use_mamba",
        action="store_true",
        help="Use mamba instead of conda to create and run test environments.",
    )

    common_opts = parser.add_argument_group("common options")
    common_opts.add_argument(
        "--dry-run",
        action="store_true",
        help="Display the tests that would be run without running them.",
    )
    common_opts.add_argument(
        "-q",
        "--quiet",
        action="count",
        default=0,
        help="Less verbose output. May be repeated.",
    )
    common_opts.add_argument(
        "--debug",
        action="store_true",
        help="Show debug output.",
    )
    add_markdown_help(parser)
    return parser


def test_main(
    args: Sequence[str] | None = None,
    prog: str | None = None,
) -> None:
    """Main procedure for `whl2conda test` command"""
    parser = _create_argparser(prog)
    parsed = parser.parse_args(args)
    testargs = TestArgs(**vars(parsed))

    setup_logging((1 if testargs.debug else 0) - testargs.quiet)

    if testargs.prefix and len(testargs.python) > 1:
        parser.error("-p/--prefix is not allowed with multiple --python versions")

    work_dir = Path(tempfile.mkdtemp(prefix="whl2conda-test-"))
    try:
        spec, source_root, project_python = _resolve_test_spec(testargs, work_dir)
        if not spec:
            parser.error(
                f"No tests found for {testargs.project_dir}: expected a"
                " --test-file, a [tool.whl2conda.tests] pyproject section,"
                " or a recipe with a test section"
            )

        python_versions: Sequence[str] = testargs.python or project_python or [""]

        if testargs.dry_run:
            versions = ", ".join(v for v in python_versions if v) or "<default>"
            print(f"python versions: {versions}")
            print(spec.describe())
            return

        for python_version in python_versions:
            if python_version:
                logger.info("Testing with python %s", python_version)
            env_suffix = f"-{python_version}" if python_version else ""
            env_prefix = testargs.prefix or work_dir / f"test-env{env_suffix}"
            run_package_tests(
                testargs.package_file,
                spec,
                env_prefix=env_prefix,
                work_dir=work_dir / f"test_tmp{env_suffix}",
                source_root=source_root,
                channels=testargs.channels,
                keep_env=testargs.keep_test_env,
                use_mamba=testargs.use_mamba,
                python_version=python_version,
            )
        logger.info("All package tests passed")
    except RecipeError as ex:
        parser.error(str(ex))
    except PackageTestError as ex:
        print(f"ERROR: {ex}", file=sys.stderr)
        sys.exit(1)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _resolve_test_spec(
    testargs: TestArgs,
    work_dir: Path,
) -> tuple[PackageTestSpec, Path, Sequence[str]]:
    """Resolve the test spec, source root, and project python versions.

    Sources, in order of precedence: the --test-file option, the
    pyproject.toml [tool.whl2conda.tests] section, and the test section
    of a rendered conda recipe in the project directory.
    """
    if testargs.test_file:
        spec = PackageTestSpec.from_file(testargs.test_file)
        return spec, testargs.test_file.parent.absolute(), ()

    project_dir = testargs.project_dir
    pyproj = PyProjInfo()
    if project_dir.joinpath("pyproject.toml").is_file():
        pyproj = read_pyproject(project_dir)
    if pyproj.tests:
        spec = PackageTestSpec.from_v1_tests(pyproj.tests)
        return spec, project_dir.absolute(), pyproj.test_python

    if not any(
        project_dir.joinpath(name).is_file() for name in ("meta.yaml", "recipe.yaml")
    ):
        return PackageTestSpec(), project_dir.absolute(), ()

    rendered = render_recipe(
        project_dir,
        work_dir=work_dir,
        use_mamba=testargs.use_mamba,
        variant_config=testargs.variant_config,
    )
    spec = PackageTestSpec.from_rendered_recipe(rendered)
    return spec, recipe_source_root(rendered, work_dir), pyproj.test_python
