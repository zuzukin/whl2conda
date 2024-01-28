#  Copyright 2023-2024 Christopher Barber
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
"""
whl2conda command line interface
"""

from __future__ import annotations

# standard lib
import argparse
import logging
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

# this project
from ..impl.download import download_wheel
from ..impl.prompt import is_interactive, choose_wheel
from ..api.converter import Wheel2CondaConverter, CondaPackageFormat, DependencyRename
from ..impl.pyproject import read_pyproject, PyProjInfo
from .common import (
    add_markdown_help,
    dedent,
    existing_path,
    existing_dir,
    maybe_existing_dir,
)

__all__ = ["convert_main"]


# pylint: disable=too-many-instance-attributes
@dataclass
class Whl2CondaArgs:
    """
    Parsed arguments
    """

    build_number: Optional[int]
    build_wheel: bool
    dep_renames: Sequence[tuple[str, str]]
    dropped_deps: Sequence[str]
    dry_run: bool
    extra_deps: list[str]
    from_index: Optional[tuple[str, str]]
    from_pypi: Optional[str]
    ignore_pyproject: bool
    interactive: bool
    keep_pip_deps: bool
    name: str
    out_dir: Optional[Path]
    out_format: str
    overwrite: bool
    project_root: Optional[Path]
    python: str
    quiet: int
    verbose: int
    wheel_dir: Optional[Path]
    wheel_or_root: Optional[Path]
    yes: bool


def _create_argparser(prog: Optional[str] = None) -> argparse.ArgumentParser:
    """Creates the argument parser

    The parser will return a namespace with attributes matching
    Whl2CondaArgs
    """
    parser = argparse.ArgumentParser(
        usage=dedent("""
            %(prog)s <wheel> [options]
                   %(prog)s [<project-root>] [options]
            """),
        prog=prog,
        description=dedent("""
            Generates a conda package from a pure python wheel
            """),
        formatter_class=argparse.RawTextHelpFormatter,
        add_help=False,
    )

    # Sections
    input_opts = parser.add_argument_group("Input options")
    output_opts = parser.add_argument_group("Output options")
    override_opts = parser.add_argument_group("Override options")
    info_opts = parser.add_argument_group("Help and debug options")

    input_opts.add_argument(
        "wheel_or_root",
        nargs="?",
        metavar="[<wheel> | <project-root>]",
        type=existing_path,
        help=dedent("""
        Either path to a wheel file to convert or a project root
        directory containing a pyproject.toml or setup.py file.
        """),
    )

    input_opts.add_argument(
        "--project-root",
        "--root",
        dest="project_root",
        metavar="<dir>",
        type=existing_dir,
        help=dedent("""
            Project root directory. This is a directory containing either a
            pyproject.toml or a (deprecated) setup.py file. This option may
            not be used if the project directory was given as the positional
            argument.
            
            If not specified, the project root will be located by searching
            the wheel directory and its parent directories, or if no wheel
            given, will default to the current directory.
        """),
    )

    download_opts = input_opts.add_mutually_exclusive_group()
    download_opts.add_argument(
        "--from-pypi",
        metavar="<package-spec>",
        help=dedent("""
            Download package satisfying <package-spec> from standard pypi.org repository.
        """),
    )
    download_opts.add_argument(
        "--from-index",
        nargs=2,
        metavar=("<index-url>", "<package-spec>"),
        help=dedent("""
            Download package satisfying <package-spec> from repository at <index-url>.
        """),
    )

    input_opts.add_argument(
        "-w",
        "--wheel-dir",
        metavar="<dir>",
        type=maybe_existing_dir,
        help=dedent("""
            Location of wheel directory. Defaults to dist/ subdirectory of 
            project.
            """),
    )

    input_opts.add_argument(
        "--ignore-pyproject",
        action="store_true",
        help="Ignore settings from pyproject.toml file, if any",
    )

    output_opts.add_argument(
        "--out-dir",
        "--out",
        dest="out_dir",
        metavar="<dir>",
        type=maybe_existing_dir,
        help=dedent("""
            Output directory for conda package. Defaults to wheel directory
            or else project dist directory.
            """),
    )

    output_opts.add_argument(
        "--overwrite",
        action="store_true",
        help=dedent("""
            Overwrite existing output files.
            """),
    )

    output_opts.add_argument(
        "--format",
        "--out-format",
        choices=["V1", "tar.bz2", "V2", "conda", "tree"],
        dest="out_format",
        help="Output package format (%(default)s)",
    )
    output_opts.add_argument(
        "--build-wheel",
        action="store_true",
        help=dedent("""
            Build wheel
            """),
    )
    output_opts.add_argument(
        "--build-number",
        type=int,
        help="Specify build number. Otherwise taken from wheel.",
    )

    override_opts.add_argument(
        "--name",
        metavar="<package-name>",
        help="Override package name",
    )
    override_opts.add_argument(
        "-R",
        "--dependency-rename",
        nargs=2,
        metavar=("<pip-name>", "<conda-name>"),
        action="append",
        default=[],
        dest="dep_renames",
        help=dedent("""
        Rename pip dependency for conda. May be specified muliple times.
        """),
    )
    override_opts.add_argument(
        "-A",
        "--add-dependency",
        dest="extra_deps",
        metavar="<conda-dep>",
        action="append",
        default=[],
        help=dedent("""
            Add an additional conda dependency. May be specified multiple times.
            """),
    )
    override_opts.add_argument(
        "-D",
        "--drop-dependency",
        metavar="<pip-name>",
        dest="dropped_deps",
        action="append",
        default=[],
        help=dedent("""
            Drop dependency with given name from conda dependency list.
            May be specified multiple times.
            """),
    )
    override_opts.add_argument(
        "-K",
        "--keep-pip-dependencies",
        dest="keep_pip_deps",
        action="store_true",
        help="Retain pip dependencies in python dist_info of conda package.",
    )
    override_opts.add_argument(
        "--python",
        metavar="<version-spec>",
        default="",
        help="Set/override python dependency.",
    )

    info_opts.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Do not write any files.",
    )
    info_opts.add_argument(
        "--batch",
        "--not-interactive",
        dest='interactive',
        action="store_false",
        default=is_interactive(),
        help="Batch mode - disable interactive prompts.",
    )
    info_opts.add_argument(
        "--yes",
        action="store_true",
        help="Answer 'yes' or choose default to all interactive questions",
    )
    info_opts.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity.",
    )
    info_opts.add_argument(
        "-q",
        "--quiet",
        action="count",
        default=0,
        help="Less verbose output",
    )

    info_opts.add_argument(
        "-h",
        "-?",
        "--help",
        action="help",
        help="Show usage and exit.",
    )
    add_markdown_help(info_opts)

    return parser


def _parse_args(
    parser: argparse.ArgumentParser, args: Optional[Sequence[str]]
) -> Whl2CondaArgs:
    """Parse and return arguments"""
    return Whl2CondaArgs(**vars(parser.parse_args(args)))


def _is_project_root(path: Path) -> bool:
    return any(path.joinpath(f).is_file() for f in ["pyproject.toml", "setup.py"])


# pylint: disable=too-many-statements,too-many-branches,too-many-locals
def convert_main(args: Optional[Sequence[str]] = None, prog: Optional[str] = None):
    """
    Main command line interface
    """

    parser = _create_argparser(prog)
    parsed = _parse_args(parser, args)

    interactive = parsed.interactive
    always_yes = parsed.yes

    dry_run = parsed.dry_run
    # dry_run implies at least verbosity of 1 unless turned off by quiet flag
    verbosity = max(parsed.verbose, int(dry_run)) - parsed.quiet

    project_root: Optional[Path] = None
    wheel_file: Optional[Path] = None
    wheel_dir: Optional[Path] = parsed.wheel_dir

    build_wheel = parsed.build_wheel
    build_no_deps = True  # pylint: disable=unused-variable

    download_index = ""
    download_spec = ""
    if parsed.from_pypi:
        download_spec = parsed.from_pypi
    elif parsed.from_index:
        download_index, download_spec = parsed.from_index

    wheel_or_root = parsed.wheel_or_root
    saw_positional_root = False
    if not wheel_or_root:
        project_root = Path.cwd()
    else:
        if wheel_or_root.is_dir():
            project_root = wheel_or_root
            saw_positional_root = True
        else:
            wheel_file = wheel_or_root
            if wheel_file.suffix != ".whl":
                parser.error(f"Input file '{wheel_file} does not have .whl suffix")
            if not wheel_dir:
                wheel_dir = wheel_file.parent
            # Look for project root in wheel's parent directories
            if any((pr := p) for p in wheel_file.parents if _is_project_root(p)):
                project_root = pr

    if parsed.project_root:
        if saw_positional_root:
            parser.error(
                "Cannot specify project root as both positional and keyword argument."
            )
        project_root = parsed.project_root

    pyproj_info = PyProjInfo()
    if project_root and not parsed.ignore_pyproject:
        try:
            pyproj_info = read_pyproject(project_root)
        except FileNotFoundError:
            pass

    if project_root:
        project_root = project_root.expanduser().absolute()
        if not download_spec and not _is_project_root(project_root):
            # Note: don't complain about missing project file if using
            #  a download spec.
            parser.error(
                f"No pyproject.toml or setup.py in project root '{project_root}'"
            )
        if not wheel_dir:
            wheel_dir = pyproj_info.wheel_dir
            if not wheel_dir:
                # Use dist directory of project
                # TODO - check for build system specific alternate dist (#23)
                wheel_dir = project_root.joinpath("dist")

    # TODO - rearrange logic to make this more obvious?
    assert wheel_dir is not None
    wheel_dir = wheel_dir.expanduser().absolute()

    can_build = project_root is not None

    # assemble rename patterns and verify regular expression can be compiled
    renames: list[DependencyRename] = []
    source = str(pyproj_info.toml_file)
    try:
        for pat, repl in pyproj_info.dependency_rename:
            renames.append(DependencyRename.from_strings(pat, repl))
        source = "-R/--dependency-rename option"
        for pat, repl in parsed.dep_renames:
            renames.append(DependencyRename.from_strings(pat, repl))
        source = "-D/--drop-dependency option"
        for dropname in parsed.dropped_deps:
            renames.append(DependencyRename.from_strings(dropname, ""))
    except ValueError as ex:
        parser.error(f"Bad rename pattern from {source}:\n{ex}")

    out_dir: Optional[Path] = None
    if parsed.out_dir:
        out_dir = parsed.out_dir.expanduser().absolute()
    elif pyproj_info.out_dir:
        out_dir = pyproj_info.out_dir
    else:
        out_dir = wheel_dir

    if not wheel_file and wheel_dir and not build_wheel and not download_spec:
        # find wheel in directory
        try:
            wheel_file = choose_wheel(
                wheel_dir,
                interactive=interactive,
                choose_first=always_yes,
                can_build=can_build,
            )
            if wheel_file == Path('build'):
                build_wheel = True
                wheel_file = None
            elif wheel_file == Path("build-no-dep"):
                build_wheel = True
                build_no_deps = True
                wheel_file = None
        except FileNotFoundError as ex:
            if always_yes and can_build:
                build_wheel = True
            else:
                parser.error(str(ex))
        except Exception as ex:  # pylint: disable=broad-except
            parser.error(str(ex))

    if fmtname := parsed.out_format:
        if fmtname in ("V1", "tar.bz2"):
            out_fmt = CondaPackageFormat.V1
        elif fmtname in ("V2", "conda"):
            out_fmt = CondaPackageFormat.V2
        else:
            out_fmt = CondaPackageFormat.TREE
    elif pyproj_info.conda_format:
        out_fmt = pyproj_info.conda_format
    else:
        out_fmt = CondaPackageFormat.V2

    if verbosity < -1:
        level = logging.ERROR
    elif verbosity < 0:
        level = logging.WARNING
    elif verbosity == 0:
        level = logging.INFO
    elif verbosity == 1:
        level = logging.DEBUG
    else:  # verbosity >= 2:
        level = logging.DEBUG - 5

    logging.getLogger().setLevel(level)
    logging.basicConfig(level=level, format="%(message)s")

    with tempfile.TemporaryDirectory(
        dir=Path.cwd(), prefix="whl2conda-convert-"
    ) as tmpdirname:
        if not wheel_file:
            if download_spec:
                wheel_file = download_wheel(
                    download_spec,
                    into=Path(tmpdirname),
                    index=download_index,
                )
            elif build_wheel:  # pragma: no branch
                assert project_root and wheel_dir
                wheel_file = do_build_wheel(
                    project_root,
                    wheel_dir,
                    no_deps=build_no_deps,
                    dry_run=dry_run,
                    capture_output=level > logging.INFO,
                )

        assert wheel_file

        converter = Wheel2CondaConverter(wheel_file, out_dir)
        converter.dry_run = parsed.dry_run
        converter.package_name = (
            parsed.name or pyproj_info.conda_name or pyproj_info.name
        )
        converter.out_format = out_fmt
        converter.overwrite = parsed.overwrite
        converter.keep_pip_dependencies = parsed.keep_pip_deps
        converter.extra_dependencies.extend(pyproj_info.extra_dependencies)
        converter.extra_dependencies.extend(parsed.extra_deps)
        converter.python_version = parsed.python
        converter.interactive = interactive
        converter.build_number = parsed.build_number

        converter.dependency_rename.extend(renames)

        _conda_package = converter.convert()


def do_build_wheel(
    project_root: Path,
    wheel_dir: Path,
    *,
    no_deps: bool = True,
    no_build_isolation: bool = False,
    dry_run: bool = False,
    capture_output: bool = False,
) -> Path:
    """Build wheel for project

    Arguments:
        project_root: directory containing pyproject.toml or setup.py
        wheel_dir: target output directory, created as needed
        no_deps: build with --no-deps
        no_build_isolation: build with --no-build-isolation
        dry_run: just log, don't actually run anything
        capture_output: if True, capture output.

    Returns:
        path to created wheel

    Raises:
        CalledProcessError if pip command fails
    """
    logger = logging.getLogger(__name__)
    logger.info("Building wheel for %s", project_root)
    if not dry_run:
        wheel_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "pip",
        "wheel",
        str(project_root),
        "-w",
        str(wheel_dir),
    ]
    if no_deps:
        cmd.append("--no-deps")
    if no_build_isolation:
        cmd.append("--no-build-isolation")
    logger.info("Running: %s", cmd)
    if dry_run:
        wheel = wheel_dir.joinpath("dry-run-1.0-py3-none-any.whl")
    else:
        start = time.time()
        time.sleep(0.01)  # wait to avoid time resolution issues

        subprocess.run(
            cmd,
            check=True,
            capture_output=capture_output,
        )

        wheels = sorted(
            wheel_dir.glob("*.whl"),
            key=lambda p: p.stat().st_ctime,
            reverse=True,
        )

        assert wheels, f"No wheel created in '{wheel_dir}'"
        create_time = wheels[0].stat().st_ctime
        assert (
            create_time >= start
        ), f"Latest wheel {wheels[0]} has create time {create_time} older than start {start}"

        wheel = wheels[0]

    return wheel


if __name__ == "__main__":  # pragma: no cover
    convert_main()
