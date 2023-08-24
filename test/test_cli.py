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

from __future__ import annotations

# standard
import re
import shutil
from pathlib import Path
from typing import Any, Generator, List, Optional, Sequence, Tuple

# third party
import pytest

# this project
from whl2conda.__about__ import __version__
from whl2conda.converter import CondaPackageFormat, Wheel2CondaConverter
from whl2conda.cli import main
from whl2conda.prompt import is_interactive

from .test_prompt import monkeypatch_interactive

this_dir = Path(__file__).parent
project_dir = this_dir.joinpath("projects")

# pylint: disable=redefined-outer-name


class CliTestCase:
    """A CLI test case runner"""

    #
    # pytest fixtures
    #

    caplog: pytest.LogCaptureFixture
    capsys: pytest.CaptureFixture
    monkeypatch: pytest.MonkeyPatch
    tmp_path: Path

    #
    # Expected values
    #

    args: Sequence[str]
    interactive: bool
    expected_dry_run: bool = False
    expected_package_name: str = ""
    expected_out_fmt: CondaPackageFormat = CondaPackageFormat.V2
    expected_overwrite: bool = False
    expected_keep_pip: bool = False
    exoected_dependency_rename: Sequence[Tuple[str, str]] = ()
    expected_extra_dependencies: Sequence[str] = ()
    expected_interactive: bool = True
    expected_project_root: str = ""
    """Relative path from projects dir"""
    expected_parser_error: str = ""

    expected_prompts: List[str]
    responses: List[str]

    #
    # Other test state
    #

    project_dir: Path

    # pylint: disable=too-many-locals
    def __init__(
        self,
        args: Sequence[str],
        *,
        # required
        caplog: pytest.LogCaptureFixture,
        capsys: pytest.CaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        # optional
        interactive: Optional[bool] = None,
        expected_dry_run: bool = False,
        expected_package_name: str = "",
        expected_parser_error: str = "",
        expected_out_fmt: CondaPackageFormat = CondaPackageFormat.V2,
        expected_overwrite: bool = False,
        expected_keep_pip: bool = False,
        expected_extra_dependencies: Sequence[str] = (),
        expected_interactive: bool = True,
        expected_project_root: str = "",
    ):
        self.caplog = caplog
        self.capsys = capsys
        self.monkeypatch = monkeypatch
        self.tmp_path = tmp_path

        self.args = args
        self.interactive = is_interactive() if interactive is None else interactive
        self.expected_dry_run = expected_dry_run
        self.expected_parser_error = expected_parser_error
        self.expected_package_name = expected_package_name
        self.expected_out_fmt = expected_out_fmt
        self.expected_overwrite = expected_overwrite
        self.expected_keep_pip = expected_keep_pip
        self.expected_extra_dependencies = list(expected_extra_dependencies)
        self.expected_interactive = expected_interactive
        self.expected_project_root = expected_project_root
        self.expected_prompts = []
        self.responses = []

        self.project_dir = tmp_path.joinpath("projects")
        shutil.copytree(project_dir, self.project_dir)

    def run(self) -> None:
        """Run the test"""

        prompts = iter(self.expected_prompts)
        responses = iter(self.responses)

        # pylint: disable=unused-argument
        def fake_build_wheel(
            project_root: Path,
            wheel_dir: Path,
            *,
            no_deps: bool = False,
            dry_run: bool = False,
        ) -> Path:
            return wheel_dir.joinpath("fake-1.0-py3-none-any.whl")

        def fake_input(prompt: str) -> str:
            expected_prompt = next(prompts)
            assert re.search(
                expected_prompt, prompt
            ), f"'{expected_prompt}' does not match prompt '{prompt}'"
            return next(responses)

        def fake_convert(converter: Wheel2CondaConverter) -> Path:
            self.validate_converter(converter)

            wheel_name = converter.wheel_path.name
            # parse package name and version from wheel filename
            m = re.fullmatch(r"([^-]+)-([^-]+)(-.*)?\.whl", wheel_name)
            assert m is not None
            default_package_name = re.sub("_", "-", m.group(1))
            version = m.group(2)
            package_name = converter.package_name or default_package_name
            # pylint: disable=protected-access
            conda_pkg_path = converter._conda_package_path(package_name, version)
            if not conda_pkg_path.is_file() and not converter.dry_run:
                # just write an empty file so that existence check will work
                conda_pkg_path.parent.mkdir(parents=True, exist_ok=True)
                conda_pkg_path.write_text("")
            return conda_pkg_path

        with self.monkeypatch.context() as mp:
            mp.setattr(Wheel2CondaConverter, "convert", fake_convert)
            mp.setattr("builtins.input", fake_input)
            mp.setattr("whl2conda.cli.do_build_wheel", fake_build_wheel)
            if self.interactive is not is_interactive():
                monkeypatch_interactive(mp, self.interactive)
            mp.chdir(self.project_dir)

            self.capsys.readouterr()

            # Run the command
            exit_code: Any = None
            try:
                main(self.args, "whl2conda")
            except SystemExit as exit_err:
                exit_code = exit_err.code

            _out, err = self.capsys.readouterr()

            if self.expected_parser_error:
                if exit_code is None:
                    pytest.fail(f"No parser error, but expected '{self.expected_parser_error}'")
                assert re.search(self.expected_parser_error, err)
            else:
                assert err == ""
                assert exit_code is None

            assert not list(prompts)
            assert not list(responses)

    def add_prompt(self, expected_prompt: str, response: str) -> CliTestCase:
        """Add a prompt/response pair

        Return:
            this object, to enable method chaining
        """
        self.expected_prompts.append(expected_prompt)
        self.responses.append(response)
        return self

    def validate_converter(self, converter: Wheel2CondaConverter) -> None:
        """Validate converter settings"""
        assert converter.project_root == self.project_dir.joinpath(self.expected_project_root)
        assert converter.dry_run is self.expected_dry_run
        assert converter.package_name is self.expected_package_name
        assert converter.out_format is self.expected_out_fmt
        assert converter.overwrite is self.expected_overwrite
        assert converter.keep_pip_dependencies is self.expected_keep_pip
        assert converter.extra_dependencies == list(self.expected_extra_dependencies)
        assert converter.dependency_rename == list(self.exoected_dependency_rename)


class CliTestCaseFactory:
    """Factory for CLI test case runners"""

    capsys: pytest.CaptureFixture
    monkeypatch: pytest.MonkeyPatch
    tmp_path: Path

    def __init__(
        self,
        *,
        caplog: pytest.LogCaptureFixture,
        capsys: pytest.CaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        self.caplog = caplog
        self.capsys = capsys
        self.monkeypatch = monkeypatch
        self.tmp_path = tmp_path

    def __call__(self, args: Sequence[str], **kwargs) -> CliTestCase:
        return CliTestCase(
            caplog=self.caplog,
            capsys=self.capsys,
            monkeypatch=self.monkeypatch,
            tmp_path=self.tmp_path,
            args=args,
            **kwargs,
        )


@pytest.fixture
def test_case(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Generator[CliTestCaseFactory, None, None]:
    """Yields test CLI case factory"""
    yield CliTestCaseFactory(
        caplog=caplog, capsys=capsys, monkeypatch=monkeypatch, tmp_path=tmp_path
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


def test_simple_default(test_case: CliTestCaseFactory) -> None:
    """
    Interactive mode run on project dir with no options.
    """
    case = test_case(
        ["simple"],
        interactive=False,
        expected_project_root="simple",
        expected_parser_error="No wheels found in directory",
    )
    case.run()

    case.interactive = True
    case.expected_parser_error = ""
    case.add_prompt(
        r"\[build\] build wheel",
        "build",
    )
    case.run()


def test_parse_errors(test_case: CliTestCaseFactory) -> None:
    """
    Test cli parser errors
    """
    case = test_case(["does-not-exist"], expected_parser_error="'does-not-exist' does not exist")
    case.run()

    case.args = [str(Path(__file__).absolute())]
    case.expected_parser_error = "does not have .whl suffix"
    case.run()

    case.args = ["simple", "--project-root", "simple"]
    case.expected_parser_error = "project root as both positional and keyword"
    case.run()

    case.args = ["simple/simple"]
    case.expected_parser_error = "No pyproject.toml"
    case.run()
