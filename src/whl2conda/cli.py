#  Copyright 2023 Christopher Barber
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

import argparse
import logging
import subprocess
import sys
import time
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from .__about__ import __version__
from .prompt import is_interactive, choose_wheel
from .converter import Wheel2CondaConverter, CondaPackageFormat
from .pyproject import read_pyproject, PyProjInfo


class MarkdownHelpFormatter(argparse.RawTextHelpFormatter):
    """
    Format help in markdown format for use in docs
    """

    def __init__(self, prog: str):
        super().__init__(prog, max_help_position=12, width=80)

    def add_usage(self, usage, actions, groups, prefix=None):
        self.add_text(f"## {usage.split()[0]}")
        self.start_section("Usage")
        super().add_usage(usage, actions, groups, prefix)
        self.end_section()

    def start_section(self, heading):
        self._indent()
        section = self._Section(self, self._current_section, argparse.SUPPRESS)

        def add_heading() -> str:
            return f"### {heading}\n```text" if section.items else ''

        self._add_item(add_heading, [])
        self._add_item(section.format_help, [])
        self._current_section = section

    def end_section(self) -> None:
        show = bool(self._current_section.items)
        super().end_section()
        if show:
            self.add_text("```")


def dedent(text: str) -> str:
    """Deindent help string"""
    return textwrap.dedent(text).strip()


# pylint: disable=too-many-instance-attributes
@dataclass
class Whl2CondaArgs:
    """
    Parsed arguments
    """

    dep_renames: Sequence[Tuple[str, str]]
    dropped_deps: Sequence[str]
    dry_run: bool
    extra_deps: List[str]
    interactive: bool
    keep_pip_deps: bool
    markdown_help: bool
    name: str
    out_dir: Optional[Path]
    out_format: str
    overwrite: bool
    project_root: Optional[Path]
    python: str
    quiet: int
    test_env: Optional[str]
    test_channels: Sequence[str]
    test_install: bool
    test_prefix: Optional[Path]
    test_python: Optional[str]
    verbose: int
    wheel_dir: Optional[Path]
    wheel_or_root: Optional[Path]
    yes: bool


def _existing_path(val: str) -> Path:
    path = Path(val)
    if not path.exists():
        raise argparse.ArgumentTypeError(f"path '{val}' does not exist")
    return path


def _existing_dir(val: str) -> Path:
    path = _existing_path(val)
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f"'{val}' is not a directory")
    return path


def _create_argparser(prog: Optional[str] = None) -> argparse.ArgumentParser:
    """Creates the argument parser

    The parser will return a namespace with attributes matching
    Whl2CondaArgs
    """
    parser = argparse.ArgumentParser(
        usage="%(prog)s [<wheel-or-root>] [options]",
        prog=prog,
        description=dedent(
            """
            Generates a conda package from a pure python wheel
            """
        ),
        # formatter_class=MarkdownHelpFormatter,
        formatter_class=argparse.RawTextHelpFormatter,
        add_help=False,
    )

    input_opts = parser.add_argument_group("Input options")

    input_opts.add_argument(
        "wheel_or_root",
        nargs="?",
        metavar="<wheel-or-root>",
        type=_existing_path,
        help=dedent(
            """
        Either path to a wheel file to convert or a project root
        directory containing a pyproject.toml or setup.py file.
        """
        ),
    )

    input_opts.add_argument(
        "--project-root",
        "--root",
        dest="project_root",
        metavar="<dir>",
        type=_existing_dir,
        help=dedent(
            """
            Project root directory. This is a directory containing either a
            pyproject.toml or a (deprecated) setup.py file. This option may
            not be used if the project directory was given as the positional
            argument.
            
            If not specified, the project root will be located by searching
            the wheel directory and its parent directories, or if no wheel
            given, will default to the current directory.
        """
        ),
    )

    input_opts.add_argument(
        "-w",
        "--wheel-dir",
        metavar="<dir>",
        type=_existing_dir,
        help=dedent(
            """
            Location of wheel directory. Defaults to dist/ subdirectory of 
            project.
            """
        ),
    )

    output_opts = parser.add_argument_group("Output options")

    output_opts.add_argument(
        "--out-dir",
        "--out",
        dest="out_dir",
        metavar="<dir>",
        type=Path,
        help=dedent(
            """
            Output directory for conda package. Defaults to wheel directory
            or else project dist directory.
            """
        ),
    )

    output_opts.add_argument(
        "--overwrite",
        action="store_true",
        help=dedent(
            """
            Overwrite existing output files.
            """
        ),
    )

    output_opts.add_argument(
        "--format",
        "--out-format",
        choices=["V1", "tar.bz2", "V2", "conda", "tree"],
        dest="out_format",
        help="Output package format (%(default)s)",
    )

    override_opts = parser.add_argument_group("Override options")

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
        help=dedent(
            """
        Rename pip dependency for conda. May be specified muliple times.
        """
        ),
    )
    override_opts.add_argument(
        "-A",
        "--add-dependency",
        dest="extra_deps",
        metavar="<conda-dep>",
        action="append",
        default=[],
        help=dedent(
            """
            Add an additional conda dependency. May be specified multiple times.
            """
        ),
    )
    override_opts.add_argument(
        "-D",
        "--drop-dependency",
        metavar="<pip-name>",
        dest="dropped_deps",
        action="append",
        default=[],
        help=dedent(
            """
            Drop dependency with given name from conda dependency list.
            May be specified multiple times.
            """
        ),
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
        help="Set/override python dependency.",
    )

    test_opts = parser.add_argument_group("Test options")

    test_opts.add_argument(
        "--test-install",
        action="store_true",
        help="Test installation into a temporary environment",
    )
    test_opts.add_argument(
        "--test-channel",
        metavar="<channel>",
        action="append",
        dest="test_channels",
        default=[],
        help="Add an extra channel for use in test install.",
    )
    test_opts.add_argument(
        "--test-python",
        metavar="<version>",
        default="",
        help="Version of python to use for test install. (Default is current version).",
    )
    test_env_opts = test_opts.add_mutually_exclusive_group()
    test_env_opts.add_argument(
        "--test-env",
        metavar="<name>",
        help="Test environment name to create",
    )
    test_env_opts.add_argument(
        "--test-prefix",
        metavar="<prefix>",
        type=Path,
        help="Test environment prefix to create",
    )

    info_opts = parser.add_argument_group("Help and debug options")

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
    info_opts.add_argument(
        "--markdown-help",
        action="store_true",
        help=argparse.SUPPRESS,  # For internal use, do not show help
    )
    info_opts.add_argument("--version", action="version", version=__version__)

    # TODO --override-pyproject - ignore [tool.whl2conda] pyproject settings
    # TODO  --conda-bld - install in conda-bld and reindex (require tests first?)
    #
    # TODO - Debug options for keeping work?
    # TODO  - Way to run tests in test env?
    # TODO  - Do we need to remove package from conda-bld/pkgs cache
    #         if anything goes wrong with test?
    # TODO - add option to update/generate stdrenames.json file.

    return parser


def _parse_args(parser: argparse.ArgumentParser, args: Optional[Sequence[str]]) -> Whl2CondaArgs:
    """Parse and return arguments"""
    return Whl2CondaArgs(**vars(parser.parse_args(args)))


def _is_project_root(path: Path) -> bool:
    return any(path.joinpath(f).is_file() for f in ["pyproject.toml", "setup.py"])


# pylint: disable=too-many-statements,too-many-branches,too-many-locals
def main(args: Optional[Sequence[str]] = None, prog: Optional[str] = None):
    """
    Main command line interface
    """

    parser = _create_argparser(prog)
    parsed = _parse_args(parser, args)

    if parsed.markdown_help:
        parser.formatter_class = MarkdownHelpFormatter
        parser.print_help()
        sys.exit(0)

    interactive = parsed.interactive
    always_yes = parsed.yes

    dry_run = parsed.dry_run
    # dry_run implies at least verbosity of 1 unless turned off by quiet flag
    verbosity = max(parsed.verbose, int(dry_run)) - parsed.quiet

    project_root: Optional[Path] = None
    wheel_file: Optional[Path] = None
    wheel_dir: Optional[Path] = parsed.wheel_dir

    build_wheel = False  # TODO add option for this
    build_no_deps = False  # pylint: disable=unused-variable

    wheel_or_root = parsed.wheel_or_root
    if not wheel_or_root:
        project_root = Path.cwd()
    else:
        if wheel_or_root.is_dir():
            project_root = wheel_or_root
        else:
            wheel_file = wheel_or_root
            if wheel_file.suffix != ".whl":
                parser.error(f"Input file '{wheel_file} does not have .whl suffix")
            # Look for project root in wheel's parent directories
            if any((pr := p) for p in wheel_file.parents if _is_project_root(p)):
                project_root = pr

    if parsed.project_root:
        if project_root:
            parser.error("Cannot specify project root as both positional and keyword argument.")
        project_root = parsed.project_root

    pyproj_info = PyProjInfo.no_project()
    if project_root:
        try:
            pyproj_info = read_pyproject(project_root)
        except FileNotFoundError:
            pass

    if project_root:
        project_root = project_root.expanduser().absolute()
        if not _is_project_root(project_root):
            parser.error(f"No pyproject.toml or setup.py in project root '{project_root}'")
        if not wheel_dir:
            wheel_dir = pyproj_info.wheel_dir
            if not wheel_dir:
                # Use dist directory of project
                # TODO - check for build system specific alternate dist (#23)
                wheel_dir = project_root.joinpath("dist")

    can_build = project_root is not None

    if not wheel_file and wheel_dir and not build_wheel:
        # find wheel in directory
        try:
            wheel_file = choose_wheel(
                wheel_dir, interactive=interactive, choose_first=always_yes, can_build=can_build
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

    out_dir: Optional[Path] = None
    if parsed.out_dir:
        out_dir = parsed.out_dir.expanduser().absolute()
    else:
        out_dir = wheel_dir

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

    if parsed.test_install:
        try:
            subprocess.check_output(
                ["conda", "run", "-n", "base", "conda-index", "-h"], stderr=subprocess.STDOUT
            )
        except Exception:  # pylint: disable=broad-exception-caught
            parser.error(
                "--test-install requires that conda-index be installed in the base channel"
            )

    if not wheel_file:
        if build_wheel:
            assert project_root and wheel_dir
            wheel_file = do_build_wheel(
                project_root, wheel_dir, no_deps=build_no_deps, dry_run=dry_run
            )

    assert wheel_file

    converter = Wheel2CondaConverter(wheel_file, out_dir=out_dir)
    converter.dry_run = parsed.dry_run
    converter.package_name = parsed.name or pyproj_info.conda_name
    converter.out_format = out_fmt
    converter.overwrite = parsed.overwrite
    converter.keep_pip_dependencies = parsed.keep_pip_deps
    converter.extra_dependencies.extend(pyproj_info.extra_dependencies)
    converter.extra_dependencies.extend(parsed.extra_deps)
    converter.interactive = interactive
    converter.project_root = project_root

    converter.dependency_rename.extend(pyproj_info.dependency_rename)
    for dropname in parsed.dropped_deps:
        converter.dependency_rename.append((dropname, ""))
    converter.dependency_rename.extend(parsed.dep_renames)

    if verbosity < -1:
        level = logging.ERROR
    elif verbosity < 0:
        level = logging.WARNING
    elif verbosity == 0:
        level = logging.INFO
    elif verbosity == 1:
        level = logging.DEBUG
    elif verbosity >= 2:
        level = logging.DEBUG - 5

    logging.getLogger().setLevel(level)
    logging.basicConfig(level=level, format="%(message)s")

    conda_package = converter.convert()

    if conda_package.is_file() and not dry_run and parsed.test_install:
        converter.test_install(
            conda_package,
            channels=parsed.test_channels,
            python_version=parsed.test_python,
            env_name=parsed.test_env,
            env_prefix=parsed.test_prefix,
        )


def do_build_wheel(
    project_root: Path,
    wheel_dir: Path,
    *,
    no_deps: bool = False,
    dry_run: bool = False,
) -> Path:
    """Build wheel for project

    Arguments:
        project_root: directory containing pyproject.toml or setup.py
        wheel_dir: target output directory, created as needed
        no_deps: build with --no-deps --no-build-isolation
        dry_run: just log, don't actually run anything

    Returns:
        path to created wheel
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
        cmd.extend(["--no-deps", "--no-build-isolation"])
    logger.info("Running: %s", cmd)
    if dry_run:
        wheel = wheel_dir.joinpath("dry-run-1.0-py3-none-any.whl")
    else:
        start = time.time()
        # TODO capture/hide output in quiet mode
        subprocess.check_call(cmd)

        wheels = sorted(
            wheel_dir.glob("*.whl"),
            key=lambda p: p.stat().st_ctime,
            reverse=True,
        )

        assert wheels and wheels[0].stat().st_ctime >= start, f"No wheel created in '{wheel_dir}'"

        wheel = wheels[0]

    return wheel


if __name__ == "__main__":  # pragma: no cover
    main()
