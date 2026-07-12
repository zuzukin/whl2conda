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
whl2conda build implementation
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import shutil
import subprocess
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

from ..api.converter import (
    CondaPackageFormat,
    Wheel2CondaConverter,
    noarch_build_string,
    normalize_pypi_name,
)

# this project
from ..impl.recipe import (
    RecipeError,
    RenderedRecipe,
    render_recipe,
    rewrite_build_script,
)
from .common import (
    add_markdown_help,
    dedent,
    existing_dir,
    get_conda_bld_path,
    maybe_existing_dir,
)
from .install import install_into_conda_bld
from .testenv import PackageTestSpec, run_package_tests

__all__ = ["build_main", "predict_package_path"]

logger = logging.getLogger(__name__)


def predict_package_path(
    rendered: RenderedRecipe,
    conda_bld_path: Path,
    package_format: CondaPackageFormat,
) -> Path:
    """Predict the file path of the package built from a rendered recipe.

    Uses the same name normalization and build string generation as the
    wheel converter, so the prediction matches the actual output.

    Args:
        rendered: the rendered recipe
        conda_bld_path: conda-bld (or output) directory containing the
            `noarch/` subdirectory the package lands in
        package_format: the conda package format

    Raises:
        RecipeError: if the recipe does not build a noarch python package.
    """
    if not rendered.noarch_python:
        raise RecipeError(
            f"Cannot predict package path for recipe in {rendered.recipe_dir}:"
            " it does not build a `noarch: python` package"
        )
    name = normalize_pypi_name(rendered.name)
    build_string = noarch_build_string(rendered.build_number)
    suffix = str(package_format.value)
    return (
        conda_bld_path / "noarch" / f"{name}-{rendered.version}-{build_string}{suffix}"
    )


@dataclasses.dataclass(slots=True)
class BuildArgs:
    """Parsed arguments for whl2conda build"""

    recipe_path: list[Path]
    build_only: bool
    channels: list[str]
    check: bool
    croot: Path | None
    debug: bool
    extra_deps: list[str]
    keep_test_env: bool
    no_test: bool
    output: bool
    output_folder: Path | None
    package_format: CondaPackageFormat | None
    python: str
    quiet: int
    skip_existing: bool
    test_only: bool


class _IgnoredOption(argparse.Action):
    """Accepted for conda-build compatibility but ignored (warns once)."""

    warned: ClassVar[set[str]] = set()

    def __init__(self, *args, **kwargs) -> None:
        kwargs["dest"] = argparse.SUPPRESS
        kwargs["default"] = argparse.SUPPRESS
        super().__init__(*args, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None) -> None:
        if option_string not in self.warned:
            self.warned.add(str(option_string))
            logger.warning("ignoring unsupported option: %s", option_string)


class _UnsupportedOption(argparse.Action):
    """conda-build option that whl2conda build loudly rejects."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs["dest"] = argparse.SUPPRESS
        kwargs["default"] = argparse.SUPPRESS
        super().__init__(*args, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None) -> None:
        parser.error(f"{option_string} is not supported by whl2conda build")


# conda build options accepted and ignored, as (flags, nargs) pairs
# where nargs 0 is a plain flag and 1 takes a value (see issue #110)
_IGNORED_OPTIONS: list[tuple[tuple[str, ...], int]] = [
    (("--no-anaconda-upload", "--no-binstar-upload"), 0),
    (("--no-force-upload",), 0),
    (("--no-include-recipe",), 0),
    (("--verify",), 0),
    (("--no-verify",), 0),
    (("--strict-verify",), 0),
    (("--no-activate",), 0),
    (("--no-build-id",), 0),
    (("--build-id-pat",), 1),
    (("--prefix-length",), 1),
    (("--no-prefix-length-fallback",), 0),
    (("--prefix-length-fallback",), 0),
    (("--no-locking",), 0),
    (("--error-overlinking",), 0),
    (("--no-error-overlinking",), 0),
    (("--error-overdepending",), 0),
    (("--no-error-overdepending",), 0),
    (("--long-test-prefix",), 0),
    (("--no-long-test-prefix",), 0),
    (("--merge-build-host",), 0),
    (("--old-build-string",), 0),
    (("--bootstrap",), 1),
    (("--cache-dir",), 1),
    (("--stats-file",), 1),
    (("-p", "--post"), 0),
    (("--test-run-post",), 0),
    (("--keep-going", "-k"), 0),
    (("--keep-old-work",), 0),
    (("--dirty",), 0),
    (("--no-remove-work-dir",), 0),
    (("--zstd-compression-level",), 1),
    (("-m", "--variant-config-files"), 1),
    (("--variants",), 1),
    (("-e", "--exclusive-config-files", "--exclusive-config-file"), 1),
    (("--append-file",), 1),
    (("--clobber-file",), 1),
    (("--extra-meta",), 1),
    (("--numpy",), 1),
]

# conda build options that are rejected with an error (see issue #110)
_UNSUPPORTED_OPTIONS: list[tuple[tuple[str, ...], int]] = [
    (("-n", "--no-source"), 0),
    (("--token",), 1),
    (("--user",), 1),
    (("--label",), 1),
    (("--password",), 1),
    (("--sign",), 1),
    (("--sign-with",), 1),
    (("--identity",), 1),
    (("-r", "--repository"), 1),
    (("--perl",), 1),
    (("--R",), 1),
    (("--lua",), 1),
]


def _package_format(value: str) -> CondaPackageFormat:
    """argparse type for conda build --package-format values."""
    val = value.lower().lstrip(".")
    if val in ("1", "tar.bz2"):
        return CondaPackageFormat.V1
    if val in ("2", "conda"):
        return CondaPackageFormat.V2
    raise argparse.ArgumentTypeError(
        f"invalid package format '{value}' - use 1/tar.bz2 or 2/conda"
    )


def _create_argparser(prog: str | None = None) -> argparse.ArgumentParser:
    """Create the argument parser for whl2conda build."""
    parser = argparse.ArgumentParser(
        usage="%(prog)s <recipe-path> [options]",
        description=dedent("""
            Build a conda package from a pure python wheel.

            This command is a limited drop-in replacement for `conda build`
            for recipes of pure python packages whose build script is a
            `pip install .` or `pip wheel .` command: it builds the wheel
            and converts it directly to a conda package without creating
            a build environment.

            Most conda build options that do not apply to this build
            model are accepted and ignored with a warning; options whose
            omission would silently change the meaning of a build
            pipeline (e.g. package uploads) are rejected with an error.

            This is an experimental feature and is still under active
            change and development.
            """),
        formatter_class=argparse.RawTextHelpFormatter,
        prog=prog,
        allow_abbrev=False,
    )

    parser.add_argument(
        "recipe_path",
        metavar="RECIPE_PATH",
        nargs="+",
        type=existing_dir,
        help="Path to directory containing the conda recipe",
    )

    mode_opts = parser.add_argument_group(
        "Build mode options"
    ).add_mutually_exclusive_group()
    mode_opts.add_argument(
        "--output",
        action="store_true",
        help="Print the path of the output package without building.",
    )
    mode_opts.add_argument(
        "--check",
        action="store_true",
        help=dedent("""
            Only render the recipe and verify that whl2conda can build
            it, without building anything. (whl2conda extension)
            """),
    )
    mode_opts.add_argument(
        "-t",
        "--test",
        dest="test_only",
        action="store_true",
        help=dedent("""
            Test the already-built package for this recipe instead of
            building. Unlike conda build, the recipe path is still
            required (the package location is derived from the recipe).
            """),
    )
    mode_opts.add_argument(
        "-b",
        "--build-only",
        action="store_true",
        help="Only build the package; do not test or install it.",
    )
    mode_opts.add_argument(
        "--no-test",
        action="store_true",
        help="Build and install the package without testing it.",
    )

    conda_opts = parser.add_argument_group("conda build options")
    conda_opts.add_argument(
        "-c",
        "--channel",
        action="append",
        dest="channels",
        default=[],
        metavar="<channel>",
        help="Additional channel to search for packages. May be repeated.",
    )
    conda_opts.add_argument(
        "--output-folder",
        metavar="<dir>",
        type=maybe_existing_dir,
        help=dedent("""
            Folder to write the output package to, instead of installing
            it into the local conda-bld directory.
            """),
    )
    conda_opts.add_argument(
        "--package-format",
        metavar="<format>",
        type=_package_format,
        help="Output package format: '1'/'tar.bz2' or '2'/'conda' (default)",
    )
    conda_opts.add_argument(
        "--croot",
        metavar="<dir>",
        type=maybe_existing_dir,
        help="Use this conda-bld directory instead of the configured one.",
    )
    conda_opts.add_argument(
        "--python",
        metavar="<version-spec>",
        default="",
        help="Override the python dependency of the generated package.",
    )
    conda_opts.add_argument(
        "--skip-existing",
        action="store_true",
        help="Do not rebuild the package if it already exists.",
    )
    conda_opts.add_argument(
        "-q",
        "--quiet",
        action="count",
        default=0,
        help="Less verbose output. May be repeated.",
    )
    conda_opts.add_argument(
        "--debug",
        action="store_true",
        help="Show debug output.",
    )

    extension_opts = parser.add_argument_group("whl2conda extensions")
    extension_opts.add_argument(
        "--extra-deps",
        metavar="<conda-dep>",
        action="append",
        default=[],
        help="Additional conda dependency for the package. May be repeated.",
    )
    extension_opts.add_argument(
        "--keep-test-env",
        action="store_true",
        help="Do not delete the test environment (for debugging).",
    )

    ignored_opts = parser.add_argument_group(
        "ignored conda build options",
        description=dedent("""
            Other conda build options are accepted and ignored with a
            warning, except for upload/signing and non-python language
            options, which are rejected.
            """),
    )
    for flags, nargs in _IGNORED_OPTIONS:
        ignored_opts.add_argument(
            *flags,
            nargs=None if nargs else 0,
            action=_IgnoredOption,
            help=argparse.SUPPRESS,
        )
    for flags, nargs in _UNSUPPORTED_OPTIONS:
        ignored_opts.add_argument(
            *flags,
            nargs=None if nargs else 0,
            action=_UnsupportedOption,
            help=argparse.SUPPRESS,
        )

    add_markdown_help(parser)
    return parser


def build_main(
    args: Sequence[str] | None = None,
    prog: str | None = None,
) -> None:
    """Main procedure for `whl2conda build` command"""
    _IgnoredOption.warned.clear()
    parser = _create_argparser(prog)
    parsed = parser.parse_args(args)
    buildargs = BuildArgs(**vars(parsed))

    if len(buildargs.recipe_path) > 1:
        parser.error("only one recipe path is supported")

    verbosity = (1 if buildargs.debug else 0) - buildargs.quiet
    if verbosity < -1:
        level = logging.ERROR
    elif verbosity < 0:
        level = logging.WARNING
    elif verbosity == 0:
        level = logging.INFO
    else:
        level = logging.DEBUG
    logging.getLogger().setLevel(level)
    logging.basicConfig(level=level, format="%(message)s")

    builder = CondaBuild(buildargs)
    try:
        builder.run()
    except RecipeError as ex:
        parser.error(str(ex))


class CondaBuild:
    """Implement build command"""

    args: BuildArgs
    recipe_path: Path
    work_dir: Path
    build_script: list[str]
    subdir: str

    def __init__(self, args: BuildArgs):
        self.args = args
        self.recipe_path = args.recipe_path[0]
        self.work_dir = Path("does-not-exist")
        self.build_script = []
        self.subdir = "noarch"

    def run(self) -> None:
        """Run the build logic"""
        start = time.time()
        try:
            self.work_dir = Path(tempfile.mkdtemp(prefix="whl2conda-build-"))
            rendered = render_recipe(self.recipe_path, self.work_dir)

            if self.args.output:
                print(self._package_path(rendered))
                return

            if self.args.test_only:
                pkg_path = self._package_path(rendered)
                if not pkg_path.is_file():
                    raise RecipeError(
                        f"No package to test at {pkg_path} - build it first"
                    )
                self._run_package_tests(pkg_path, rendered)
                return

            if self.args.skip_existing:
                pkg_path = self._package_path(rendered)
                if pkg_path.is_file():
                    logger.info("Skipping existing package %s", pkg_path)
                    return

            dist_dir = self.work_dir / "dist"
            dist_dir.mkdir()
            self.build_script = rewrite_build_script(rendered, dist_dir)
            if self.args.check:
                logger.info("whl2conda can build the recipe in %s", self.recipe_path)
                return
            wheel = self._build_wheel(dist_dir)
            pkg = self._build_package(wheel, rendered)
            if not (self.args.no_test or self.args.build_only):
                self._run_package_tests(pkg, rendered)
            if not (self.args.build_only or self.args.output_folder):
                self._install_package(pkg)
        finally:
            self._cleanup()
        end = time.time()
        logger.info("Elapsed time: %f seconds", end - start)

    def _package_path(self, rendered: RenderedRecipe) -> Path:
        """Predict the path of the package built from this recipe.

        This is the path in the output folder, if one was given, and
        otherwise in the conda-bld directory the package would be
        installed into.
        """
        if self.args.output_folder:
            bld_path = self.args.output_folder
        elif self.args.croot:
            bld_path = self.args.croot
        else:
            bld_path = get_conda_bld_path()
        fmt = self.args.package_format or CondaPackageFormat.V2
        return predict_package_path(rendered, bld_path, fmt)

    def _build_wheel(self, dist_dir: Path) -> Path:
        for line in self.build_script:
            subprocess.check_call(line, shell=True)
        try:
            return next(dist_dir.glob("*.whl"))
        except StopIteration:
            raise RecipeError(
                f"Build script did not produce a wheel in {dist_dir}"
            ) from None

    def _build_package(self, wheel: Path, rendered: RenderedRecipe) -> Path:
        out_dir = self.work_dir
        if self.args.output_folder:
            out_dir = self.args.output_folder / "noarch"
        converter = Wheel2CondaConverter(wheel, out_dir)
        if self.args.package_format:
            converter.out_format = self.args.package_format
        converter.extra_dependencies.extend(self.args.extra_deps)
        converter.python_version = self.args.python
        converter.build_number = rendered.build_number
        converter.overwrite = True
        pkg = converter.convert()
        if converter.conda_target is not None:
            self.subdir = converter.conda_target.subdir
        return pkg

    def _run_package_tests(self, pkg: Path, rendered: RenderedRecipe) -> None:
        spec = PackageTestSpec.from_meta_yaml(rendered.raw.get("test") or {})
        if not spec:
            return
        # conda-build's render copies the source tree into its work dir,
        # from which test source_files are resolved
        source_root = self.recipe_path
        for work_src in sorted(self.work_dir.glob("croot/*/work")):
            source_root = work_src
            break
        run_package_tests(
            pkg,
            spec,
            env_prefix=self.work_dir / "test-env",
            work_dir=self.work_dir / "test_tmp",
            source_root=source_root,
            channels=self.args.channels,
            keep_env=self.args.keep_test_env,
        )

    def _install_package(self, pkg: Path) -> None:
        install_into_conda_bld([pkg], self.subdir, conda_bld_path=self.args.croot)

    def _cleanup(self) -> None:
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir, ignore_errors=True)
