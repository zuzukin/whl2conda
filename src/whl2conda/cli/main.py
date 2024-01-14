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
#
"""
Main whl2conda CLI
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from ..__about__ import __version__
from .common import dedent, Subcommands, add_markdown_help

__all__ = ["main"]


def main(args: Optional[Sequence[str]] = None, prog: Optional[str] = None) -> None:
    """
    Main command line interface for whl2conda
    """
    parser = argparse.ArgumentParser(
        prog=prog,
        usage="%(prog)s [options] <command> ...",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=dedent("""
            Utility for building and testing conda package generated
            directly from a python wheel.
            
            See `%(prog)s build --help` for more information.
            """),
    )

    subcmds = Subcommands(parser)
    subcmds.add_subcommand(
        "build",
        "whl2conda.cli.build.build_main",
        "conda-build replacement",
    )
    subcmds.add_subcommand(
        "config",
        "whl2conda.cli.config.config_main",
        "configure whl2conda",
    )
    subcmds.add_subcommand(
        "convert",
        "whl2conda.cli.convert.convert_main",
        "builds a conda package from a python wheel",
    )
    subcmds.add_subcommand(
        "diff",
        "whl2conda.cli.diff.diff_main",
        "compare contents of conda packages",
    )
    subcmds.add_subcommand(
        "install",
        "whl2conda.cli.install.install_main",
        "install conda package file with dependencies",
    )
    # TODO subcommand for clean/fixup of conda-bld or pkgs cache

    class ListSubcommands(argparse.Action):
        """Print out space separated list of command words and exit"""

        def __call__(self, *args, **kwargs):
            print(" ".join(subcmds.subcommands))
            sys.exit(0)

    parser.add_argument(
        "--list-subcommands", action=ListSubcommands, nargs=0, help=argparse.SUPPRESS
    )

    add_markdown_help(parser)
    parser.add_argument("--version", action="version", version=__version__)

    parsed = parser.parse_args(args)

    subcmds.run(parsed)


if __name__ == "__main__":  # pragma: no cover
    main()
