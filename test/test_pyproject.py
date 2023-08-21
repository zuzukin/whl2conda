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
Unit tests for whl2conda.pyproject module
"""

from __future__ import annotations

from pathlib import Path

import pytest

from whl2conda.pyproject import CondaPackageFormat, read_pyproject


def test_conda_package_format():
    """Unit tests for CondaPackageFormat"""
    for val in CondaPackageFormat:
        assert CondaPackageFormat.from_string(val.name) is val
        assert CondaPackageFormat.from_string(val.name.lower()) is val
        assert CondaPackageFormat.from_string(val.value) is val
        assert CondaPackageFormat.from_string(val.value.upper()) is val

    with pytest.raises(ValueError):
        CondaPackageFormat.from_string("invalid")


def test_read_pyproject(tmp_path: Path) -> None:
    """Unit test for read_pyproject function"""
    proj_file = tmp_path.joinpath("pyproject.toml")
    with pytest.raises(FileNotFoundError):
        read_pyproject(proj_file)
