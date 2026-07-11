#  Copyright 2026 Christopher Barber
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
Test a conda package in a fresh conda environment.

Provides a normalized test specification, which can be read from either
a classic conda recipe `test:` section or a v1 recipe `tests:` list, and
a runner that installs the package into a new environment (using the
`whl2conda install` machinery) and runs the specified imports and
commands.
"""

from __future__ import annotations

# standard
import logging
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import chain
from pathlib import Path
from typing import Any

# this project
from .install import install_main

__all__ = [
    "PackageTestError",
    "PackageTestSpec",
    "run_package_tests",
]

logger = logging.getLogger(__name__)


class PackageTestError(RuntimeError):
    """A package test could not be run or failed."""


@dataclass(slots=True)
class PackageTestSpec:
    """Normalized specification of conda package tests."""

    requires: list[str] = field(default_factory=list)
    """Additional conda dependencies for the test environment."""

    imports: list[str] = field(default_factory=list)
    """Python modules that must import successfully."""

    commands: list[str] = field(default_factory=list)
    """Shell commands that must succeed, run in the test working dir."""

    source_files: list[str] = field(default_factory=list)
    """Files/globs copied from the source root into the test working dir."""

    pip_check: bool = False
    """Whether to run `python -m pip check` in the test environment."""

    def __bool__(self) -> bool:
        return bool(self.imports or self.commands or self.pip_check)

    @classmethod
    def from_meta_yaml(cls, test_section: Mapping[str, Any]) -> PackageTestSpec:
        """Create spec from a rendered meta.yaml `test:` section."""
        return cls(
            requires=list(test_section.get("requires") or ()),
            imports=list(test_section.get("imports") or ()),
            commands=list(test_section.get("commands") or ()),
            source_files=list(test_section.get("source_files") or ()),
        )

    @classmethod
    def from_v1_tests(cls, tests: Sequence[Mapping[str, Any]]) -> PackageTestSpec:
        """Create spec from a v1 recipe `tests:` list.

        The v1 format runs each test element in its own environment;
        this flattens all elements into a single specification run in
        one shared test environment.
        """
        spec = cls()
        for test in tests:
            if python_test := test.get("python"):
                spec.imports.extend(python_test.get("imports") or ())
                if python_test.get("pip_check", True):
                    spec.pip_check = True
            elif "script" in test:
                script = test["script"]
                if isinstance(script, (str, Mapping)):
                    script = [script]
                spec.commands.extend(
                    line["content"] if isinstance(line, Mapping) else str(line)
                    for line in script
                )
                requirements = test.get("requirements") or {}
                spec.requires.extend(requirements.get("run") or ())
                files = test.get("files") or {}
                if isinstance(files, Mapping):
                    spec.source_files.extend(files.get("source") or ())
                else:
                    spec.source_files.extend(files)
            else:
                kind = ", ".join(test.keys()) or "empty"
                logger.warning("Ignoring unsupported v1 test element: %s", kind)
        if spec.pip_check:
            spec.requires.append("pip")
        return spec


def run_package_tests(
    package: Path,
    spec: PackageTestSpec,
    *,
    env_prefix: Path,
    work_dir: Path,
    source_root: Path | None = None,
    channels: Sequence[str] = (),
    keep_env: bool = False,
) -> None:
    """Install a conda package into a fresh environment and test it.

    Args:
        package: conda package file to test
        spec: the tests to run
        env_prefix: path at which the test environment is created
        work_dir: working directory in which commands are run; created
            if necessary, and `spec.source_files` are copied into it
        source_root: directory from which `spec.source_files` are
            resolved; defaults to the current directory
        channels: additional conda channels for the test environment
        keep_env: do not remove the test environment afterwards

    Raises:
        PackageTestError: if a test fails or cannot be run.
    """
    try:
        install_cmd = [
            str(package),
            "--create",
            "-p",
            str(env_prefix),
            "--yes",
            "--extra",
            # NOTE: the remaining arguments pass through to conda create
            *chain.from_iterable(("-c", channel) for channel in channels),
            *spec.requires,
        ]
        install_main(install_cmd)

        work_dir.mkdir(parents=True, exist_ok=True)
        _copy_source_files(spec.source_files, source_root or Path.cwd(), work_dir)

        for import_name in spec.imports:
            _run_test(
                [
                    "conda",
                    "run",
                    "-p",
                    str(env_prefix),
                    "python",
                    "-c",
                    f"import {import_name}",
                ],
                work_dir,
                f"import of '{import_name}'",
            )

        if spec.pip_check:
            _run_test(
                [
                    "conda",
                    "run",
                    "-p",
                    str(env_prefix),
                    "python",
                    "-m",
                    "pip",
                    "check",
                ],
                work_dir,
                "pip check",
            )

        for command in spec.commands:
            _run_test(
                f"conda run -p {env_prefix!s} {command}",
                work_dir,
                f"command '{command}'",
                shell=True,
            )
    finally:
        if keep_env:
            logger.info("Keeping test environment at %s", env_prefix)
        else:
            shutil.rmtree(env_prefix, ignore_errors=True)


def _copy_source_files(
    patterns: Sequence[str], source_root: Path, work_dir: Path
) -> None:
    """Copy test source file globs into the test working directory."""
    for pattern in patterns:
        matches = sorted(source_root.glob(pattern))
        if not matches:
            raise PackageTestError(
                f"Test source files '{pattern}' not found in {source_root}"
            )
        for match in matches:
            target = work_dir / match.relative_to(source_root)
            if match.is_dir():
                shutil.copytree(match, target, dirs_exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(match, target)


def _run_test(
    cmd: str | list[str],
    work_dir: Path,
    description: str,
    *,
    shell: bool = False,
) -> None:
    try:
        subprocess.check_call(cmd, shell=shell, cwd=work_dir)
    except subprocess.CalledProcessError as ex:
        raise PackageTestError(f"Package test {description} failed: {ex}") from ex
