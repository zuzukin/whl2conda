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
Interactive prompt utilities.
"""

from __future__ import annotations

import enum
import io
import sys
from pathlib import Path

__all__ = [
    "WheelChoice",
    "bool_input",
    "choose_wheel",
    "is_interactive",
]


def is_interactive() -> bool:
    """
    True if input appears to be connected to an interactive terminal
    """
    if stdin := sys.__stdin__:
        return stdin.isatty()
    return False


def bool_input(prompt: str) -> bool:
    """Boolean interactive prompt, accepts y/n, yes/no, true/false"""
    true_vals = {"y", "yes", "true"}
    false_vals = {"n", "no", "false"}
    while True:
        answer = input(prompt).lower()
        if answer in true_vals:
            return True
        if answer in false_vals:
            return False


class WheelChoice(enum.Enum):
    """Non-file result of [choose_wheel][(m).]: build the wheel instead."""

    BUILD = "build"
    BUILD_NO_DEPS = "build-no-dep"


def choose_wheel(
    wheel_dir: Path,
    *,
    interactive: bool = False,
    choose_first: bool = False,
    can_build: bool = False,
) -> Path | WheelChoice:
    """
    Choose wheel from available wheels in distribution directory.

    Args:
        wheel_dir: directory containing .whl files
        interactive: if true, prompt user for choice
        choose_first: choose first available wheel (the most recent one)
            implies not interactive
        can_build: show build options when interactive

    Returns:
        Path of the chosen wheel, or a [WheelChoice][(m).] build action.

    Raises:
        FileNotFoundError: no wheels in directory and not interactive
            or choose_first
        FileExistsError: more than one wheel in directory when non-interactive
    """
    if choose_first:
        interactive = False

    wheels = sorted(
        wheel_dir.glob("*.whl"),
        key=lambda p: p.stat().st_ctime,
        reverse=True,
    )

    if not wheels and not (interactive and can_build):
        raise FileNotFoundError(f"No wheels found in directory '{wheel_dir}'")
    if not interactive:
        if choose_first or len(wheels) == 1:
            return wheels[0]
        raise FileExistsError(
            f"Cannot choose from multiple wheels in directory '{wheel_dir}'"
        )

    # key -> (label, chosen wheel or build action or None for quit)
    options: dict[str, tuple[str, Path | WheelChoice | None]] = {
        str(i): (wheel.name, wheel) for i, wheel in enumerate(wheels)
    }
    if can_build:
        options['build'] = ('build wheel', WheelChoice.BUILD)
        options['no-dep'] = (
            'build wheel with --no-deps --no-build-isolation',
            WheelChoice.BUILD_NO_DEPS,
        )
    options['quit'] = ("quit program", None)

    while True:
        with io.StringIO() as out:
            for k, (label, _choice) in options.items():
                key = f"[{k}]"
                print(f"{key:>8s} {label}", file=out)
            print(f"Choose wheel ({','.join(options)}): ")
            prompt = out.getvalue()
        option = input(prompt)
        if t := options.get(option):
            choice = t[1]
            if choice is None:
                sys.exit(2)
            return choice
