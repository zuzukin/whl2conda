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
Converter API
"""
# See https://docs.conda.io/projects/conda-build/en/stable/resources/package-spec.html

from __future__ import annotations

# standard
import email
import enum
import iniconfig
import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import time
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

# third party
from wheel.wheelfile import WheelFile
from conda_package_handling.api import create as create_conda_pkg

__all__ = [
    "CondaPackageFormat",
    "Wheel2CondaConverter",
    "Wheel2CondaError"
]

from .__about__ import __version__
from .prompt import bool_input

class Wheel2CondaError(RuntimeError):
    """Errors from Wheel2CondaConverter"""

class CondaPackageFormat(enum.Enum):
    """
    Supported output package formats

    * V1: original conda format as .tar.bz2 file
    * V2: newer .conda format
    * TREE: dumps package out as a directory tree (for debugging)
    """

    V1 = ".tar.bz2"
    V2 = ".conda"
    TREE = ".tree"

class NonNoneDict(dict):
    def __setitem__(self, key: str, val: Any) -> None:
        if val is None:
            if key in self:
                del self[key]
        else:
            super().__setitem__(key, val)

class Wheel2CondaConverter:
    """
    Converter supports generation of conda package from a pure python wheel.

    """

    package_name: str = ""
    logger: logging.Logger
    wheel_path: Optional[Path]
    out_dir: Path
    dry_run: bool = False
    wheel: Optional[WheelFile]
    out_format: CondaPackageFormat
    overwrite: bool = False
    keep_pip_dependencies: bool = False
    dependency_rename: List[Tuple[str, str]]
    extra_dependencies: List[str]
    project_root: Path
    interactive: bool = False

    temp_dir: Optional[tempfile.TemporaryDirectory] = None

    def __init__(
        self,
        wheel_path: Optional[Path] = None,
        *,
        out_dir: Optional[Path] = None,
    ):
        self.logger = logging.getLogger(__name__)
        self.wheel_path = wheel_path
        if out_dir:
            self.out_dir = out_dir
        elif wheel_path:
            self.out_dir = wheel_path.parent
        else:
            self.out_dir = Path.cwd()
        self.dependency_rename = []
        self.extra_dependencies = []
        self.project_root = Path.cwd()

    def __enter__(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="whl2conda-")

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.temp_dir:
            self.temp_dir.cleanup()

    def convert(self) -> Path:
        """
        Convert wheel to conda package

        Does not write any non-temporary files if dry_run is True.

        Returns:
            Path of conda package
        """
        # TODO - split up into smaller methods
        # pylint: disable=too-many-statements,too-many-branches,too-many-locals

        with self:
            assert self.temp_dir is not None
            tmp_path = Path(self.temp_dir.name)

            #
            # Build the wheel if needed
            #

            # TODO add explicit option to enable/request building wheel
            if self.wheel_path is None:
                self.logger.info("Building wheel for %s", self.project_root)
                wheel_dist_dir = tmp_path.joinpath("dist")
                subprocess.check_call(
                    [
                        "pip",
                        "wheel",
                        str(self.project_root),
                        "-w",
                        str(wheel_dist_dir),
                        "--no-deps",
                        "--no-build-isolation",
                    ]
                )
                self.wheel_path = next(wheel_dist_dir.glob("*.whl"))

            #
            # Extract the wheel
            #

            self.logger.info("Reading %s", self.wheel_path)
            wheel = WheelFile(self.wheel_path)
            wheel_dir = Path(self.temp_dir.name).joinpath("wheel-files")
            wheel.extractall(wheel_dir)

            if self.logger.getEffectiveLevel() <= logging.DEBUG:
                for wheel_file in wheel_dir.glob("**/*"):
                    if wheel_file.is_file():
                        self._debug("Extracted %s", wheel_file.relative_to(wheel_dir))

            #
            # Parse the metadata
            #

            wheel_info_dir = next(wheel_dir.glob("*.dist-info"))

            WHEEL_file = wheel_info_dir.joinpath("WHEEL")
            WHEEL_msg = email.message_from_string(WHEEL_file.read_text("utf8"))
            # https://peps.python.org/pep-0427/#what-s-the-deal-with-purelib-vs-platlib
            is_pure_lib = WHEEL_msg.get("Root-Is-Purelib","").lower() == "true"
            wheel_build_number = WHEEL_msg.get("Build", "")
            wheel_version = WHEEL_msg.get("Wheel-Version")

            if wheel_version != "1.0":
                raise Wheel2CondaError(f"Wheel {self.wheel_path} has unsupported wheel version {wheel_version}")

            if not is_pure_lib:
                raise Wheel2CondaError(f"Wheel {self.wheel_path} is not pure python")

            wheel_md_file = wheel_info_dir.joinpath("METADATA")
            md: Dict[str, List[Any]] = {}

            # TODO: clean up metadata parsing code to only use lists for classifiers and requirements
            md_msg = email.message_from_string(wheel_md_file.read_text())
            for mdkey, mdval in md_msg.items():
                mdkey = mdkey.lower().strip()
                mdval = mdval.strip()
                md.setdefault(mdkey, []).append(mdval)
                if mdkey == "requires-dist":
                    continue

            if not self.keep_pip_dependencies:
                requires = md_msg.get_all("Requires-Dist",())
                del md_msg["Requires-Dist"]
                # Turn requirements into optional extra requirements
                for require in requires:
                    md_msg.add_header("Requires-Dist", f"{require}: extra == 'pypi")
                wheel_md_file.write_text(md_msg.as_string())

            package_name = self.package_name or str(md.get("name", [])[0]).strip()
            self.package_name = package_name
            version = md.get("version", [""])[0].strip()

            dependencies: List[str] = []
            python_version = md.get("requires-python", [""])[0]
            if python_version:
                dependencies.append(f"python {python_version}")
            dependencies.extend(md.get("requires-dist", []))

            #
            # Copy site-packages files
            #

            conda_dir = Path(self.temp_dir.name).joinpath("conda-files")
            conda_dir.mkdir()
            conda_site_packages = conda_dir.joinpath("site-packages")
            conda_site_packages.mkdir()
            conda_info_dir = conda_dir.joinpath("info")
            conda_info_dir.mkdir()

            shutil.copytree(wheel_dir, conda_site_packages, dirs_exist_ok=True)

            rel_files = list(
                str(f.relative_to(conda_dir))
                for f in conda_site_packages.glob("**/*")
                if f.is_file()
            )

            #
            # Modify dependencies
            #

            conda_dependencies: List[str] = []
            for dep in dependencies:
                m = re.fullmatch(r"([a-zA-Z0-9_.-]+)\b\s*\(?(.*?)\)?", dep.strip())
                conda_name = ""
                conda_ver = ""
                pip_name = ""
                if m is None:
                    # Should this be an error? What should we do?
                    # How does user work around if this happens?
                    self._warn("Cannot parse dependency '%s'", dep)
                else:
                    conda_name = pip_name = m.group(1)
                    conda_ver = m.group(2)
                    for oldmatch, replacement in self.dependency_rename:
                        if m := re.fullmatch(oldmatch, pip_name):
                            conda_name = m.expand(replacement)
                            break

                if conda_name:
                    conda_dep = f"{conda_name} {conda_ver}"
                    if conda_name == pip_name:
                        self._debug("Dependency copied: '%s'", conda_dep)
                    else:
                        self._debug("Dependency renamed: '%s' -> '%s'", dep, conda_dep)
                    conda_dependencies.append(conda_dep)
                else:
                    self._debug("Dependency dropped: %s", dep)

            for dep in self.extra_dependencies:
                self._debug("Dependency added:  '%s'", dep)

            # TODO: copy licenses
            # * info/licenses - dir containing license files
            license = md.get("license-expression", [None])[0] or md.get("license", [None])[0]

            # * info/about.json
            conda_about_file = conda_info_dir.joinpath("about.json")
            conda_about_file.write_text(
                json.dumps(
                    NonNoneDict(
                        # TODO only include if defined
                        description=md.get("description", [""])[0],
                        license=license or None,
                        classifiers=md.get("classifier"),
                        keywords=md.get("keyword"),
                        whl2conda_version=__version__,
                        # TODO:
                        # home
                        # dev_url
                        # doc_url
                        # license_url
                        # summary - get from body of METADATA
                        # authors, maintainers
                    ),
                    indent=2,
                )
            )

            conda_hash_input_file = conda_info_dir.joinpath("hash_input.json")
            conda_hash_input_file.write_text(json.dumps({}, indent=2))

            # * info/files - list of relative paths of files not including info/
            conda_files_file = conda_info_dir.joinpath("files")
            with open(conda_files_file, "w") as f:
                for rel_file in rel_files:
                    f.write(rel_file)
                    f.write("\n")

            # info/index.json
            conda_index_file = conda_info_dir.joinpath("index.json")
            conda_index_file.write_text(
                json.dumps(
                    dict(
                        arch=None,
                        build="py_0",
                        # TODO convert build number from WHEEL file
                        build_number=0,
                        depends=conda_dependencies,
                        license=license,
                        name=package_name,
                        noarch="python",
                        platform=None,
                        subdir="noarch",
                        timestamp=int(time.time() + time.timezone),
                        version=version,
                    ),
                    indent=2,
                )
            )

            # info/link.json
            conda_link_file = conda_info_dir.joinpath("link.json")
            wheel_entry_points_file = wheel_info_dir.joinpath("entry_points.txt")
            console_scripts: List[str] = []
            if wheel_entry_points_file.is_file():
                wheel_entry_points = iniconfig.IniConfig(wheel_entry_points_file)
                for section_name in ["console_scripts", "gui_scripts"]:
                    if section_name in wheel_entry_points:
                        if section := wheel_entry_points[section_name]:
                            console_scripts.extend(f"{k}={v}" for k, v in section.items())

            # TODO - check correct setting for gui scripts
            conda_link_file.write_text(
                json.dumps(
                    dict(
                        noarch=dict(type="python"),
                        entry_points=console_scripts,  # TODO
                        package_metadata_version=1,
                    ),
                    indent=2,
                )
            )

            # info/paths.json - paths with SHA256 do we really need this?
            conda_paths_file = conda_info_dir.joinpath("paths.json")
            paths: List[Dict[str, Any]] = []
            for rel_file in rel_files:
                abs_file = conda_dir.joinpath(rel_file)
                file_bytes = abs_file.read_bytes()
                paths.append(
                    dict(
                        _path=rel_file,
                        path_type="hardlink",
                        sha256=sha256(file_bytes).hexdigest(),
                        size_in_bytes=len(file_bytes),
                    )
                )
            conda_paths_file.write_text(json.dumps(dict(paths=paths, paths_version=1), indent=2))

            #
            # Write the conda package
            #

            dry_run_suffix = " (dry run)" if self.dry_run else ""

            if self.logger.getEffectiveLevel() <= logging.DEBUG:
                for file in conda_dir.glob("**/*"):
                    if file.is_file():
                        self._debug("Packaging %s", file.relative_to(conda_dir))

            if self.out_format is CondaPackageFormat.TREE:
                suffix = ""
            else:
                suffix = str(self.out_format.value)

            conda_pkg_file = f"{package_name}-{version}-py_0{suffix}"
            conda_pkg_path = Path(self.out_dir).joinpath(conda_pkg_file)

            if conda_pkg_path.exists():
                if not self.overwrite:
                    msg = f"Output conda package already exists at '{conda_pkg_path}'"
                    overwrite = False
                    if self.interactive:
                        print(msg)
                        overwrite = bool_input("Overwrite? ")
                    if not overwrite:
                        raise FileExistsError(msg)
                self._info("Removing existing %s%s", conda_pkg_path, dry_run_suffix)
                if not self.dry_run:
                    if conda_pkg_path.is_dir():
                        shutil.rmtree(conda_pkg_path)
                    else:
                        conda_pkg_path.unlink()

            self._info("Writing %s%s", conda_pkg_path, dry_run_suffix)

            if not self.dry_run:
                if self.out_format is CondaPackageFormat.TREE:
                    shutil.copytree(conda_dir, Path(self.out_dir).joinpath(conda_pkg_file))
                else:
                    create_conda_pkg(conda_dir, None, conda_pkg_file, self.out_dir)

            return conda_pkg_path

    def test_install(
        self,
        conda_package: Path,
        *,
        env_prefix: Union[Path, str, None] = None,
        env_name: Optional[str] = None,
        python_version: Optional[str] = None,
        channels: Sequence[str] = (),
    ) -> None:
        """
        Test installing package

        Args:
            conda_package: package file to install
            env_prefix: location of test prefix environment
            env_name: name of test environment.
            python_version: python version of test environment,
                defaults to current environment
            channels: additional channels to use for creation
        """
        # TODO - move to a function in separate module or in converter
        if not python_version:
            python_version = ".".join(str(x) for x in sys.version_info[:2])

        print(f"Test installing package in python {python_version} environment")
        with tempfile.TemporaryDirectory(prefix="whl2conda-test-install-") as tmpdir:
            tmppath = Path(tmpdir)
            if env_prefix is not None:
                env_args = ["-p", str(env_prefix)]
            elif env_name is not None:
                env_args = ["-n", env_name]
            else:
                env_args = ["-p", str(tmppath.joinpath("prefix"))]
            # make a local test channel and index it
            test_channel = tmppath.joinpath("channel")
            test_channel_noarch = test_channel.joinpath("noarch")
            test_channel_noarch.mkdir(parents=True)
            shutil.copyfile(conda_package, test_channel_noarch.joinpath(conda_package.name))
            subprocess.check_call(["conda", "run", "-n", "base", "conda-index", str(test_channel)])
            # create a test prefix
            create_cmd = ["conda", "create", "--yes"]
            create_cmd.extend(env_args)
            # create_cmd.append("--verbose")
            create_cmd.extend(["-c", f"file:/{test_channel}"])
            for channel in channels:
                create_cmd.extend(["-c", channel])
            create_cmd.append(f"python={python_version}")
            create_cmd.append(self.package_name)
            subprocess.check_call(create_cmd)

    def _warn(self, msg, *args):
        self.logger.warning(msg, *args)

    def _info(self, msg, *args):
        self.logger.info(msg, *args)

    def _debug(self, msg, *args):
        self.logger.debug(msg, *args)

    def _trace(self, msg, *args):
        self.logger.log(logging.DEBUG - 5, msg, *args)
