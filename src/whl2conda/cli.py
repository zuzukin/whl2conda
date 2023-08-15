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
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from .__about__ import __version__
from .converter import Wheel2CondaConverter, CondaPackageFormat

class MarkdownHelpFormatter(argparse.RawTextHelpFormatter):
    def __init__(self, prog:str):
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
            if section.items:
                return f"### {heading}\n```text"
            else:
                return ''
        self._add_item(add_heading, [])
        self._add_item(section.format_help, [])
        self._current_section = section

    def end_section(self) -> None:
        show = bool(self._current_section.items)
        super().end_section()
        if show:
            self.add_text("```")

def dedent(text: str) -> str:
    return textwrap.dedent(text).strip()

# pylint: disable=too-many-statements,too-many-branches,too-many-locals
def main():
    """
    Main command line interface
    """
    prog = os.path.basename(sys.argv[0])
    parser = argparse.ArgumentParser(
        usage=f"{prog} [<wheel>] [options]",
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

    input_opts.add_argument("wheel", nargs="?", metavar="<wheel>", help="Wheel file to convert")

    input_opts.add_argument(
        "--project-root",
        "--root",
        metavar="<dir>",
        default=os.getcwd(),
        help="Project root directory, if applicable. Default is current directory.",
    )

    output_opts = parser.add_argument_group("Output options")

    output_opts.add_argument(
        "--out-dir",
        "--out",
        metavar="<dir>",
        help=dedent(
            """
        Output directory for conda package. Defaults to wheel directory.
        """
        ),
    )
    # TODO support generation in conda-bld/noarch (including index update)

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
        default="tar.bz2",
        help="Output package format (%(default)s)",
    )

    override_opts = parser.add_argument_group("Override options")

    override_opts.add_argument("--name", metavar="<package-name>", help="Override package name")
    override_opts.add_argument(
        "-R",
        "--dependency-rename",
        nargs=2,
        metavar=("<pip-name>", "<conda-name>"),
        action="append",
        default=[],
        help=dedent(
            """
        Rename pip dependency for conda. May be specified muliple times.
        """
        ),
    )
    override_opts.add_argument(
        "-A",
        "--add-dependency",
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
        action="store_true",
        help="Retain pip dependencies in python dist_info of conda package.",
    )
    override_opts.add_argument(
        "--python", metavar="<version-spec>", help="Set/override python dependency."
    )

    test_opts = parser.add_argument_group("Test options")

    test_opts.add_argument(
        "--test-install",
        metavar="<python-version>",
        help="Test installation into a temporary environment",
    )
    test_opts.add_argument(
        "--test-channel",
        metavar="<channel>",
        action="append",
        default=[],
        help="Add an extra channel for use in test install.",
    )

    info_opts = parser.add_argument_group("Help and debug options")

    info_opts.add_argument("-n", "--dry-run", action="store_true", help="Do not write any files.")
    info_opts.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity.")
    info_opts.add_argument("-q", "--quiet", action="count", default=0, help="Less verbose output")

    info_opts.add_argument("-h", "-?", "--help", action="help", help="Show usage and exit.")
    info_opts.add_argument(
        "--markdown-help", action="store_true",
        help = argparse.SUPPRESS # "Show help in markdown format"
    )
    info_opts.add_argument("--version", action="version", version=__version__)

    parsed = parser.parse_args()

    #
    # Process args
    #

    if parsed.markdown_help:
        parser.formatter_class = MarkdownHelpFormatter
        parser.print_help()
        sys.exit(0)

    wheel = parsed.wheel
    if not wheel:
        parser.error("Cannot locate wheel.")

    wheel_file = Path(wheel).expanduser().absolute()
    if not wheel_file.exists():
        parser.error(f"Input wheel '{wheel_file}' does not exist")
    if wheel_file.suffix != ".whl":
        parser.error(f"Input file '{wheel_file} does not have .whl suffix")

    project_root = Path(parsed.project_root).expanduser().absolute()
    if not project_root.is_dir():
        parser.error(f"Project root '{project_root}' does not exist.")

    if parsed.out_dir:
        out_dir = Path(parsed.out_dir).expanduser().absolute()
    else:
        out_dir = wheel_file.parent
    if not out_dir.is_dir():
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
    # TODO - build missing wheel using pyproject.toml

    converter = Wheel2CondaConverter(wheel_file, out_dir=out_dir)
    converter.dry_run = parsed.dry_run
    converter.package_name = parsed.name
    converter.out_format = out_fmt
    converter.overwrite = parsed.overwrite
    converter.keep_pip_dependencies = parsed.keep_pip_dependencies
    converter.extra_dependencies = parsed.add_dependency

    for dropname in parsed.drop_dependency:
        converter.dependency_rename[dropname] = ""
    for pipname, replacement in parsed.dependency_rename:
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

    if conda_package.is_file() and not dry_run and parsed.test_install is not None:
        # TODO - move to a function in separate module or in converter
        print(f"Test installing package in python {parsed.test_install} environment")
        with tempfile.TemporaryDirectory(prefix="whl2conda-test-install-") as tmpdir:
            tmppath = Path(tmpdir)
            # make a local test channel and index it
            test_channel = tmppath.joinpath("channel")
            test_channel_noarch = test_channel.joinpath("noarch")
            test_channel_noarch.mkdir(parents=True)
            shutil.copyfile(conda_package, test_channel_noarch.joinpath(conda_package.name))
            subprocess.check_call(["conda", "run", "-n", "base", "conda-index", str(test_channel)])
            # create a test prefix
            test_prefix = tmppath.joinpath("prefix")
            create_cmd = ["conda", "create", "-p", str(test_prefix), "--yes"]
            # create_cmd.append("--verbose")
            create_cmd.extend(["-c", f"file:/{test_channel}"])
            for channel in parsed.test_channel:
                create_cmd.extend(["-c", channel])
            create_cmd.append(f"python={parsed.test_install}")
            create_cmd.append(converter.package_name)
            subprocess.check_call(create_cmd)


if __name__ == "__main__":  # pragma: no cover
    main()
