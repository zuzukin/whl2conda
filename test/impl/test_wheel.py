#  Copyright 2024 Christopher Barber
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
Unit tests for the whl2conda.impl.wheel module
"""
import platform
import stat
from pathlib import Path

import pytest

from whl2conda.impl.wheel import unpack_wheel

from ..test_packages import setup_wheel

def test_unpack_wheel(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    setup_wheel: Path,
) -> None:
    """
    Unit test for unpack_wheel
    """

    unpack_wheel(setup_wheel, tmp_path)

    if not platform.system() == "Windows":
        # Regression case for #135
        script_paths = list(tmp_path.rglob("**/scripts/*.py"))
        assert script_paths
        for script_path in script_paths:
            assert script_path.stat().st_mode & stat.S_IXUSR
