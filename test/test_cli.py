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

import argparse

# standard
import logging
import re
import shutil
from pathlib import Path
from typing import Any, Generator, List, Optional, Sequence, Tuple
from urllib.error import URLError

# third party
import pytest

# this project
from whl2conda.__about__ import __version__
from whl2conda.converter import CondaPackageFormat, Wheel2CondaConverter
from whl2conda.cli import main
from whl2conda.cli.build import do_build_wheel
from whl2conda.cli.config import update_std_renames
from whl2conda.prompt import is_interactive
from whl2conda.stdrename import user_stdrenames_path

from .test_prompt import monkeypatch_interactive

this_dir = Path(__file__).parent
project_dir = this_dir.joinpath("projects")

__all__ = ["CliTestCase", "CliTestCaseFactory", "test_case"]

# pylint: disable=redefined-outer-name

#
# Test case fixture
#


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

    args: List[str]
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
    from_dir: Path

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
        from_dir: str = "",
    ):
        self.caplog = caplog
        self.capsys = capsys
        self.monkeypatch = monkeypatch
        self.tmp_path = tmp_path

        self.args = list(args)
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
        self.from_dir = (
            self.project_dir.joinpath(from_dir) if from_dir else self.project_dir
        )
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
            # TODO validate no_deps, dry_run
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
            # TODO monkeypatch for --test-install
            mp.setattr(Wheel2CondaConverter, "convert", fake_convert)
            mp.setattr("builtins.input", fake_input)
            mp.setattr("whl2conda.cli.build.do_build_wheel", fake_build_wheel)
            if self.interactive is not is_interactive():
                monkeypatch_interactive(mp, self.interactive)
            mp.chdir(self.from_dir)

            self.capsys.readouterr()

            # Run the command
            exit_code: Any = None
            try:
                main(["build"] + self.args, "whl2conda")
            except SystemExit as exit_err:
                exit_code = exit_err.code

            _out, err = self.capsys.readouterr()

            if self.expected_parser_error:
                if exit_code is None:
                    pytest.fail(
                        f"No parser error, but expected '{self.expected_parser_error}'"
                    )
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
        if self.expected_project_root:
            assert converter.project_root == self.project_dir.joinpath(
                self.expected_project_root
            )
        else:
            assert not converter.project_root
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


#
# Command line tests
#


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

    subcmds = ["build", "config"]
    for subcmd in subcmds:
        assert re.search(rf"^\s+{subcmd}\s+\w+", out, flags=re.MULTILINE)

    def _check_subcmd(subcmd: str):
        with monkeypatch.context() as ctx:
            with pytest.raises(SystemExit):
                main(f"{subcmd} --help".split(), "whl2conda2")
            out, err = capsys.readouterr()
            assert not err
            assert "usage: whl2conda2" in out
            assert "--markdown-help" not in out

            ctx.setattr("sys.argv", f"whl2conda3 {subcmd} --help".split())
            with pytest.raises(SystemExit):
                main()
            out, err = capsys.readouterr()
            assert not err
            assert "usage: whl2conda3" in out

            with pytest.raises(SystemExit):
                main(f"{subcmd} --markdown-help".split())
            out, err = capsys.readouterr()
            assert not err
            assert "### Usage" in out
            assert "usage: whl2conda3" in out

    for subcmd in subcmds:
        _check_subcmd(subcmd)


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

    # run from project root dir without any positional args
    case.from_dir = case.project_dir.joinpath("simple")
    case.args = []
    case.run()

    case.from_dir = case.project_dir
    case.args = ["--project-root", str(case.project_dir.joinpath("simple"))]
    case.run()


def test_simple_log_level(
    test_case: CliTestCaseFactory,
) -> None:
    """
    Test log level setting using simple project
    """
    root_logger = logging.getLogger()
    wheel_file = test_case.tmp_path.joinpath("acme-1.0.whl")
    wheel_file.write_text("")

    case = test_case([str(wheel_file), "--dry-run"], expected_dry_run=True)
    case.run()
    assert root_logger.level == logging.DEBUG

    case.args.append("-v")  # implied by dry run already
    case.run()
    assert root_logger.level == logging.DEBUG

    case.args[-1] = "-q"
    case.run()
    assert root_logger.level == logging.INFO

    case.args[-1] = "-qq"
    case.run()
    assert root_logger.level == logging.WARNING

    case.args.append("--quiet")
    case.run()
    assert root_logger.level == logging.ERROR

    case.args[2:] = ["-v", "--verbose"]
    case.run()
    assert root_logger.level < logging.DEBUG

    case.args[1:] = []
    case.expected_dry_run = False
    case.run()
    assert root_logger.level == logging.INFO


def test_parse_errors(test_case: CliTestCaseFactory) -> None:
    """
    Test cli parser errors
    """
    case = test_case(
        ["does-not-exist"], expected_parser_error="'does-not-exist' does not exist"
    )
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

    case.args = ["--project-root", "does-not-exist"]
    case.expected_parser_error = "does not exist"
    case.run()

    not_a_dir = case.tmp_path.joinpath("not_a_dir")
    not_a_dir.write_text("")
    case.args = ["--project-root", str(not_a_dir.absolute())]
    case.expected_parser_error = "is not a directory"
    case.run()


def test_out_format(test_case: CliTestCaseFactory) -> None:
    """
    Test --out-format
    """

    wheel_file = test_case.tmp_path.joinpath("fake-1.0.whl")
    wheel_file.write_text("")

    case = test_case(
        [str(wheel_file), "--out-format", "V1"], expected_out_fmt=CondaPackageFormat.V1
    )
    case.run()

    case.args[-1] = "tar.bz2"
    case.run()

    case.args[-1] = "V2"
    case.expected_out_fmt = CondaPackageFormat.V2
    case.run()

    case.args[-1] = "conda"
    case.run()

    case.args[-1] = "tree"
    case.expected_out_fmt = CondaPackageFormat.TREE
    case.run()

    case.args[-1] = "bogus"
    case.expected_parser_error = "invalid choice"
    case.run()


# pylint: disable=too-many-statements
def test_update_std_renames(
    capsys: pytest.CaptureFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unit test for update_std_renames internal method"""

    fake_update_result = False
    expected_dry_run = True
    fake_exception: Optional[Exception] = None

    # pylint: disable=unused-argument
    def _fake_update(
        renames_file: Path, *, url: str = "", dry_run: bool = False
    ) -> bool:
        if fake_exception is not None:
            raise fake_exception
        assert dry_run is expected_dry_run
        return fake_update_result

    monkeypatch.setattr("whl2conda.stdrename.update_renames_file", _fake_update)
    monkeypatch.setattr("whl2conda.cli.config.update_renames_file", _fake_update)

    file = tmp_path.joinpath("stdrename.json")
    with pytest.raises(SystemExit):
        update_std_renames(file, dry_run=True)
    out, err = capsys.readouterr()
    assert not err
    assert f"Updating {file}" in out
    assert "No changes" in out

    fake_update_result = True
    with pytest.raises(SystemExit):
        update_std_renames(file, dry_run=True)
    out, err = capsys.readouterr()
    assert not err
    assert f"Updating {file}" in out
    assert "Update available" in out

    expected_dry_run = False
    with pytest.raises(SystemExit):
        update_std_renames(file, dry_run=False)
    out, err = capsys.readouterr()
    assert not err
    assert f"Updating {file}" in out
    assert "Updated" in out

    fake_update_result = False
    with pytest.raises(SystemExit):
        update_std_renames(file, dry_run=False)
    out, err = capsys.readouterr()
    assert not err
    assert f"Updating {file}" in out
    assert "No changes" in out

    fake_exception = URLError("could not connect")
    with pytest.raises(SystemExit) as exc_info:
        update_std_renames(file, dry_run=False)
    assert exc_info.value.code != 0
    out, err = capsys.readouterr()
    assert f"Updating {file}" in out
    assert "Cannot download" in err

    #
    # test command line
    #

    for var in ["HOME", "USERPROFILE"]:
        monkeypatch.setenv(var, str(tmp_path))

    renames_file = user_stdrenames_path()
    assert renames_file.relative_to(tmp_path)
    assert not renames_file.exists()

    fake_exception = None
    expected_dry_run = False
    fake_update_result = True

    with pytest.raises(SystemExit) as exc_info:
        main(["config", "--update-std-renames"])
    assert exc_info.value.code == 0
    out, err = capsys.readouterr()
    assert not err
    assert f"Updating {renames_file}" in out
    assert "Updated" in out

    fake_update_result = False
    expected_dry_run = True
    with pytest.raises(SystemExit) as exc_info:
        main(["config", "--update-std-renames", "--dry-run"])
    assert exc_info.value.code == 0
    out, err = capsys.readouterr()
    assert not err
    assert f"Updating {renames_file}" in out
    assert "No changes" in out

    expected_dry_run = False
    with pytest.raises(SystemExit) as exc_info:
        main(["config", "--update-std-renames", "here.json"])
    assert exc_info.value.code == 0
    out, err = capsys.readouterr()
    assert not err
    assert "Updating here.json" in out


def test_do_build_wheel(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Unit test for internal do_build_wheel function"""
    project_root = tmp_path
    wheel_dir = project_root.joinpath("dist")
    assert not wheel_dir.exists()

    expected_project_root = project_root
    expected_wheel_dir = wheel_dir
    expected_no_deps = False
    expected_no_build_isolation = False

    def fake_call(cmd: Sequence[str], **_kwargs) -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("pip", choices=["pip"])
        parser.add_argument("cmd", choices=["wheel"])
        parser.add_argument("root")
        parser.add_argument("-w", "--wheel-dir")
        parser.add_argument("--no-deps", action="store_true")
        parser.add_argument("--no-build-isolation", action="store_true")
        parsed = parser.parse_args(cmd)
        assert parsed.root == str(expected_project_root)
        assert parsed.wheel_dir == str(expected_wheel_dir)
        assert parsed.no_deps is expected_no_deps
        assert parsed.no_build_isolation is expected_no_build_isolation
        wheel_file = Path(parsed.wheel_dir).joinpath("acme-1.2.3-py3-none-any.whl")
        wheel_file.write_text("")

    monkeypatch.setattr("subprocess.check_call", fake_call)

    caplog.set_level("INFO")

    wheel_file = do_build_wheel(project_root, wheel_dir, dry_run=True)
    assert not wheel_dir.exists()
    assert not wheel_file.exists()
    assert wheel_file.parent == wheel_dir
    assert wheel_file.name.startswith("dry-run-")

    logs = caplog.records
    assert logs[0].levelname == 'INFO'
    assert logs[0].getMessage() == f"Building wheel for {project_root}"
    assert logs[1].levelname == "INFO"
    assert logs[1].getMessage().startswith("Running: ['pip'")

    caplog.clear()

    caplog.set_level("WARNING")
    wheel_file = do_build_wheel(project_root, wheel_dir)
    assert wheel_file.parent == wheel_dir
    assert wheel_file.is_file()

    expected_no_build_isolation = expected_no_deps = True
    wheel_file = do_build_wheel(project_root, wheel_dir, no_deps=True)
