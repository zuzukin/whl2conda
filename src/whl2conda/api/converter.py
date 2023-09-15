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
import configparser
import dataclasses
import email
import io
import json
import logging
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Optional, Sequence, NamedTuple

# third party
from wheel.wheelfile import WheelFile
from conda_package_handling.api import create as create_conda_pkg

# this project
from ..__about__ import __version__
from ..impl.prompt import bool_input
from ..impl.pyproject import CondaPackageFormat
from .stdrename import load_std_renames

__all__ = [
    "CondaPackageFormat",
    "DependencyRename",
    "Wheel2CondaConverter",
    "Wheel2CondaError",
]


def __compile_requires_dist_re() -> re.Pattern:
    # NOTE: these are currently fairly forgiving and will accept bad syntax
    name_re = r"(?P<name>[a-zA-Z0-9_.-]+)"
    extra_re = r"(?:\[(?P<extra>.+?)\])?"
    version_re = r"(?:\(?(?P<version>.*?)\)?)?"
    marker_re = r"(?:;\s*(?P<marker>.*?)\s*)?"
    space = r"\s*"
    return re.compile(
        name_re + space + extra_re + space + version_re + space + marker_re
    )


_requires_dist_re = __compile_requires_dist_re()

_extra_marker_re = [
    re.compile(r"""\bextra\s*==\s*(['"])(?P<name>\w+)\1"""),
    re.compile(r"""\b(['"])(?P<name>\w+)\1\s*==\s*extra"""),
]


@dataclass
class RequiresDistEntry:
    """
    Requires-Dist metadata entry parsed from wheel
    """

    # see https://packaging.python.org/specifications/core-metadata/#requires-dist-multiple-use
    # and https://peps.python.org/pep-0508/
    name: str
    extras: Sequence[str] = ()
    version: str = ""
    marker: str = ""

    extra_marker_name: str = ""
    """Name from extra expression in marker, if any"""

    generic: bool = True
    """True if marker is empty or only contains an extra expression"""

    @classmethod
    def parse(cls, raw: str) -> RequiresDistEntry:
        """
        Parse entry from raw string read from "Requires-Dist" or related header.

        Raises:
            SyntaxError: if entry is not properly formatted.
        """
        m = _requires_dist_re.fullmatch(raw)
        if not m:
            raise SyntaxError(f"Cannot parse Requires-Dist entry: {repr(raw)}")
        entry = RequiresDistEntry(name=m.group("name"))
        if extra := m.group("extra"):
            entry.extras = tuple(re.split(r"\s*,\s*", extra))
        if version := m.group("version"):
            entry.version = version
        if marker := m.group("marker"):
            entry.marker = marker
            entry.generic = False
            for pat in _extra_marker_re:
                if m := pat.search(marker):
                    entry.extra_marker_name = m.group("name")
                    if m.string == marker:
                        entry.generic = True
                    break
        return entry

    def __str__(self) -> str:
        with io.StringIO() as buf:
            buf.write(self.name)
            if self.extras:
                buf.write(f" [{','.join(self.extras)}]")
            if self.version:
                buf.write(f" {self.version}")
            if self.marker:
                buf.write(f" ; {self.marker}")
            return buf.getvalue()


class Wheel2CondaError(RuntimeError):
    """Errors from Wheel2CondaConverter"""


def non_none_dict(**kwargs: Any) -> dict[str,Any]:
    """dict that drops keys with None values"""
    d = dict()
    for k,v in kwargs.items():
        if v is not None:
            d[k] = v
    return d


@dataclass
class MetadataFromWheel:
    """Metadata parsed from wheel distribution"""

    md: dict[str, Any]
    package_name: str
    version: str
    wheel_build_number: str
    license: Optional[str]
    dependencies: list[RequiresDistEntry]
    wheel_info_dir: Path


class DependencyRename(NamedTuple):
    r"""
    Defines a pypi to conda package renaming rule.

    The pattern must fully match the input package.
    The replacement string may contain group references
    e.g. r'\1', r'\g<name>`.
    """

    pattern: re.Pattern
    replacement: str

    @classmethod
    def from_strings(cls, pattern: str, replacement: str) -> DependencyRename:
        r"""Construct from strings

        This will also translate '$#' and '${name}' expressions
        into r'\#' and r'\P<name>' respectively.
        """
        try:
            pat = re.compile(pattern)
        except re.error as err:
            # pylint: disable=raise-missing-from
            raise ValueError(f"Bad dependency rename pattern '{pattern}': {err}")
        repl = re.sub(r"\$(\d+)", r"\\\1", replacement)
        repl = re.sub(r"\$\{(\w+)}", r"\\g<\1>", repl)
        # TODO also verify replacement does not contain invalid package chars
        try:
            pat.sub(repl, "")
        except Exception as ex:
            if isinstance(ex, re.error):
                msg = ex.msg
            else:
                msg = str(ex)
            # pylint: disable=raise-missing-from
            raise ValueError(
                f"Bad dependency replacement '{replacement}' for pattern '{pattern}': {msg}"
            )
        return cls(pat, repl)

    def rename(self, pypi_name: str) -> tuple[str, bool]:
        """Rename dependency package name

        Returns conda name and indicator of whether the
        pattern was applied.
        """
        if m := self.pattern.fullmatch(pypi_name):
            return m.expand(self.replacement), True
        return pypi_name, False


class Wheel2CondaConverter:
    """
    Converter supports generation of conda package from a pure python wheel.

    """

    SUPPORTED_WHEEL_VERSIONS = ("1.0",)
    SUPPORTED_METADATA_VERSIONS = ("1.0", "1.1", "1.2", "2.1", "2.2", "2.3")
    MULTI_USE_METADATA_KEYS = {
        "Classifier",
        "Dynamic",
        "License-File",
        "Obsoletes",
        "Obsoletes-Dist",
        "Platform",
        "Project-URL",
        "Provides",
        "Provides-Dist",
        "Provides-Extra",
        "Requires",
        "Requires-Dist",
        "Requires-External",
        "Supported-Platform",
    }

    package_name: str = ""
    logger: logging.Logger
    wheel_path: Path
    out_dir: Path
    dry_run: bool = False
    wheel: Optional[WheelFile]
    out_format: CondaPackageFormat
    overwrite: bool = False
    keep_pip_dependencies: bool = False
    dependency_rename: list[DependencyRename]
    extra_dependencies: list[str]
    interactive: bool = False
    build_number: Optional[int] = None

    wheel_md: Optional[MetadataFromWheel] = None
    conda_pkg_path: Optional[Path] = None
    std_renames: dict[str, str]

    temp_dir: Optional[tempfile.TemporaryDirectory] = None

    def __init__(
        self,
        wheel_path: Path,
        out_dir: Path,
    ):
        self.logger = logging.getLogger(__name__)
        self.wheel_path = wheel_path
        self.out_dir = out_dir
        self.dependency_rename = []
        self.extra_dependencies = []
        # TODO - option to ignore this
        self.std_renames = load_std_renames()

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
        # pylint: disable=too-many-statements,too-many-branches,too-many-locals

        with self:
            assert self.temp_dir is not None

            extracted_wheel_dir = self._extract_wheel()

            wheel_md = self._parse_wheel_metadata(extracted_wheel_dir)

            conda_dir = Path(self.temp_dir.name).joinpath("conda-files")
            conda_info_dir = conda_dir.joinpath("info")
            conda_dir.mkdir()

            # Copy files into site packages and get relative paths
            rel_files = self._copy_site_packages(extracted_wheel_dir, conda_dir)

            conda_dependencies = self._compute_conda_dependencies(wheel_md.dependencies)

            # Write conda info files
            self._copy_licenses(conda_info_dir, wheel_md)
            self._write_about(conda_info_dir, wheel_md.md)
            self._write_hash_input(conda_info_dir)
            self._write_files_list(conda_info_dir, rel_files)
            self._write_index(conda_info_dir, wheel_md, conda_dependencies)
            self._write_link_file(conda_info_dir, wheel_md.wheel_info_dir)
            self._write_paths_file(conda_dir, rel_files)

            conda_pkg_path = self._conda_package_path(
                wheel_md.package_name, wheel_md.version
            )
            self._write_conda_package(conda_dir, conda_pkg_path)

            return conda_pkg_path

    def _conda_package_path(self, package_name: str, version: str) -> Path:
        """Construct conda package file path"""
        if self.out_format is CondaPackageFormat.TREE:
            suffix = ""
        else:
            suffix = str(self.out_format.value)
        conda_pkg_file = f"{package_name}-{version}-py_0{suffix}"
        self.conda_pkg_path = Path(self.out_dir).joinpath(conda_pkg_file)
        return self.conda_pkg_path

    # pylint: disable=too-many-branches
    def _write_conda_package(self, conda_dir: Path, conda_pkg_path: Path) -> Path:
        dry_run_suffix = " (dry run)" if self.dry_run else ""
        if self.logger.getEffectiveLevel() <= logging.DEBUG:
            for file in conda_dir.glob("**/*"):
                if file.is_file():
                    self._debug("Packaging %s", file.relative_to(conda_dir))
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
                shutil.copytree(
                    conda_dir, Path(self.out_dir).joinpath(conda_pkg_path.name)
                )
            else:
                self.out_dir.mkdir(parents=True, exist_ok=True)
                create_conda_pkg(conda_dir, None, conda_pkg_path.name, self.out_dir)

        return conda_pkg_path

    def _write_paths_file(self, conda_dir: Path, rel_files: Sequence[str]) -> None:
        # info/paths.json - paths with SHA256 do we really need this?
        conda_paths_file = conda_dir.joinpath("info", "paths.json")
        paths: list[dict[str, Any]] = []
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
        conda_paths_file.write_text(
            json.dumps(dict(paths=paths, paths_version=1), indent=2)
        )

    def _write_link_file(self, conda_info_dir: Path, wheel_info_dir: Path) -> None:
        # info/link.json
        conda_link_file = conda_info_dir.joinpath("link.json")
        wheel_entry_points_file = wheel_info_dir.joinpath("entry_points.txt")
        console_scripts: list[str] = []
        if wheel_entry_points_file.is_file():
            wheel_entry_points = configparser.ConfigParser()
            wheel_entry_points.read(wheel_entry_points_file)
            for section_name in ["console_scripts", "gui_scripts"]:
                if section_name in wheel_entry_points:
                    if section := wheel_entry_points[section_name]:
                        console_scripts.extend(f"{k}={v}" for k, v in section.items())
        conda_link_file.write_text(
            json.dumps(
                dict(
                    noarch=dict(type="python"),
                    entry_points=console_scripts,
                    package_metadata_version=1,
                ),
                indent=2,
            )
        )

    # pylint: disable=too-many-arguments
    def _write_index(
        self,
        conda_info_dir: Path,
        wheel_md: MetadataFromWheel,
        conda_dependencies: Sequence[str],
    ) -> None:
        # info/index.json
        conda_index_file = conda_info_dir.joinpath("index.json")

        if self.build_number is not None:
            build_number = self.build_number
        else:
            try:
                build_number = int(wheel_md.wheel_build_number)
            except ValueError:
                build_number = 0

        conda_index_file.write_text(
            json.dumps(
                dict(
                    arch=None,
                    build="py_0",
                    build_number=build_number,
                    depends=conda_dependencies,
                    license=wheel_md.license,
                    name=wheel_md.package_name,
                    noarch="python",
                    platform=None,
                    subdir="noarch",
                    timestamp=int(time.time() + time.timezone),  # UTC timestamp
                    version=wheel_md.version,
                ),
                indent=2,
            )
        )

    def _write_files_list(self, conda_info_dir: Path, rel_files: Sequence[str]) -> None:
        # * info/files - list of relative paths of files not including info/
        conda_files_file = conda_info_dir.joinpath("files")
        with open(conda_files_file, "w") as f:
            for rel_file in rel_files:
                f.write(str(rel_file))
                f.write("\n")

    def _write_hash_input(self, conda_info_dir: Path) -> None:
        conda_hash_input_file = conda_info_dir.joinpath("hash_input.json")
        conda_hash_input_file.write_text(json.dumps({}, indent=2))

    def _write_about(self, conda_info_dir: Path, md: dict[str, Any]) -> None:
        # * info/about.json
        license = md.get("license-expression") or md.get("license")
        conda_about_file = conda_info_dir.joinpath("about.json")
        # TODO description can come from METADATA message body
        #   then need to also use content type. It doesn't seem
        #   that conda-forge packages include this in the info/
        doc_url: Optional[str] = None
        dev_url: Optional[str] = None
        extra: dict[str, Any] = {}
        for urlline in md.get("project-url", ()):
            urlparts = re.split(r"\s*,\s*", urlline, maxsplit=1)
            if len(urlparts) > 1:
                key, url = urlparts
                keyl = key.lower()
                if re.match(r"doc(umentation)?\b", keyl):
                    doc_url = urlparts[1]
                elif re.match(r"(dev(elopment)?|repo(sitory))\b", keyl):
                    dev_url = urlparts[1]
                if key and url:
                    extra[key] = url
        for key in ["author", "maintainer", "author-email", "maintainer-email"]:
            val = md.get(key)
            if val:
                extra[key] = val
        if license_files := md.get("license-file"):
            extra["license_files"] = list(license_files)
        conda_about_file.write_text(
            json.dumps(
                non_none_dict(
                    description=md.get("description"),
                    summary=md.get("summary"),
                    license=license or None,
                    classifiers=md.get("classifier"),
                    keywords=md.get("keywords"),
                    home=md.get("home-page"),
                    whl2conda_version=__version__,
                    dev_url=dev_url,
                    doc_url=doc_url,
                    extra=extra or None,
                ),
                indent=2,
            )
        )

    # pylint: disable=too-many-locals
    def _compute_conda_dependencies(
        self,
        dependencies: Sequence[RequiresDistEntry],
    ) -> list[str]:
        conda_dependencies: list[str] = []

        # TODO - instead RequiresDistEntrys should be passed as an argument

        for entry in dependencies:
            if entry.extra_marker_name:
                self._debug("Skipping extra dependency: %s", entry)
                continue
            if not entry.generic:
                # TODO - support non-generic packages
                self._warn("Skipping dependency with environment marker: %s", entry)
                continue

            conda_name = pip_name = entry.name
            version = entry.version
            # TODO - do something with extras (#36)
            #   download target pip package and its extra dependencies
            # check manual renames first
            renamed = False
            for renamer in self.dependency_rename:
                conda_name, renamed = renamer.rename(pip_name)
                if renamed:
                    break
            if not renamed:
                conda_name = self.std_renames.get(pip_name, pip_name)

            if conda_name:
                conda_dep = f"{conda_name} {version}"
                if conda_name == pip_name:
                    self._debug("Dependency copied: '%s'", conda_dep)
                else:
                    self._debug("Dependency renamed: '%s' -> '%s'", entry, conda_dep)
                conda_dependencies.append(conda_dep)
            else:
                self._debug("Dependency dropped: %s", entry)
        for dep in self.extra_dependencies:
            self._debug("Dependency added:  '%s'", dep)
            conda_dependencies.append(dep)
        return conda_dependencies

    def _copy_site_packages(self, wheel_dir: Path, conda_dir: Path) -> list[str]:
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
        return rel_files

    def _copy_licenses(self, conda_info_dir: Path, wheel_md: MetadataFromWheel) -> None:
        to_license_dir = conda_info_dir / "licenses"
        wheel_info_dir = wheel_md.wheel_info_dir
        wheel_license_dir = wheel_info_dir / "licenses"
        if wheel_license_dir.is_dir():
            # just copy directory
            shutil.copytree(
                wheel_license_dir,
                to_license_dir,
                dirs_exist_ok=True,
            )
        else:
            # Otherwise look for files in the dist-info dir
            # that match the license-file entries. The paths
            # of the license-file entries may be relative to
            # where the wheel was built and may not directly
            # point at the files.
            for license_file in wheel_md.md.get("license-file", ()):
                # copy license file if it exists
                license_path = Path(license_file)
                from_files = [wheel_info_dir / license_path.name]
                if not license_path.is_absolute():
                    from_files.insert(0, wheel_info_dir / license_path)
                for from_file in from_files:
                    if from_file.exists():
                        to_file = to_license_dir / from_file.relative_to(wheel_info_dir)
                        if not to_file.exists():
                            to_file.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(from_file, to_file)
                            break

    # pylint: disable=too-many-locals, too-many-statements
    def _parse_wheel_metadata(self, wheel_dir: Path) -> MetadataFromWheel:
        wheel_info_dir = next(wheel_dir.glob("*.dist-info"))
        WHEEL_file = wheel_info_dir.joinpath("WHEEL")
        WHEEL_msg = email.message_from_string(WHEEL_file.read_text("utf8"))
        # https://peps.python.org/pep-0427/#what-s-the-deal-with-purelib-vs-platlib

        is_pure_lib = WHEEL_msg.get("Root-Is-Purelib", "").lower() == "true"
        wheel_build_number = WHEEL_msg.get("Build", "")
        wheel_version = WHEEL_msg.get("Wheel-Version")

        if wheel_version not in self.SUPPORTED_WHEEL_VERSIONS:
            raise Wheel2CondaError(
                f"Wheel {self.wheel_path} has unsupported wheel version {wheel_version}"
            )

        if not is_pure_lib:
            raise Wheel2CondaError(f"Wheel {self.wheel_path} is not pure python")

        wheel_md_file = wheel_info_dir.joinpath("METADATA")
        md: dict[str, list[Any]] = {}
        # Metdata spec: https://packaging.python.org/en/latest/specifications/core-metadata/
        # Required keys: Metadata-Version, Name, Version
        md_msg = email.message_from_string(wheel_md_file.read_text())
        md_version_str = md_msg.get("Metadata-Version")
        if md_version_str not in self.SUPPORTED_METADATA_VERSIONS:
            # TODO - perhaps just warn about this if not in "strict" mode
            raise Wheel2CondaError(
                f"Wheel {self.wheel_path} has unsupported metadata version {md_version_str}"
            )
        # md_version = tuple(int(x) for x in md_version_str.split("."))
        for mdkey, mdval in md_msg.items():
            mdkey = mdkey.strip()
            if mdkey in self.MULTI_USE_METADATA_KEYS:
                md.setdefault(mdkey.lower(), []).append(mdval)
            else:
                md[mdkey.lower()] = mdval
            if mdkey in {"requires-dist", "requires"}:
                continue

        requires: list[RequiresDistEntry] = []
        raw_requires_entries = md.get("requires-dist", md.get("requires", ()))
        for raw_entry in raw_requires_entries:
            try:
                entry = RequiresDistEntry.parse(raw_entry)
                requires.append(entry)
            except SyntaxError as err:
                # TODO: error in strict mode?
                self._warn(str(err))

        if not self.keep_pip_dependencies:
            # Turn requirements into optional extra requirements
            del md_msg["Requires"]
            del md_msg["Requires-Dist"]
            for entry in requires:
                if not entry.extra_marker_name:
                    marker = entry.marker
                    extra_clause = "extra == 'original'"
                    if marker:
                        marker = f"({entry.marker}) and {extra_clause}"
                    else:
                        marker = extra_clause
                    entry = dataclasses.replace(entry, marker=marker)
                md_msg.add_header("Requires-Dist", str(entry))
            md_msg.add_header("Provides-Extra", "original")
            wheel_md_file.write_text(md_msg.as_string())
        package_name = self.package_name or str(md.get("name"))
        self.package_name = package_name
        version = md.get("version")

        python_version: str = str(md.get("requires-python", ""))
        if python_version:
            requires.append(RequiresDistEntry("python", version=python_version))
        self.wheel_md = MetadataFromWheel(
            md=md,
            package_name=package_name,
            version=str(version),
            wheel_build_number=wheel_build_number,
            license=md.get("license-expression") or md.get("license"),  # type: ignore
            dependencies=requires,
            wheel_info_dir=wheel_info_dir,
        )
        return self.wheel_md

    def _extract_wheel(self) -> Path:
        self.logger.info("Reading %s", self.wheel_path)
        wheel = WheelFile(self.wheel_path)
        assert self.temp_dir
        wheel_dir = Path(self.temp_dir.name).joinpath("wheel-files")
        wheel.extractall(wheel_dir)
        if self.logger.getEffectiveLevel() <= logging.DEBUG:
            for wheel_file in wheel_dir.glob("**/*"):
                if wheel_file.is_file():
                    self._debug("Extracted %s", wheel_file.relative_to(wheel_dir))
        return wheel_dir

    def _warn(self, msg, *args):
        self.logger.warning(msg, *args)

    def _info(self, msg, *args):
        self.logger.info(msg, *args)

    def _debug(self, msg, *args):
        self.logger.debug(msg, *args)

    def _trace(self, msg, *args):
        self.logger.log(logging.DEBUG - 5, msg, *args)
