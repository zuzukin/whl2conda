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
from typing import Optional, Sequence

from ..__about__ import __version__
from .build import build_main
from .common import dedent, Subcommands, MarkdownHelp

__all__ = ["main"]


def main(args: Optional[Sequence[str]] = None, prog: Optional[str] = None) -> None:
    """
    Main command line interface for whl2conda
    """
    parser = argparse.ArgumentParser(
        prog=prog,
        usage="%(prog)s [options] <command> ...",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=dedent(
            """
            Utility for building and testing conda package generated
            directly from a python wheel.
            
            See `%(prog)s build --help` for more information.
            """
        ),
    )

    subcmds = Subcommands(parser)
    subcmds.add_subcommand(
        "build", build_main, "builds a conda package from a python wheel"
    )

    parser.add_argument(
        "--markdown-help",
        action=MarkdownHelp,
        help=argparse.SUPPRESS,  # For internal use, do not show help
    )
    parser.add_argument("--version", action="version", version=__version__)

    parsed = parser.parse_args(args)

    subcmds.run(parsed)


if __name__ == "__main__":  # pragma: no cover
    main()
