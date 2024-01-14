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
whl2conda diff subcommand implementation
"""

from __future__ import annotations

# standard
import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Sequence

# third party
import conda_package_handling.api as cphapi

# this project
from .common import add_markdown_help, dedent, existing_path

__all__ = ["diff_main"]


def existing_conda_package(val: str) -> Path:
    """
    Assert string refers to an existing conda package file
    """
    path = existing_path(val)
    if not (path.name.endswith(".conda") or path.name.endswith(".tar.bz2")):
        raise argparse.ArgumentTypeError(f"'{val}' is not a conda package")
    return path


def diff_main(
    args: Optional[Sequence[str]] = None,
    prog: Optional[str] = None,
) -> None:
    """Main routine for `whl2conda diff` subcommand"""

    parser = argparse.ArgumentParser(
        description=dedent("""
            Compare the content of two conda packages
            
            This will unpack each conda packaeg into temporary
            directories, normalize the layout of files in the 
            input directory to minimize line differences, and
            will run the specified diff tool and arguments.
            
            This can be used to compare packages generated using
            this tool against those created using conda-build.            
            """),
        formatter_class=argparse.RawTextHelpFormatter,
        prog=prog,
    )

    parser.add_argument(
        "package1",
        metavar="<package1>",
        type=existing_conda_package,
        help="First package to compare",
    )

    parser.add_argument(
        "package2",
        metavar="<package2>",
        type=existing_conda_package,
        help="Second package to compare",
    )

    parser.add_argument(
        "-T",
        "--diff-tool",
        metavar="<tool>",
        required=True,
        help=dedent("""
            Diff tool to use. This is currently required.
            
            The tool is expected to take positional arguments
            for each directory. Additional arguments may be
            passed after --args.
            """),
    )

    parser.add_argument(
        "-A",
        "--args",
        nargs=argparse.REMAINDER,
        default=[],
        help="All remaining arguments passed to diff tool",
    )

    add_markdown_help(parser)

    parsed = parser.parse_args(args)

    diff_tool = parsed.diff_tool
    diff_args = list(parsed.args)

    with tempfile.TemporaryDirectory(
        dir=os.getcwd(), prefix="whl2conda-diff-"
    ) as tmp_dir_name:
        tmpdir = Path(tmp_dir_name)

        # if directory doesn't get deleted, make
        # sure it does not get checked in
        gitignore = tmpdir / ".gitignore"
        gitignore.write_text("*\n")

        pkg1_dir = tmpdir / "pkg1"
        pkg2_dir = tmpdir / "pkg2"

        _extract_packge(parsed.package1, pkg1_dir)
        _extract_packge(parsed.package2, pkg2_dir)

        subprocess.run(
            [diff_tool, str(pkg1_dir), str(pkg2_dir)] + diff_args, check=False
        )


def _extract_packge(package: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    cphapi.extract(str(package), dest_dir)

    # normalize contents
    info_dir = dest_dir / "info"
    _normalize_json(info_dir / "about.json")
    _normalize_json(info_dir / "link.json")
    _normalize_index(info_dir / "index.json")
    _normalize_paths(info_dir / "paths.json")
    _sort_lines(info_dir / "files")

    # find RECORD in site-packages/*.distinfo
    site_packages = dest_dir / "site-packages"
    dest_info = next(site_packages.glob("*.dist-info"))
    assert dest_info.is_dir()
    # TODO strip __pycache__ entries from RECORD
    _sort_lines(dest_info / "RECORD")

    # remove __pycache__ dirs?


def _normalize_json(file: Path) -> None:
    jobj = json.loads(file.read_text("utf8"))
    file.write_text(json.dumps(jobj, indent=2, sort_keys=True))


def _normalize_index(file: Path) -> None:
    jobj = json.loads(file.read_text("utf8"))
    jobj["depends"] = sorted(jobj["depends"])
    file.write_text(json.dumps(jobj, indent=2, sort_keys=True))


def _normalize_paths(file: Path) -> None:
    jobj = json.loads(file.read_text("utf8"))
    paths = jobj["paths"]
    jobj["paths"] = sorted(paths, key=lambda entry: entry["_path"])
    file.write_text(json.dumps(jobj, indent=2, sort_keys=True))


# def normalize_email_msg(file: Path) -> None:
#     email.message_from_string(file.read_text("utf8"))


def _sort_lines(file: Path) -> None:
    with open(file) as f:
        lines = f.readlines()
    with open(file, "w") as f:
        f.writelines(sorted(lines))
