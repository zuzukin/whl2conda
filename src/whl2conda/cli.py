#  Copyright 2023 Christopher Barber
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
whl2conda command line interface
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

from .__about__ import __version__
from .converter import Wheel2CondaConverter, CondaPackageFormat


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


@dataclass
class Whl2CondaArgs:
    """
    Parsed arguments
    """

    dep_renames: Sequence[Tuple[str, str]] = ()
    dropped_deps: Sequence[str] = ()
    dry_run: bool = False
    extra_deps: Sequence[str] = ()
    keep_pip_deps: bool = False
    markdown_help: bool = False
    name: str = ""
    out_dir: Optional[str] = None
    out_format: str = "conda"
    overwrite: bool = False
    project_root: Optional[str] = None
    quiet: int = 0
    test_env: Optional[str] = None
    test_channels: Sequence[str] = ()
    test_install: bool = False
    test_prefix: Optional[str] = None
    test_python: str = ""
    verbose: int = 0
    wheel_or_root: Optional[str] = None


def _create_argparser() -> argparse.ArgumentParser:
    prog = os.path.basename(sys.argv[0])
    parser = argparse.ArgumentParser(
        usage=f"{prog} [<wheel-or-root>] [options]",
        description=dedent(
            """
            Generates a conda package from a pure python wheel
            """
        ),
        # formatter_class=MarkdownHelpFormatter,
        formatter_class=argparse.RawTextHelpFormatter,
        add_help=False,
    )
    # parser._action_groups = []

    input_opts = parser.add_argument_group("Input options")

    input_opts.add_argument(
        "wheel_or_root",
        nargs="?",
        metavar="<wheel-or-root>",
        help=dedent(
            """
        Either path to a wheel file to convert or a project root
        directory containing a pyproject.toml or setup.py file.
        """
        ),
    )
    # TODO instead take either wheel or project root

    input_opts.add_argument(
        "--project-root",
        "--root",
        dest="project_root",
        metavar="<dir>",
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
    # TODO search for pyproject.toml/setup.py starting from wheel directory

    output_opts = parser.add_argument_group("Output options")

    output_opts.add_argument(
        "--out-dir",
        "--out",
        dest="out_dir",
        metavar="<dir>",
        help=dedent(
            """
            Output directory for conda package. Defaults to wheel directory
            or else project dist directory.
            """
        ),
    )
    # TODO support generation in conda-bld/noarch (including index update)

    # TODO check for interactive terminal using sys.__stdin__.isatty()
    #  if interactive allow prompts for
    #   - choosing wheel if multiple wheels in input dist dir
    #   - whether to overwrite existing files
    #   - whether to build missing wheel
    #
    # TODO add --yes option

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
        default="conda",
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
        "--python", metavar="<version-spec>", help="Set/override python dependency."
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

    # TODO
    #   -w --wheel-dir - generate wheel in specified dir (cannot specify `wheel` arg) and keep
    #   --override-pyproject - ignore [tool.whl2conda] pyproject settings
    #   --conda-bld - install in conda-bld and reindex (require tests first?)
    #
    #  - Debug options for keeping work?
    #  - Way to run tests in test env?
    #  - Do we need to remove package from conda-bld/pkgs cache if anything goes wrong with test?

    return parser


def _parse_args(parser: argparse.ArgumentParser) -> Whl2CondaArgs:
    return Whl2CondaArgs(**vars(parser.parse_args()))


def _is_project_root(path: Path) -> bool:
    return any(path.joinpath(f).is_file() for f in ["pyproject.toml", "setup.py"])


# pylint: disable=too-many-statements,too-many-branches,too-many-locals
def main():
    """
    Main command line interface
    """

    parser = _create_argparser()
    parsed = _parse_args(parser)

    _interactive = sys.__stdin__.isatty()

    project_root: Optional[Path] = Path.cwd()
    wheel_file: Optional[Path] = None

    wheel_or_root = parsed.wheel_or_root
    if not wheel_or_root:
        project_root = Path.cwd()
    else:
        wheel_or_root_path = Path(wheel_or_root)
        if not wheel_or_root_path.exists():
            parser.error(f"Input path `{wheel_or_root_path}` does not exist")
        if wheel_or_root_path.is_dir():
            project_root = wheel_or_root_path
        else:
            wheel_file = wheel_or_root_path
            if wheel_file.suffix != ".whl":
                parser.error(f"Input file '{wheel_file} does not have .whl suffix")
            # Look for project root in wheel's parent directories
            if any((pr := p) for p in wheel_file.parents if _is_project_root(p)):
                project_root = pr

    if parsed.project_root:
        if project_root:
            parser.error("Cannot specify project root as both positional and keyword argument.")
        project_root = Path(parsed.project_root)

    if project_root:
        project_root = project_root.expanduser().absolute()
        if not _is_project_root(project_root):
            parser.error(f"No pyproject.toml or setup.py in project root '{project_root}'")

    if not wheel_file:
        pass

    if parsed.markdown_help:
        parser.formatter_class = MarkdownHelpFormatter
        parser.print_help()
        sys.exit(0)

    out_dir: Optional[Path] = None
    if parsed.out_dir:
        out_dir = Path(parsed.out_dir).expanduser().absolute()
        if out_dir.is_dir():
            parser.error(f"Output directory '{out_dir}' does not exist.")

    fmtname = parsed.out_format.lower()
    if fmtname in ("v1", "tar.bz2"):
        out_fmt = CondaPackageFormat.V1
    elif fmtname in ("v2", "conda"):
        out_fmt = CondaPackageFormat.V2
    else:
        out_fmt = CondaPackageFormat.TREE

    dry_run = bool(parsed.dry_run)
    verbosity = int(parsed.verbose)
    verbosity = max(verbosity, int(dry_run))
    verbosity -= int(parsed.quiet)

    if parsed.test_install:
        try:
            subprocess.check_output(
                ["conda", "run", "-n", "base", "conda-index", "-h"], stderr=subprocess.STDOUT
            )
        except Exception:  # pylint: disable=broad-exception-caught
            parser.error(
                "--test-install requires that conda-index be installed in the base channel"
            )

    # TODO - get options from pyproject.toml file
    converter = Wheel2CondaConverter(wheel_file, out_dir=out_dir)
    converter.dry_run = parsed.dry_run
    converter.package_name = parsed.name
    converter.out_format = out_fmt
    converter.overwrite = parsed.overwrite
    converter.keep_pip_dependencies = parsed.keep_pip_deps
    converter.extra_dependencies = list(parsed.extra_deps)

    for dropname in parsed.dropped_deps:
        converter.dependency_rename[dropname] = ""
    for pipname, replacement in parsed.dep_renames:
        converter.dependency_rename[pipname] = replacement

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


if __name__ == "__main__":  # pragma: no cover
    main()
