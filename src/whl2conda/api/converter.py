#  Copyright 2023-2026 Christopher Barber
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
import email.message
import email.policy
import io
import json
import logging
import re
import shutil
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, NamedTuple

# third party
from conda_package_handling.api import create as create_conda_pkg

# this project
from ..__about__ import __version__
from ..impl.prompt import bool_input
from ..impl.pyproject import CondaPackageFormat
from ..impl.wheel import unpack_wheel
from .stdrename import load_std_renames

__all__ = [
    "CondaPackageFormat",
    "CondaTargetInfo",
    "DependencyRename",
    "Wheel2CondaConverter",
    "Wheel2CondaError",
    "normalize_pypi_name",
]


def __compile_requires_dist_re() -> re.Pattern:
    # NOTE: these are currently fairly forgiving and will accept bad syntax
    name_re = r"(?P<name>[a-zA-Z0-9_.-]+)"
    extra_re = r"(?:\[(?P<extra>.+?)\])?"
    version_re = r"(?:\(?(?P<version>[^;]*?)\)?)?"
    marker_re = r"(?:;\s*(?P<marker>.*?)\s*)?"
    space = r"\s*"
    return re.compile(
        space + name_re + space + extra_re + space + version_re + space + marker_re
    )


requires_dist_re = __compile_requires_dist_re()

_extra_marker_re = [
    re.compile(r"""\bextra\s*==\s*(['"])(?P<name>\w+)\1"""),
    re.compile(r"""\b(['"])(?P<name>\w+)\1\s*==\s*extra"""),
]

# Version pattern from official python packaging spec:
# https://packaging.python.org/en/latest/specifications/version-specifiers/#appendix-parsing-version-strings-with-regular-expressions
# which original comes from:
# https://github.com/pypa/packaging (either Apache or BSD license)

PIP_VERSION_PATTERN = r"""
    v?
    (?:
        (?:(?P<epoch>[0-9]+)!)?                           # epoch
        (?P<release>[0-9]+(?:\.[0-9]+)*)                  # release segment
        (?P<pre>                                          # pre-release
            [-_\.]?
            (?P<pre_l>(a|b|c|rc|alpha|beta|pre|preview))
            [-_\.]?
            (?P<pre_n>[0-9]+)?
        )?
        (?P<post>                                         # post release
            (?:-(?P<post_n1>[0-9]+))
            |
            (?:
                [-_\.]?
                (?P<post_l>post|rev|r)
                [-_\.]?
                (?P<post_n2>[0-9]+)?
            )
        )?
        (?P<dev>                                          # dev release
            [-_\.]?
            (?P<dev_l>dev)
            [-_\.]?
            (?P<dev_n>[0-9]+)?
        )?
    )
    (?:\+(?P<local>[a-z0-9]+(?:[-_\.][a-z0-9]+)*))?       # local version
"""

pip_version_re = re.compile(
    r"^\s*(?P<operator>[=<>!~]+)\s*(?P<version>" + PIP_VERSION_PATTERN + r")\s*$",
    re.VERBOSE | re.IGNORECASE,
)
"""
Regular expression matching pip version spec
"""


def normalize_pypi_name(name: str) -> str:
    """Normalize a PyPI package name per PEP 503.

    Converts to lowercase and replaces any runs of ``[-_.]``
    with a single dash.
    """
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass(slots=True)
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

    def set_marker(self, marker: str) -> None:
        """Set marker value and update extra_marker_name and generic values"""
        self.marker = marker
        self.generic = False
        for pat in _extra_marker_re:
            if m := pat.search(marker):
                self.extra_marker_name = m.group("name")
                if m.group(0) == marker:
                    self.generic = True
                return

    @classmethod
    def parse(cls, raw: str) -> RequiresDistEntry:
        """
        Parse entry from raw string read from "Requires-Dist" or related header.

        Raises:
            SyntaxError: if entry is not properly formatted.
        """
        m = requires_dist_re.fullmatch(raw)
        if not m:
            raise SyntaxError(f"Cannot parse Requires-Dist entry: {raw!r}")
        entry = RequiresDistEntry(name=normalize_pypi_name(m.group("name")))
        if extra := m.group("extra"):
            entry.extras = tuple(re.split(r"\s*,\s*", extra))
        if version := m.group("version"):
            entry.version = version
        if marker := m.group("marker"):
            entry.set_marker(marker)
        return entry

    def with_extra(self, name: str) -> RequiresDistEntry:
        """Returns copy of entry with  an extra == '<name>' clause to marker"""
        marker = f"extra == '{name}'"
        if self.marker:
            marker = f"({self.marker}) and {marker}"

        entry = dataclasses.replace(self)
        entry.set_marker(marker)
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


def non_none_dict(**kwargs: Any) -> dict[str, Any]:
    """dict that drops keys with None values"""
    return {k: v for k, v in kwargs.items() if v is not None}


@dataclass(slots=True)
class MetadataFromWheel:
    """Metadata parsed from wheel distribution"""

    md: dict[str, Any]
    package_name: str
    version: str
    wheel_build_number: str
    license: str | None
    dependencies: list[RequiresDistEntry]
    wheel_info_dir: Path
    is_pure_python: bool
    python_tag: str
    abi_tag: str
    platform_tag: str


@dataclass(slots=True)
class CondaTargetInfo:
    """Conda package target metadata derived from wheel tags.

    For noarch (pure python) packages, uses standard noarch values.
    For platform-specific packages, derives values from wheel platform tags.
    """

    subdir: str
    arch: str | None
    platform: str | None
    build_string: str
    is_noarch: bool
    site_packages_prefix: str
    python_version: str = ""
    """Python version for binary packages (e.g. '3.13'). Empty for noarch."""

    def marker_environment(self) -> dict[str, str]:
        """Return PEP 508 marker environment for the target platform.

        Used to evaluate environment markers on dependencies when
        converting binary wheels.
        """
        match self.platform:
            case "linux":
                os_name = "posix"
                sys_platform = "linux"
                platform_system = "Linux"
            case "osx":
                os_name = "posix"
                sys_platform = "darwin"
                platform_system = "Darwin"
            case "win":
                os_name = "nt"
                sys_platform = "win32"
                platform_system = "Windows"
            case _:
                return {}

        # Map conda arch to platform_machine values
        machine_map = {
            "x86_64": "x86_64",
            "arm64": "arm64",
            "aarch64": "aarch64",
            "x86": "x86",
            "ppc64le": "ppc64le",
            "s390x": "s390x",
            "armv7l": "armv7l",
        }
        platform_machine = machine_map.get(self.arch or "", "")

        return {
            "os_name": os_name,
            "sys_platform": sys_platform,
            "platform_system": platform_system,
            "platform_machine": platform_machine,
            "platform_python_implementation": "CPython",
            "implementation_name": "cpython",
            "python_version": self.python_version,
            "python_full_version": f"{self.python_version}.0",
            "implementation_version": f"{self.python_version}.0",
        }

    @classmethod
    def from_wheel_metadata(
        cls,
        wheel_md: MetadataFromWheel,
        build_number: int = 0,
    ) -> CondaTargetInfo:
        """Create from wheel metadata.

        For pure python wheels, returns noarch target info.
        For platform-specific wheels, derives conda metadata from wheel tags.
        """
        if wheel_md.is_pure_python:
            return cls(
                subdir="noarch",
                arch=None,
                platform=None,
                build_string="py_0",
                is_noarch=True,
                site_packages_prefix="site-packages",
            )

        # Platform-specific package
        subdir, arch, platform = _parse_platform_tag(wheel_md.platform_tag)
        python_version = _python_version_from_tag(wheel_md.python_tag)
        build_string = f"py{''.join(python_version.split('.'))}_{build_number}"

        if platform == "win":
            site_packages_prefix = "Lib/site-packages"
        else:
            site_packages_prefix = f"lib/python{python_version}/site-packages"

        return cls(
            subdir=subdir,
            arch=arch,
            platform=platform,
            build_string=build_string,
            is_noarch=False,
            site_packages_prefix=site_packages_prefix,
            python_version=python_version,
        )


# Mapping of wheel platform tag patterns to (subdir, arch, platform)
_WHEEL_PLATFORM_MAP: list[tuple[re.Pattern, str, str, str]] = [
    (re.compile(r"macosx_.*_arm64"), "osx-arm64", "arm64", "osx"),
    (re.compile(r"macosx_.*_x86_64"), "osx-64", "x86_64", "osx"),
    (re.compile(r"macosx_.*_universal2"), "osx-arm64", "arm64", "osx"),
    (re.compile(r"(?:many|musl)linux.*_x86_64"), "linux-64", "x86_64", "linux"),
    (re.compile(r"(?:many|musl)linux.*_aarch64"), "linux-aarch64", "aarch64", "linux"),
    (re.compile(r"(?:many|musl)linux.*_ppc64le"), "linux-ppc64le", "ppc64le", "linux"),
    (re.compile(r"(?:many|musl)linux.*_s390x"), "linux-s390x", "s390x", "linux"),
    (re.compile(r"(?:many|musl)linux.*_armv7l"), "linux-armv7l", "armv7l", "linux"),
    (re.compile(r"win_amd64"), "win-64", "x86_64", "win"),
    (re.compile(r"win32"), "win-32", "x86", "win"),
    (re.compile(r"win_arm64"), "win-arm64", "arm64", "win"),
]


def _parse_platform_tag(platform_tag: str) -> tuple[str, str, str]:
    """Parse wheel platform tag into (subdir, arch, platform).

    Returns:
        Tuple of (conda_subdir, arch, platform)

    Raises:
        Wheel2CondaError: if platform tag is not recognized
    """
    for pattern, subdir, arch, platform in _WHEEL_PLATFORM_MAP:
        if pattern.fullmatch(platform_tag):
            return subdir, arch, platform
    raise Wheel2CondaError(f"Unsupported wheel platform tag: '{platform_tag}'")


def _python_version_from_tag(python_tag: str) -> str:
    """Extract python version string from wheel python tag.

    E.g., "cp313" -> "3.13", "cp39" -> "3.9", "py3" -> "3"
    """
    m = re.match(r"(?:cp|py)(\d)(\d+)?", python_tag)
    if m:
        major = m.group(1)
        minor = m.group(2) or ""
        if minor:
            return f"{major}.{minor}"
        return major
    return python_tag


def _os_constraint_from_platform_tag(platform_tag: str) -> str:
    """Extract OS minimum version constraint from wheel platform tag.

    For macOS wheels like ``macosx_11_0_arm64``, returns ``__osx >=11.0``.
    Returns empty string if no OS constraint can be derived.
    """
    if m := re.match(r"macosx_(\d+)_(\d+)", platform_tag):
        major, minor = m.group(1), m.group(2)
        return f"__osx >={major}.{minor}"
    return ""


def _python_pin_from_version(python_version: str) -> list[str]:
    """Generate tight Python version pin dependencies for binary packages.

    For a version like ``3.13``, returns::

        ["python >=3.13,<3.14.0a0", "python_abi 3.13.* *_cp313"]

    Returns empty list if version has no minor component.
    """
    parts = python_version.split(".")
    if len(parts) != 2:
        return []
    major, minor = parts
    next_minor = int(minor) + 1
    return [
        f"python >={python_version},<{major}.{next_minor}.0a0",
        f"python_abi {python_version}.* *_cp{major}{minor}",
    ]


def _evaluate_marker(marker: str, env: dict[str, str]) -> bool:
    """Evaluate a PEP 508 environment marker against the given environment.

    Returns True if the marker is satisfied, False otherwise.
    Returns True on parse errors (conservative — include the dependency).
    """
    try:
        from packaging.markers import Marker

        m = Marker(marker)
        return bool(m.evaluate(env))
    except Exception:
        return True


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
            raise ValueError(
                f"Bad dependency replacement '{replacement}' for pattern '{pattern}': {msg}"
            )
        return cls(pat, repl)

    def rename(self, pypi_name: str) -> tuple[str, bool]:
        """Rename dependency package name

        The name is normalized before matching per PEP 503.

        Returns conda name and indicator of whether the
        pattern was applied.
        """
        normalized = normalize_pypi_name(pypi_name)
        if m := self.pattern.fullmatch(normalized):
            return m.expand(self.replacement), True
        return pypi_name, False


class Wheel2CondaConverter:
    """
    Converter supports generation of conda package from a pure python wheel.

    """

    SUPPORTED_WHEEL_VERSIONS = ("1.0",)
    SUPPORTED_METADATA_VERSIONS: tuple[str, ...] = (
        "1.0",
        "1.1",
        "1.2",
        "2.1",
        "2.2",
        "2.3",
        "2.4",
    )
    MULTI_USE_METADATA_KEYS: frozenset[str] = frozenset({
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
    })

    package_name: str = ""
    logger: logging.Logger
    wheel_path: Path
    out_dir: Path
    dry_run: bool = False
    out_format: CondaPackageFormat = CondaPackageFormat.V2
    overwrite: bool = False
    keep_pip_dependencies: bool = False
    dependency_rename: list[DependencyRename]
    extra_dependencies: list[str]
    python_version: str = ""
    interactive: bool = False
    build_number: int | None = None
    allow_impure: bool = False

    wheel_md: MetadataFromWheel | None = None
    conda_target: CondaTargetInfo | None = None
    conda_pkg_path: Path | None = None
    std_renames: dict[str, str]

    def __init__(
        self,
        wheel_path: Path,
        out_dir: Path,
        *,
        update_std_renames: bool = False,
    ):
        self.logger = logging.getLogger(__name__)
        self.wheel_path = wheel_path
        self.out_dir = out_dir
        self.dependency_rename = []
        self.extra_dependencies = []
        # TODO - option to ignore this
        self.std_renames = load_std_renames(update=update_std_renames)

    def convert(self) -> Path:
        """
        Convert wheel to conda package

        Does not write any non-temporary files if dry_run is True.

        Returns:
            Path of conda package
        """
        with tempfile.TemporaryDirectory(prefix="whl2conda-") as temp_dirname:
            temp_dir = Path(temp_dirname)
            extracted_wheel_dir = self._extract_wheel(temp_dir)

            wheel_md = self._parse_wheel_metadata(extracted_wheel_dir)

            if self.build_number is not None:
                build_number = self.build_number
            else:
                try:
                    build_number = int(wheel_md.wheel_build_number)
                except ValueError:
                    build_number = 0

            conda_target = CondaTargetInfo.from_wheel_metadata(
                wheel_md, build_number=build_number
            )
            self.conda_target = conda_target

            if not conda_target.is_noarch:
                self._check_binary_conversion(wheel_md)

            conda_dir = temp_dir / "conda-files"
            conda_info_dir = conda_dir.joinpath("info")
            conda_dir.mkdir()

            # Copy files into conda package
            self._copy_wheel_files(extracted_wheel_dir, conda_dir)

            # collect relative paths before constructing info/ directory
            rel_files = [
                str(f.relative_to(conda_dir))
                for f in conda_dir.glob("**/*")
                if f.is_file()
            ]

            # For binary packages, evaluate platform markers against target
            marker_env = (
                conda_target.marker_environment()
                if not conda_target.is_noarch
                else None
            )
            conda_dependencies = self._compute_conda_dependencies(
                wheel_md.dependencies, marker_env=marker_env
            )

            # Add binary-specific dependencies
            if not conda_target.is_noarch:
                self._warn(
                    "Experimental: converting non-pure wheel '%s'. "
                    "Converted package may include bundled libraries that "
                    "differ from conda-forge shared library packages.",
                    self.wheel_path.name,
                )
                conda_dependencies = self._add_binary_dependencies(
                    conda_dependencies, conda_target, wheel_md.platform_tag
                )

            # Write conda info files
            # TODO - copy readme file into info
            #  must be one of README, README.md or README.rst
            self._copy_licenses(conda_info_dir, wheel_md)
            self._write_about(conda_info_dir, wheel_md.md)
            self._write_hash_input(conda_info_dir)
            self._write_files_list(conda_info_dir, rel_files)
            self._write_index(
                conda_info_dir, wheel_md, conda_dependencies, conda_target
            )
            self._write_link_file(conda_info_dir, wheel_md, conda_target)
            self._write_paths_file(conda_dir, rel_files)
            self._write_git_file(conda_info_dir)

            conda_pkg_path = self._conda_package_path(
                wheel_md.package_name, wheel_md.version, conda_target
            )
            self._write_conda_package(conda_dir, conda_pkg_path)

            return conda_pkg_path

    @classmethod
    def read_metadata_file(cls, file: Path) -> email.message.Message:
        """
        Read a wheel email-formatted metadata file (e.g. METADATA, WHEEL)

        Args:
            file: path to file

        Returns:
            Message object
        """
        return email.message_from_string(
            file.read_text(encoding="utf8", errors="backslashreplace"),
            policy=email.policy.EmailPolicy(utf8=True, refold_source="none"),  # type: ignore
        )

    def _conda_package_path(
        self, package_name: str, version: str, conda_target: CondaTargetInfo
    ) -> Path:
        """Construct conda package file path"""
        if self.out_format is CondaPackageFormat.TREE:
            suffix = ""
        else:
            suffix = str(self.out_format.value)
        conda_pkg_file = f"{package_name}-{version}-{conda_target.build_string}{suffix}"
        self.conda_pkg_path = Path(self.out_dir).joinpath(conda_pkg_file)
        return self.conda_pkg_path

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

    def _write_git_file(self, conda_info_dir: Path) -> None:
        """Write empty git file"""
        # python wheels don't have this concept, but conda-build
        # will write an empty git file if there are no git sources,
        # so we follow suit:
        conda_info_dir.joinpath("git").write_bytes(b'')

    def _write_paths_file(self, conda_dir: Path, rel_files: Sequence[str]) -> None:
        # info/paths.json - paths with SHA256 do we really need this?
        conda_paths_file = conda_dir.joinpath("info", "paths.json")
        paths: list[dict[str, Any]] = []
        for rel_file in rel_files:
            abs_file = conda_dir.joinpath(rel_file)
            file_bytes = abs_file.read_bytes()
            paths.append({
                "_path": rel_file,
                "path_type": "hardlink",
                "sha256": sha256(file_bytes).hexdigest(),
                "size_in_bytes": len(file_bytes),
            })
        conda_paths_file.write_text(
            json.dumps({"paths": paths, "paths_version": 1}, indent=2), encoding="utf8"
        )

    def _write_link_file(
        self,
        conda_info_dir: Path,
        wheel_md: MetadataFromWheel,
        conda_target: CondaTargetInfo,
    ) -> None:
        # Binary packages don't use link.json (matches conda-forge convention)
        if not conda_target.is_noarch:
            return

        # info/link.json
        conda_link_file = conda_info_dir.joinpath("link.json")
        wheel_entry_points_file = wheel_md.wheel_info_dir.joinpath("entry_points.txt")
        console_scripts: list[str] = []
        if wheel_entry_points_file.is_file():
            wheel_entry_points = configparser.ConfigParser()
            wheel_entry_points.read(wheel_entry_points_file)
            for section_name in ["console_scripts", "gui_scripts"]:
                if section_name in wheel_entry_points:
                    section = wheel_entry_points[section_name]
                    console_scripts.extend(f"{k}={v}" for k, v in section.items())

        link_dict: dict[str, Any] = {"package_metadata_version": 1}
        noarch_dict: dict[str, Any] = {"type": "python"}
        if console_scripts:
            noarch_dict["entry_points"] = console_scripts
        link_dict["noarch"] = noarch_dict

        conda_link_file.write_text(
            json.dumps(link_dict, indent=2, sort_keys=True),
            encoding="utf8",
        )

    def _write_index(
        self,
        conda_info_dir: Path,
        wheel_md: MetadataFromWheel,
        conda_dependencies: Sequence[str],
        conda_target: CondaTargetInfo,
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

        index_dict: dict[str, Any] = {
            "arch": conda_target.arch,
            "build": conda_target.build_string,
            "build_number": build_number,
            "depends": conda_dependencies,
            "license": wheel_md.license,
            "name": wheel_md.package_name,
            "platform": conda_target.platform,
            "subdir": conda_target.subdir,
            "timestamp": int(time.time() + time.timezone),  # UTC timestamp
            "version": wheel_md.version,
        }
        if conda_target.is_noarch:
            index_dict["noarch"] = "python"

        conda_index_file.write_text(
            json.dumps(index_dict, indent=2),
            encoding="utf8",
        )

    # Platform tag mapping is now handled by _WHEEL_PLATFORM_MAP and
    # CondaTargetInfo.from_wheel_metadata()

    def _write_files_list(self, conda_info_dir: Path, rel_files: Sequence[str]) -> None:
        # * info/files - list of relative paths of files not including info/
        conda_files_file = conda_info_dir.joinpath("files")
        with open(conda_files_file, "w", encoding="utf8") as f:
            for rel_file in rel_files:
                f.write(str(rel_file))
                f.write("\n")

    def _write_hash_input(self, conda_info_dir: Path) -> None:
        conda_hash_input_file = conda_info_dir.joinpath("hash_input.json")
        conda_hash_input_file.write_text(json.dumps({}, indent=2), encoding="utf8")

    def _write_about(self, conda_info_dir: Path, md: dict[str, Any]) -> None:
        """Write the info/about.json file"""
        # * info/about.json
        #
        # Note that the supported fields in the about section are not
        # well documented, but conda-build will only copy fields from
        # its approved list, which can be found in the FIELDS datastructure
        # in the conda_build.metadata module. This currently includes:
        #
        #   URLS: home, dev_url, doc_url, doc_source_url
        #   Text: license, summary, description, license_family
        #   Lists: tags, keyword
        #   Paths in source tree: license-file, prelink_message, readme
        #
        # conda-build also adds conda-build-version and conda-version fields.

        # TODO description can come from METADATA message body
        #   then need to also use content type. It doesn't seem
        #   that conda-forge packages include this in the info/

        conda_about_file = conda_info_dir.joinpath("about.json")

        extra = non_none_dict(
            author=md.get("author"),
            classifiers=md.get("classifier"),
            maintainer=md.get("maintainer"),
            whl2conda_version=__version__,
        )

        proj_url_pat = re.compile(r"\s*(?P<key>\w+(\s+\w+)*)\s*,\s*(?P<url>\w.*)\s*")
        doc_url: str | None = None
        dev_url: str | None = None
        for urlline in md.get("project-url", ()):
            if m := proj_url_pat.match(urlline):  # pragma: no branch
                key = m.group("key")
                url = m.group("url")
                if re.match(r"(?i)doc(umentation)?\b", key):
                    doc_url = url
                elif re.match(r"(?i)(dev(elopment)?|repo(sitory))\b", key):
                    dev_url = url
                extra[key] = url

        for key in ["author-email", "maintainer-email"]:
            val = md.get(key)
            if val:
                author_key = key.split("-", maxsplit=1)[0] + "s"
                extra[author_key] = val.split(",")

        license = md.get("license-expression") or md.get("license")
        if license_files := md.get("license-file"):
            extra["license_files"] = list(license_files)

        if keywords := md.get("keywords"):
            keyword_list = keywords.split(",")
        else:
            keyword_list = None

        conda_about_file.write_text(
            json.dumps(
                non_none_dict(
                    description=md.get("description"),
                    summary=md.get("summary"),
                    license=license or None,
                    keywords=keyword_list,
                    home=md.get("home-page"),
                    dev_url=dev_url,
                    doc_url=doc_url,
                    extra=extra,
                ),
                indent=2,
                sort_keys=True,
            ),
            encoding="utf8",
        )

    def _compute_conda_dependencies(
        self,
        dependencies: Sequence[RequiresDistEntry],
        marker_env: dict[str, str] | None = None,
    ) -> list[str]:
        conda_dependencies: list[str] = []

        saw_python = False

        for entry in dependencies:
            if entry.extra_marker_name:
                self._debug("Skipping extra dependency: %s", entry)
                continue
            if not entry.generic:
                if marker_env:
                    # Evaluate marker against target platform
                    if not _evaluate_marker(entry.marker, marker_env):
                        self._debug(
                            "Skipping dependency (marker not satisfied): %s", entry
                        )
                        continue
                    self._debug(
                        "Including marker dependency for target platform: %s", entry
                    )
                else:
                    # TODO - support non-generic packages
                    self._warn("Skipping dependency with environment marker: %s", entry)
                    continue

            conda_name = pip_name = entry.name
            version = self.translate_version_spec(entry.version)
            if saw_python := conda_name == "python":
                if self.python_version and version != self.python_version:
                    self._info(
                        "Overriding python version '%s' with '%s'",
                        version,
                        self.python_version,
                    )
                    version = self.python_version

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

        if not saw_python and self.python_version:
            self._info("Added 'python %s' dependency", self.python_version)
            conda_dependencies.append(f"python {self.python_version}")

        for dep in self.extra_dependencies:
            self._debug("Dependency added:  '%s'", dep)
            conda_dependencies.append(dep)
        return conda_dependencies

    def _add_binary_dependencies(
        self,
        conda_dependencies: list[str],
        conda_target: CondaTargetInfo,
        platform_tag: str,
    ) -> list[str]:
        """Add binary-specific dependencies (python pin, OS constraint).

        Replaces any loose python version spec with a tight pin derived from
        the wheel's Python tag, and adds OS minimum version constraints.
        """
        python_pin = _python_pin_from_version(conda_target.python_version)
        if python_pin:
            # Remove any existing loose python dependency
            result = [
                dep for dep in conda_dependencies if not dep.startswith("python ")
            ]
            result.extend(python_pin)
            self._debug(
                "Binary python pin: %s",
                ", ".join(python_pin),
            )
        else:
            result = list(conda_dependencies)

        if os_constraint := _os_constraint_from_platform_tag(platform_tag):
            result.append(os_constraint)
            self._debug("OS constraint: %s", os_constraint)

        return result

    # Known package prefixes that are unlikely to work as binary conversions
    # due to bundled GPU libraries, complex runtime dependencies, etc.
    def _check_binary_conversion(self, wheel_md: MetadataFromWheel) -> None:
        """Check for conditions that make binary conversion unlikely to succeed.

        Raises:
            Wheel2CondaError: if conversion is blocked due to known-bad patterns
        """
        version = wheel_md.version

        # Check for local version suffix (e.g. +cu121, +rocm5.6)
        if "+" in version:
            local = version.split("+", 1)[1]
            raise Wheel2CondaError(
                f"Wheel {self.wheel_path.name} has local version suffix '+{local}' "
                f"indicating a custom build variant (e.g. CUDA). "
                f"Such wheels bundle variant-specific libraries that are unlikely "
                f"to work correctly as conda packages. Use conda-forge packages instead."
            )

    def _copy_wheel_files(self, wheel_dir: Path, conda_dir: Path) -> None:
        """
        Copies files from wheels to corresponding location in conda package:

        For noarch packages:
        - <wheel-dir>/*.data/data/* -> <conda-dir>/*
        - <wheel-dir>/*.data/scripts/* -> <conda-dir>/python-scripts/*
        - <wheel-dir>/*.data/* -> ignored
        - <wheel-dir>/* -> <conda-dir>/site-packages

        For platform-specific packages:
        - <wheel-dir>/* -> <conda-dir>/lib/pythonX.Y/site-packages (Unix)
        - <wheel-dir>/* -> <conda-dir>/Lib/site-packages (Windows)
        - <wheel-dir>/*.data/scripts/* -> <conda-dir>/bin (Unix)
        - <wheel-dir>/*.data/scripts/* -> <conda-dir>/Scripts (Windows)
        """
        assert self.conda_target is not None
        target = self.conda_target

        conda_site_packages = conda_dir.joinpath(target.site_packages_prefix)
        conda_site_packages.mkdir(parents=True)
        conda_info_dir = conda_dir.joinpath("info")
        conda_info_dir.mkdir()

        if target.is_noarch:
            scripts_dest = "python-scripts"
        elif target.platform == "win":
            scripts_dest = "Scripts"
        else:
            scripts_dest = "bin"

        for entry in wheel_dir.iterdir():
            if not entry.is_dir():
                shutil.copyfile(entry, conda_site_packages / entry.name)
            elif not entry.name.endswith(".data"):
                shutil.copytree(
                    entry, conda_site_packages / entry.name, dirs_exist_ok=True
                )
            else:
                for datapath in entry.iterdir():
                    if not datapath.is_dir():
                        self._warn(
                            "Do not support top level file '%s' in '%s' directory - ignored",
                            datapath.name,
                            entry.relative_to(wheel_dir),
                        )
                        continue
                    if datapath.name == "data":
                        data_dest = conda_dir
                    elif datapath.name == "scripts":
                        data_dest = conda_dir / scripts_dest
                    else:
                        self._warn(
                            "Do not support '%s' path in '%s' directory - ignored",
                            datapath.name,
                            entry.relative_to(wheel_dir),
                        )
                        continue
                    shutil.copytree(datapath, data_dest, dirs_exist_ok=True)

        assert self.wheel_md is not None
        dist_info_dir = conda_site_packages / self.wheel_md.wheel_info_dir.name
        installer_file = dist_info_dir / "INSTALLER"
        installer_file.write_text("whl2conda", encoding="utf8")
        requested_file = dist_info_dir / "REQUESTED"
        requested_file.write_text("", encoding="utf8")

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
                for from_file in filter(  # pragma: no branch
                    lambda f: f.exists(), from_files
                ):
                    to_file = to_license_dir / from_file.relative_to(wheel_info_dir)
                    if not to_file.exists():  # pragma: no branch
                        to_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(from_file, to_file)
                        break

    def _parse_wheel_metadata(self, wheel_dir: Path) -> MetadataFromWheel:
        """Parse all metadata from an extracted wheel directory."""
        wheel_info_dir = next(wheel_dir.glob("*.dist-info"))
        is_pure_lib, wheel_build_number, python_tag, abi_tag, platform_tag = (
            self._parse_wheel_info(wheel_info_dir)
        )
        md, requires = self._parse_dist_metadata(wheel_info_dir)

        package_name = self.package_name or str(md.get("name"))
        # Conda package names are lowercase with hyphens
        package_name = re.sub(r"[-_.]+", "-", package_name).lower()
        self.package_name = package_name
        version = md.get("version")

        # RECORD_file = wheel_info_dir / "RECORD"
        # TODO: strip __pycache__ entries from RECORD
        # TODO: add INSTALLER and REQUESTED to RECORD
        # TODO: add direct_url to wheel and to RECORD
        # RECORD line format: <path>,sha256=<hash>,<len>

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
            is_pure_python=is_pure_lib,
            python_tag=python_tag,
            abi_tag=abi_tag,
            platform_tag=platform_tag,
        )
        return self.wheel_md

    def _parse_wheel_info(
        self, wheel_info_dir: Path
    ) -> tuple[bool, str, str, str, str]:
        """Parse the WHEEL metadata file.

        Returns:
            Tuple of (is_pure_lib, build_number, python_tag, abi_tag, platform_tag)
        """
        WHEEL_file = wheel_info_dir.joinpath("WHEEL")
        WHEEL_msg = self.read_metadata_file(WHEEL_file)
        # https://peps.python.org/pep-0427/#what-s-the-deal-with-purelib-vs-platlib

        is_pure_lib = WHEEL_msg.get("Root-Is-Purelib", "").lower() == "true"
        wheel_build_number = WHEEL_msg.get("Build", "")
        wheel_version = WHEEL_msg.get("Wheel-Version")
        # Tag entry can appear more than once (e.g. py2-none-any, py3-none-any)
        all_tags = WHEEL_msg.get_all("Tag") or ["py3-none-any"]

        if wheel_version not in self.SUPPORTED_WHEEL_VERSIONS:
            raise Wheel2CondaError(
                f"Wheel {self.wheel_path} has unsupported wheel version {wheel_version}"
            )

        # Pick the best tag: prefer py3 over py2
        wheel_tag = all_tags[0]
        for tag in all_tags:
            if tag.lower().startswith("py3"):
                wheel_tag = tag
                break

        if not self.allow_impure:
            if not is_pure_lib:
                raise Wheel2CondaError(f"Wheel {self.wheel_path} is not pure python")
            if not any(t.lower() == "py3-none-any" for t in all_tags):
                raise Wheel2CondaError(
                    f"Wheel {self.wheel_path} has unexpected tag '{wheel_tag}' for pure python"
                )

        wheel_tags = wheel_tag.split("-")
        if len(wheel_tags) != 3:
            raise Wheel2CondaError(
                f"Wheel {self.wheel_path} has bad tag format '{wheel_tags}'"
            )

        python_tag, abi_tag, platform_tag = wheel_tags
        return is_pure_lib, wheel_build_number, python_tag, abi_tag, platform_tag

    def _parse_dist_metadata(
        self, wheel_info_dir: Path
    ) -> tuple[dict[str, Any], list[RequiresDistEntry]]:
        """Parse the METADATA file and optionally rewrite pip dependencies.

        Returns:
            Tuple of (metadata_dict, requires_list)
        """
        wheel_md_file = wheel_info_dir.joinpath("METADATA")
        md: dict[str, str | list[Any]] = {}
        # Metadata spec: https://packaging.python.org/en/latest/specifications/core-metadata/
        # Required keys: Metadata-Version, Name, Version
        md_msg = self.read_metadata_file(wheel_md_file)
        md_version_str = md_msg.get("Metadata-Version")
        if md_version_str not in self.SUPPORTED_METADATA_VERSIONS:
            msg = f"Wheel {self.wheel_path} has unsupported metadata version {md_version_str}"
            # TODO - perhaps just warn about this if not in "strict" mode
            raise Wheel2CondaError(msg)
        for mdkey, mdval in md_msg.items():
            mdkey = mdkey.strip()
            if mdkey in self.MULTI_USE_METADATA_KEYS:
                if curmdval := md.get(mdkey):
                    if isinstance(curmdval, str):
                        md[mdkey] = [curmdval]
                md.setdefault(mdkey.lower(), []).append(mdval)  # type: ignore
            else:
                md[mdkey.lower()] = mdval

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
                    entry = entry.with_extra('original')
                md_msg.add_header("Requires-Dist", str(entry))
            md_msg.add_header("Provides-Extra", "original")
            wheel_md_file.write_text(md_msg.as_string(), encoding="utf8")

        return md, requires

    def translate_version_spec(self, pip_version: str) -> str:
        """
        Convert a pip version spec to a conda version spec.

        Compatible release specs using the `~=` operator will be turned
        into two clauses using ">=" and "==", for example
        `~=1.2.3` will become `>=1.2.3,1.2.*`.

        Arbitrary equality clauses using the `===` operator will be
        converted to use `==`, but such clauses are likely to fail
        so a warning will be produced.

        Any leading "v" character in the version will be dropped.
        (e.g. `v1.2.3` changes to `1.2.3`).
        """
        pip_version = pip_version.strip()
        version_specs = re.split(r"\s*,\s*", pip_version)
        for i, spec in enumerate(version_specs):
            if not spec:
                continue
            # spec for '~= <version>'
            # https://packaging.python.org/en/latest/specifications/version-specifiers/#compatible-release
            if m := pip_version_re.match(spec):
                operator = m.group("operator")
                v = m.group("version")
                v = v.removeprefix("v")
                if operator == "~=":
                    # compatible operator, e.g. convert ~=1.2.3 to >=1.2.3,==1.2.*
                    rv = m.group("release")
                    rv_parts = rv.split(".")
                    operator = ">="
                    if len(rv_parts) > 1:
                        # technically ~=1 is not valid, but if we see it, turn it into >=1
                        v += f",=={'.'.join(rv_parts[:-1])}.*"
                elif operator == "===":
                    operator = "=="
                    # TODO perhaps treat as an error in "strict" mode
                    self._warn(
                        "Converted arbitrary equality clause %s to ==%s - may not match!",
                        spec,
                        v,
                    )
                version_specs[i] = f"{operator}{v}"
            else:
                self._warn("Cannot convert bad version spec: '%s'", spec)

        return ",".join(filter(bool, version_specs))

    def _extract_wheel(self, temp_dir: Path) -> Path:
        self.logger.info("Reading %s", self.wheel_path)
        wheel_dir = temp_dir / "wheel-files"
        unpack_wheel(self.wheel_path, wheel_dir, logger=self.logger)
        return wheel_dir

    def _warn(self, msg, *args):
        self.logger.warning(msg, *args)

    def _info(self, msg, *args):
        self.logger.info(msg, *args)

    def _debug(self, msg, *args):
        self.logger.debug(msg, *args)
