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
Unit tests for whl2conda command line interface
"""

# standard
from dataclasses import dataclass
from typing import Generator, Sequence

# third party
import pytest

# this project
from whl2conda.converter import CondaPackageFormat
from whl2conda.cli import main


@dataclass
class CliTestCase:
    """A CLI test case runner"""

    capsys: pytest.CaptureFixture
    monkeypatch: pytest.MonkeyPatch

    args: Sequence[str]
    expected_dry_run: bool = False
    expected_package_name: str = ""
    expected_out_fmt: CondaPackageFormat = CondaPackageFormat.V2
    expected_overwrite: bool = False
    expected_keep_pip: bool = False
    expected_extra_dependencies: Sequence[str] = ()
    expected_interactive: bool = True

    def run(self) -> None:
        """Run the test"""
        main(self.args, "whl2conda")


class CliTestCaseFactory:
    """Factory for CLI test case runners"""

    capsys: pytest.CaptureFixture
    monkeypatch: pytest.MonkeyPatch

    def __init__(self, *, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch):
        self.capsys = capsys
        self.monkeypatch = monkeypatch

    def __call__(self, args: Sequence[str], **kwargs) -> CliTestCase:
        return CliTestCase(capsys=self.capsys, monkeypatch=self.monkeypatch, args=args, **kwargs)


@pytest.fixture
def test_case(
    capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> Generator[CliTestCaseFactory, None, None]:
    """Yields test CLI case factory"""
    yield CliTestCaseFactory(capsys=capsys, monkeypatch=monkeypatch)


# def test_foo(test_case):
#     test_case(
#         ["--version"]
#     ).run()
