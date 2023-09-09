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
Conda test utilities
"""

from __future__ import annotations

import json
import re
from subprocess import check_output
from typing import Any

__all__ = ["conda_config", "conda_json", "conda_output"]


def conda_config() -> dict[str, Any]:
    """Return conda configuration dictionary"""
    return conda_json("config", "--show")


def conda_output(*args: str) -> str:
    """Capture output from conda command"""
    return check_output(["conda"] + list(args), encoding="utf8")


def conda_json(*args: str) -> Any:
    """Run conda with --json and return parsed dictionary"""
    _args = list(args) + ["--json"]
    content = conda_output(*_args)
    return json.loads(content)


def test_conda_output() -> None:
    """Basic test for conda_output"""
    assert re.search(r"\d+\.\d+\.\d+", conda_output("--version"))


def test_conda_json() -> None:
    """Basic test for conda_json"""
    info = conda_json("info")
    assert isinstance(info, dict)
    assert info.get("conda_version")


def test_conda_config() -> None:
    """Basic test for conda_config"""
    config = conda_config()
    assert config.get("croot")
