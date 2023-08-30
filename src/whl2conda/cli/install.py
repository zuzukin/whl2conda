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
`whl2conda install` CLI
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Sequence

from conda_package_handling.api import extract as extract_conda_pkg

from .common import dedent, existing_path, add_markdown_help

__all__ = ["install_main"]


# pylint: disable=too-many-locals
def install_main(
    args: Optional[Sequence[str]] = None,
    prog: Optional[str] = None,
) -> None:
    """Main routine for `whl2conda config` subcommand"""

    parser = argparse.ArgumentParser(
        description=dedent(
            """
            Install a conda package file with dependencies.
            
            This can be used to install a package file generated
            by `whl2conda build` into an environment for testing.
            """
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        prog=prog,
    )

    parser.add_argument(
        "package_file",
        metavar="<package-file>",
        type=existing_path,
        help="Conda package file with extension .conda or .tar.bz2",
    )

    env_group = parser.add_argument_group(
        "Environment options",
    )
    env_opts = env_group.add_mutually_exclusive_group(required=True)
    env_opts.add_argument(
        "-p",
        "--prefix",
        metavar="<env-path>",
        help="Path to target conda environment",
    )
    env_opts.add_argument(
        "-n", "--name", metavar="<env-name>", help="Name of target conda enviroment"
    )
    # TODO: install in conda-bld and reindex (#10)
    # env_opts.add_argument(
    #     "--conda-bld",
    #     action="store_true",
    #     help="Install into local conda-bld"
    # )

    parser.add_argument(
        "-c",
        "--channel",
        dest="channels",
        action="append",
        default=[],
        help="Add a channel to use for install",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Display operations but don't actually install",
    )

    add_markdown_help(parser)

    parsed = parser.parse_args(args)

    dry_run = bool(parsed.dry_run)
    conda_file: Path = parsed.package_file

    conda_fname = str(conda_file.name)
    if not (conda_fname.endswith(".conda") or conda_fname.endswith(".tar.bz2")):
        parser.error(f"Package file has unsupported suffix: {conda_file}")

    with tempfile.TemporaryDirectory(prefix="whl2conda-install-") as tmpdir:
        tmp_path = Path(tmpdir)
        # extracted_dir = tmp_path.joinpath("extracted")
        extract_conda_pkg(str(conda_file), dest_dir=tmp_path)
        index = json.loads(tmp_path.joinpath("info", "index.json").read_text("utf"))
        dependencies = index.get("depends", [])

    if parsed.prefix:
        env_args = ["--prefix", parsed.prefix]
    elif parsed.name:
        env_args = ["--name", parsed.name]
    else:
        # If conda-bld, instead copy into conda-bld directory and reindex
        raise NotImplementedError

    # TODO add --create option
    # TODO option to install extra packages, or just pass through to install?

    # Add --yes automatically or add an option?
    conda_install_opts = ["conda", "install", "--yes"] + env_args
    for channel in parsed.channels:
        conda_install_opts.extend(["-c", channel])
    if dry_run:
        conda_install_opts += ["--dry-run"]
    subprocess.check_call(conda_install_opts + dependencies)
    subprocess.check_call(conda_install_opts + [str(conda_file)])
