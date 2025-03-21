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
`whl2conda install` CLI
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple, Optional, Sequence

from conda_package_handling.api import extract as extract_conda_pkg

from .common import dedent, existing_path, add_markdown_help, get_conda_bld_path
from ..external.version import ver_eval

__all__ = ["install_main"]


@dataclass
class InstallArgs:
    """Parsed arguments"""

    create: bool
    conda_bld: bool
    dry_run: bool
    use_mamba: bool
    name: str
    only_deps: bool
    no_deps: bool
    package_files: list[Path]
    prefix: Optional[Path]
    yes: bool
    remaining_args: list[str]

    @classmethod
    def parse(
        cls,
        parser: argparse.ArgumentParser,
        args: Optional[Sequence[str]],
    ):
        """Parses and returns parsed args"""
        ns = parser.parse_args(args)
        return cls(**vars(ns))


class InstallFileInfo(NamedTuple):
    """Holds information about a conda file to be installed"""

    path: Path
    name: str
    version: str


# pylint: disable=too-many-locals
def install_main(
    args: Optional[Sequence[str]] = None,
    prog: Optional[str] = None,
) -> None:
    """Main routine for `whl2conda config` subcommand"""

    parser = argparse.ArgumentParser(
        usage=dedent("""
            %(prog)s (-p <env-path> | -n <env-name>) <package-file>... [options]
                   %(prog)s --conda-bld <package-file> [options]
            """),
        description=dedent("""
            Install conda package files
            
            This can be used to install one or more conda package files
            (generated by `whl2conda build`) either into a
            conda environment (for testing) or into your
            local conda build directory.
            """),
        formatter_class=argparse.RawTextHelpFormatter,
        prog=prog,
        allow_abbrev=False,
    )

    parser.add_argument(
        "package_files",
        metavar="<package-file>",
        type=existing_path,
        nargs="+",
        help=dedent("""
            Conda package file to be installed
            Must have extension .conda or .tar.bz2
            """),
    )

    target_group = parser.add_argument_group(
        "Target (choose one)",
    )
    target_opts = target_group.add_mutually_exclusive_group(required=True)
    target_opts.add_argument(
        "-p",
        "--prefix",
        metavar="<env-path>",
        help="Path to target conda environment",
    )
    target_opts.add_argument(
        "-n", "--name", metavar="<env-name>", help="Name of target conda enviroment"
    )
    target_opts.add_argument(
        "--conda-bld", action="store_true", help="Install into local conda-bld"
    )

    env_options = parser.add_argument_group(
        "Environment options",
        description=dedent("""
            These options can be used with -n/-p when install into
            a conda environment. They are otherwise ignored.
            """),
    )

    env_options.add_argument(
        "--create", action="store_true", help="Create environment if it does not exist."
    )

    deps_options = env_options.add_mutually_exclusive_group()
    deps_options.add_argument(
        "--only-deps",
        action="store_true",
        help="Only install package dependencies, not the package itself.",
    )
    deps_options.add_argument(
        "--no-deps",
        action="store_true",
        help="Only packages themselves without any dependencies.",
    )

    env_options.add_argument(
        "--mamba",
        dest="use_mamba",
        action="store_true",
        help="Use mamba instead of conda for install actions",
    )

    env_options.add_argument(
        "--extra",
        dest="remaining_args",
        nargs=argparse.REMAINDER,
        default=[],
        help=dedent("""
            All the remaining arguments after this flat will be passed
            to `conda install` or `conda create`. This can be used to add
            additional dependencies for testing.
            """),
    )

    common_opts = parser.add_argument_group("Common options")

    common_opts.add_argument(
        "--dry-run",
        action="store_true",
        help="Display operations but don't actually install",
    )

    common_opts.add_argument(
        "--yes", action="store_true", help="Answer yes to prompts."
    )

    add_markdown_help(parser)

    parsed = InstallArgs.parse(parser, args)

    conda_files = parsed.package_files

    subdir = "noarch"
    dependencies: list[str] = []
    file_specs: list[InstallFileInfo] = []

    for conda_file in conda_files:
        conda_fname = str(conda_file.name)
        if not (conda_fname.endswith(".conda") or conda_fname.endswith(".tar.bz2")):
            parser.error(f"Package file has unsupported suffix: {conda_file}")

        with tempfile.TemporaryDirectory(prefix="whl2conda-install-") as tmpdir:
            try:
                # We don't need to do this for the conda-bld install, but it
                # provides an extra validity check on the file.
                tmp_path = Path(tmpdir)
                extract_conda_pkg(str(conda_file), dest_dir=tmp_path)
                index = json.loads(
                    tmp_path.joinpath("info", "index.json").read_text("utf")
                )
                subdir = index["subdir"]
                package_name = index["name"]
                package_version = index.get("version", "")
                file_specs.append(
                    InstallFileInfo(conda_file, package_name, package_version)
                )
                dependencies.extend(index.get("depends", []))
            except Exception as ex:  # pylint: disable=broad-exception-caught
                parser.error(f"Cannot extract conda package '{conda_file}:\n{ex}'")

    if parsed.conda_bld:
        # Install into conda-bld dir
        conda_bld_install(parsed, subdir)
    else:
        try:
            dependencies = _prune_dependencies(dependencies, file_specs)
        except Exception as ex:  # pylint: disable=broad-exception-caught
            parser.error(str(ex))
        conda_env_install(parsed, dependencies)


def conda_bld_install(parsed: InstallArgs, subdir: str):
    """Install package into conda-bld directory"""
    conda_bld_path = get_conda_bld_path()
    subdir_path = conda_bld_path.joinpath(subdir)  # e.g. noarch/

    for package_file in parsed.package_files:
        print(f"Installing {package_file} into {subdir_path}")
        if not parsed.dry_run:
            subdir_path.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(package_file, subdir_path.joinpath(package_file.name))
    if not parsed.dry_run:
        subprocess.check_call([
            "conda",
            "index",
            "--subdir",
            subdir,
            str(conda_bld_path),
        ])


def conda_env_install(parsed: InstallArgs, dependencies: list[str]):
    """Install package into an environment"""
    # pylint: disable=too-many-branches
    common_opts: list[str] = []
    env_opts: list[str] = []
    if parsed.prefix:
        env_opts.extend(["--prefix", str(parsed.prefix)])
    else:
        env_opts.extend(["--name", parsed.name])
    common_opts.extend(env_opts)

    if parsed.yes:
        common_opts.append("--yes")
    if parsed.dry_run:
        common_opts.append("--dry-run")

    conda = "mamba" if parsed.use_mamba else "conda"

    if not parsed.no_deps:
        install_deps_cmd = [conda]
        if parsed.create:
            install_deps_cmd.append("create")
        else:
            install_deps_cmd.append("install")
        install_deps_cmd.extend(common_opts)
        install_deps_cmd.extend(dependencies)
        install_deps_cmd.extend(parsed.remaining_args)

        subprocess.check_call(install_deps_cmd)

    if not parsed.only_deps:
        for package_file in parsed.package_files:
            install_pkg_cmd = [conda, "install"]
            install_pkg_cmd.extend(common_opts)
            install_pkg_cmd.append(str(package_file))

            if parsed.dry_run:
                # dry run of a package file install fails in conda
                print("Running ", install_pkg_cmd)
            else:
                subprocess.check_call(install_pkg_cmd)

        check_libmamba_cmd = "conda list -n base conda-libmamba-solver --json".split()
        if parsed.dry_run:
            print("running ", check_libmamba_cmd)
        else:
            jsonstr = subprocess.check_output(check_libmamba_cmd, encoding="utf-8")
            jobj = json.loads(jsonstr)
            version_str = jobj and jobj[0].get("version")
            version = tuple(int(s) for s in version_str.split("."))
            if version < (24, 1, 0):
                # Workaround for https://github.com/conda/conda/issues/13479
                # If a package is installed directly from file, then set solver to classic
                set_solver_cmd = (
                    ["conda", "run"]
                    + env_opts
                    + ["conda", "config", "--env", "--set", "solver", "classic"]
                )
                if parsed.dry_run:
                    print("Running ", set_solver_cmd)
                else:
                    subprocess.check_call(set_solver_cmd)


conda_depend_re = re.compile(r"\s*(?P<name>[\w\d.-]+)\s*(?P<version>.*)")


def _prune_dependencies(
    dependencies: list[str], file_specs: list[InstallFileInfo]
) -> list[str]:
    """
    Prunes dependencies list according to arguments

    - Does not attempt to merge package version specs
    - Removes duplicate specs
    - Removes references to packages in file_specs

    Arguments:
        dependencies: input list of conda dependency strings (package and optional version match specifier)
        file_specs: list of information on package files being installed

    Returns:
        List of pruned dependencies.

    Raises:
        ValueError if a dependency for a package file in file_specs does not match
    """

    exclude_packages: dict[str, InstallFileInfo] = {
        spec.name: spec for spec in file_specs
    }
    deps: set[str] = set()

    for dep in dependencies:
        if m := conda_depend_re.fullmatch(dep):  # pragma: no branch
            name = m.group("name")
            version = m.group("version")
            if version:
                version = version.replace(" ", "")  # remove spaces from version spec
            if exclude := exclude_packages.get(name):
                if not ver_eval(exclude.version, version):
                    raise ValueError(
                        f"{exclude.path} does not match dependency '{dep}'"
                    )
                continue
            dep = name
            if version:
                dep += f" {version}"
        deps.add(dep)

    return sorted(deps)
