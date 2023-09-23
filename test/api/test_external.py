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
External pypi converter tests
"""

from __future__ import annotations

import subprocess

import pytest

from whl2conda.api.converter import Wheel2CondaError

from .converter import ConverterTestCaseFactory
from .converter import test_case  # pylint: disable=unused-import


# pylint: disable=redefined-outer-name

#
# External pypi tests
#


@pytest.mark.external
def test_pypi_tomlkit(test_case: ConverterTestCaseFactory):
    """
    Test tomlkit package from pypi
    """
    test_case("pypi:tomlkit").build()


@pytest.mark.external
def test_pypi_sphinx(test_case: ConverterTestCaseFactory):
    """
    Test sphinx package from pypi
    """
    test_case("pypi:sphinx").build()


@pytest.mark.external
def test_pypi_zstandard(test_case: ConverterTestCaseFactory):
    """
    Test zstandard package - not pure python
    """
    with pytest.raises(Wheel2CondaError, match="not pure python"):
        test_case("pypi:zstandard").build()


@pytest.mark.external
def test_pypi_colorama(test_case: ConverterTestCaseFactory):
    """
    Test colorama package
    """
    test_case(
        "pypi:colorama",
    ).build()


@pytest.mark.external
def test_pypi_orix(test_case: ConverterTestCaseFactory) -> None:
    """
    Test orix package
    """
    case = test_case("pypi:orix")
    orix_pkg = case.build()
    assert orix_pkg.is_file()

    test_env = case.install(orix_pkg)

    subprocess.check_call(["conda", "install", "-p", str(test_env), "pytest", "--yes"])

    subprocess.check_call(
        [
            "conda",
            "run",
            "-p",
            str(test_env),
            "pytest",
            "--pyargs",
            "orix.tests",
            "-k",
            "not test_restrict_to_fundamental_sector",
        ]
    )
