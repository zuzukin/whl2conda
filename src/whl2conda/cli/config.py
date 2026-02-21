#  Copyright 2023-2024 Christopher Barber
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
import json
import sys
from http.client import HTTPException
from pathlib import Path
from typing import Optional, Sequence
from urllib.error import URLError

from ..api.stdrename import update_renames_file
from .common import add_markdown_help, dedent
from ..impl.pyproject import add_pyproject_defaults
from ..api.stdrename import user_stdrenames_path
from ..settings import settings, _fromidentifier

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

    settings_opts = parser.add_argument_group(
        "User settings options",
        description=dedent(
            """
            These options allow you to view or modify persistent user settings
            that affect the behavior of whl2conda. Note that all of these options
            treat key dash and underscore in key names as equivalent (e.g. you
            may use either `conda-format` or `conda_format`).
            """
        ),
    )

    # TODO - add a --describe option

    settings_opts.add_argument(
        "--set",
        metavar=("<key>", "<value>"),
        nargs=2,
        help=dedent("""
            Sets configuration parameter specified by <key> to given <value>.
            For dictionary attributes (e.g. pypi-indexes), the <key> should be
            of the form `<key>.<entry>` to set a specific entry in the table, e.g.
            
               whl2conda config --set pypi-indexes.acme https://acme.com/pypi
               
            Note that it is not currently possible to assign to entire dictionary.
        """),
    )
    settings_opts.add_argument(
        "--remove",
        metavar="<key>",
        help=dedent(
            """
            Unset user setting with given key. To remove an entry from a dictionary
            use a key for the form '<key>.<entry>', e.g.
            
              whl2conda config --remove pypi-indexes.acme
            """
        ),
    )

    show_opts = settings_opts.add_mutually_exclusive_group()
    show_opts.add_argument(
        "--show",
        metavar="<key>",
        nargs="*",
        help=dedent("""
            Show user settings from local settings file. If any <key> is given,
            then only the specified settings will be displayed, otherwise
            all settings will be shown.
            """),
    )

    show_opts.add_argument(
        "--show-sources",
        action="store_true",
        help=dedent("""
            The same as --show with no arguments but also displays location
            of settings file.
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

    if parsed.remove:
        remove_user_setting(parsed.remove, dry_run=parsed.dry_run)

    if parsed.set:
        set_user_setting(*parsed.set, dry_run=parsed.dry_run)

    if parsed.show is not None:
        show_user_settings(parsed.show)
    elif parsed.show_sources:
        show_user_settings(show_sources=True)


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


def save_settings(*, dry_run) -> None:
    if dry_run:
        print(f"Dry run: not saving {settings.settings_file}")
    else:
        settings.save()


def set_user_setting(key: str, value: str, *, dry_run: bool = False) -> None:
    settings.set(key, value)
    save_settings(dry_run=dry_run)


def show_user_settings(
    keys: Sequence[str] = (),
    show_sources: bool = False,
) -> None:
    if show_sources:
        print(f"==> {settings.settings_file} <==")
    if keys:
        for key in keys:
            print(f"{_fromidentifier(key)}: {json.dumps(settings.get(key))}")
    else:
        print(json.dumps(settings.to_dict(), indent=2))


def remove_user_setting(key: str, *, dry_run: bool = False) -> None:
    settings.unset(key)
    save_settings(dry_run=dry_run)


if __name__ == "__main__":  # pragma: no cover
    config_main()
