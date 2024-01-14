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
whl2conda config subcommand implementation
"""

from __future__ import annotations

import argparse
import sys
from http.client import HTTPException
from pathlib import Path
from typing import Optional, Sequence
from urllib.error import URLError

from ..api.stdrename import update_renames_file
from .common import add_markdown_help, dedent
from ..impl.pyproject import add_pyproject_defaults
from ..api.stdrename import user_stdrenames_path

__all__ = ["config_main"]


def config_main(
    args: Optional[Sequence[str]] = None,
    prog: Optional[str] = None,
) -> None:
    """Main routine for `whl2conda config` subcommand"""

    parser = argparse.ArgumentParser(
        description=dedent("""
            whl2conda configuration
            """),
        formatter_class=argparse.RawTextHelpFormatter,
        prog=prog,
    )

    parser.add_argument(
        "--generate-pyproject",
        metavar="<dir-or-toml>",
        nargs='?',
        const='out',
        help=dedent("""
            Add default whl2conda tool entries to a pyproject file. 
            If argument is a directory entries will be added to 
            `pyproject.toml` in that directory. If argument ends
            with suffix '.toml', that file will be updated. If
            the argument is omitted or set to `out` the generated entry 
            will be written to stdout. Other values will result in an error.
            This will create file if it does not already exist.
            It will not overwrite existing entires.
            """),
    )

    parser.add_argument(
        "--update-std-renames",
        nargs="?",
        metavar="<file>",
        const=user_stdrenames_path(),
        type=Path,
        help=dedent("""
            Update list of standard pypi to conda renames from internet and exit.
            If a <file> is not named, the default copy will be updated at
            %(const)s.
            """),
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Do not write any files.",
    )
    add_markdown_help(parser)

    parsed = parser.parse_args(args)

    if parsed.update_std_renames:
        update_std_renames(parsed.update_std_renames, dry_run=parsed.dry_run)

    if parsed.generate_pyproject:
        try:
            add_pyproject_defaults(parsed.generate_pyproject)
        except Exception as ex:  # pylint: disable=broad-exception-caught
            parser.error(str(ex))


def update_std_renames(renames_file: Path, *, dry_run: bool) -> None:
    """
    Update user cached copy of standard pypi to conda renames

    Exits program after update.

    Args:
        renames_file: file to update
        dry_run: don't write file if true
    """
    print(f"Updating {renames_file}")
    try:
        if update_renames_file(
            renames_file,
            dry_run=dry_run,
        ):
            if dry_run:
                print("Update available")
            else:
                print("Updated")
        else:
            print("No changes.")
    except (HTTPException, URLError) as ex:
        print(f"Cannot download update: {ex}", file=sys.stderr)
        sys.exit(8)
    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    config_main()
