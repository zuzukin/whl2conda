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
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator, List, Sequence

# third party
import pytest

# this project
import whl2conda.prompt
from whl2conda.__about__ import __version__
from whl2conda.converter import CondaPackageFormat, Wheel2CondaConverter
from whl2conda.cli import main
from whl2conda.prompt import is_interactive

this_dir = Path(__file__).parent
project_dir = this_dir.joinpath("projects")


@dataclass
class CliTestCase:
    """A CLI test case runner"""

    caplog: pytest.LogCaptureFixture
    capsys: pytest.CaptureFixture
    monkeypatch: pytest.MonkeyPatch

    args: Sequence[str]
    interactive: bool = field(default_factory=is_interactive)
    expected_dry_run: bool = False
    expected_package_name: str = ""
    expected_out_fmt: CondaPackageFormat = CondaPackageFormat.V2
    expected_overwrite: bool = False
    expected_keep_pip: bool = False
    expected_extra_dependencies: Sequence[str] = ()
    expected_interactive: bool = True
    expected_prompts: List[str] = field(default_factory=list)
    responses: List[str] = field(default_factory=list)

    def run(self) -> None:
        """Run the test"""

        expected_out = iter(self.expected_prompts)
        responses = iter(self.responses)

        def fake_input(prompt: str) -> str:
            expected_prompt = next(expected_out)
            assert re.search(expected_prompt, prompt)
            return next(responses)

        self.monkeypatch.setattr(Wheel2CondaConverter, "convert", lambda: None)
        self.monkeypatch.setattr("builtins.input", fake_input)
        if self.interactive is not is_interactive():
            # TODO - this isn't working. Figure out way to force interactive in tests
            self.monkeypatch.setattr(whl2conda.prompt, "is_interactive", lambda: self.interactive)

        main(self.args, "whl2conda")

    def add_prompt(self, expected_prompt: str, response: str) -> None:
        """Add a prompt/response pair"""
        self.expected_prompts.append(expected_prompt)
        self.responses.append(response)


class CliTestCaseFactory:
    """Factory for CLI test case runners"""

    capsys: pytest.CaptureFixture
    monkeypatch: pytest.MonkeyPatch

    def __init__(
        self,
        *,
        caplog: pytest.LogCaptureFixture,
        capsys: pytest.CaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ):
        self.caplog = caplog
        self.capsys = capsys
        self.monkeypatch = monkeypatch

    def __call__(self, args: Sequence[str], **kwargs) -> CliTestCase:
        return CliTestCase(
            caplog=self.caplog,
            capsys=self.capsys,
            monkeypatch=self.monkeypatch,
            args=args,
            **kwargs,
        )


@pytest.fixture
def test_case(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[CliTestCaseFactory, None, None]:
    """Yields test CLI case factory"""
    yield CliTestCaseFactory(
        caplog=caplog,
        capsys=capsys,
        monkeypatch=monkeypatch,
    )


def test_help(
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unit test for --help flag"""
    with pytest.raises(SystemExit):
        main(["--help"], "whl2conda2")
    out, err = capsys.readouterr()
    assert not err
    assert "usage: whl2conda2" in out
    assert "--markdown-help" not in out

    monkeypatch.setattr("sys.argv", ["whl2conda3", "--help"])
    with pytest.raises(SystemExit):
        main()
    out, err = capsys.readouterr()
    assert not err
    assert "usage: whl2conda3" in out

    with pytest.raises(SystemExit):
        main(["--markdown-help"])
    out, err = capsys.readouterr()
    assert not err
    assert "### Usage" in out
    assert "usage: whl2conda3" in out


def test_version(capsys: pytest.CaptureFixture):
    """Unit test for --version flag"""
    with pytest.raises(SystemExit):
        main(["--version"])
    out, err = capsys.readouterr()
    assert not err
    assert out.strip() == __version__


# def test_simple(test_case):
#     test_case.monkeypatch.chdir(project_dir)
#     case = test_case(
#         ["simple"],
#         interactive = True
#     )
#     case.run()
