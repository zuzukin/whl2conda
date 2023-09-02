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
Custom configuration for pytest

Don't run tests marked with @pytest.mark.external unless --run-external
is given.
"""

# content of conftest.py

import pytest


def pytest_addoption(parser):
    """
    Add option to pytest CLI
    """
    parser.addoption(
        "--run-external", action="store_true", default=False, help="run external tests"
    )
    parser.addoption(
        "--run-slow", action="store_true", default=False, help="run slow tests"
    )


def pytest_configure(config):
    """
    Add external marker to pytest configuration
    """
    config.addinivalue_line(
        "markers", "external: mark test as depending on extenral pypi package to run"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow to run"
    )


def pytest_collection_modifyitems(config, items):
    """
    Skip external/slow tests unless --run-external/--run-slow
    """
    if not config.getoption("--run-external"):
        # --run-external not given in cli
        skip_external = pytest.mark.skip(reason="need --run-external option to run")
        for item in items:
            if "external" in item.keywords:
                item.add_marker(skip_external)

    if not config.getoption("--run-slow"):
        # --run-slow not given in cli
        skip_slow = pytest.mark.skip(reason="need --run-slow option to run")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)
