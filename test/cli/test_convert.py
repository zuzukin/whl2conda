#  Copyright 2023-2025 Christopher Barber
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
"""
Unit tests for `whl2conda convert` command line interface
"""

from __future__ import annotations

import argparse

# standard
import logging
import os
import platform
import re
import shutil
import time
from pathlib import Path
from typing import Any, Generator, Optional, Sequence

# third party
import pytest

# this project
from whl2conda.api.converter import (
    CondaPackageFormat,
    Wheel2CondaConverter,
    DependencyRename,
)
from whl2conda.cli import main
from whl2conda.cli.convert import do_build_wheel
from whl2conda.impl.prompt import is_interactive
from whl2conda.settings import settings

from ..impl.test_prompt import monkeypatch_interactive

from ..test_packages import simple_wheel  # pylint: disable=unused-import # noqa: F401

this_dir = Path(__file__).parent.absolute()
root_dir = this_dir.parent.parent

__all__ = ["CliTestCase", "CliTestCaseFactory", "test_case"]

# pylint: disable=redefined-outer-name

#
# Test case fixture
#


# pylint: disable=too-many-instance-attributes
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

    args: list[str]
    interactive: bool
    expected_allow_metadata_version: str = ""
    expected_build_number: Optional[int] = None
    expected_dependency_renames: list[DependencyRename]
    expected_download_spec: str = ""
    expected_download_index: str = ""
    expected_dry_run: bool = False
    expected_extra_dependencies: Sequence[str] = ()
    expected_interactive: bool = True
    expected_keep_pip: bool = False
    expected_out_dir: str = ""
    expected_out_fmt: CondaPackageFormat = CondaPackageFormat.V2
    expected_overwrite: bool = False
    expected_package_name: str = ""
    expected_parser_error: str = ""
    """Relative path from projects dir"""
    expected_project_root: str = ""
    expected_python_version: str = ""
    expected_wheel_path: str = ""

    expected_prompts: list[str]
    responses: list[str]
    from_dir: Path
    was_run: bool = False
    stdrenames_updated: bool = False

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
        project_dir: Path,
        # optional
        interactive: Optional[bool] = None,
        expected_allow_metadata_version: str = "",
        expected_build_number: Optional[int] = None,
        expected_dry_run: bool = False,
        expected_extra_dependencies: Sequence[str] = (),
        expected_download_index: str = "",
        expected_download_spec: str = "",
        expected_interactive: bool = True,
        expected_keep_pip: bool = False,
        expected_out_dir: str = "",
        expected_out_fmt: CondaPackageFormat = CondaPackageFormat.V2,
        expected_overwrite: bool = False,
        expected_package_name: str = "",
        expected_parser_error: str = "",
        expected_project_root: str = "",
        expected_python_version: str = "",
        expected_wheel_path: str = "",
        expected_stdrenames_update: bool = False,
        from_dir: str = "",
    ):
        self.caplog = caplog
        self.capsys = capsys
        self.monkeypatch = monkeypatch
        self.tmp_path = tmp_path

        self.args = list(args)
        self.interactive = is_interactive() if interactive is None else interactive
        self.expected_allow_metadata_version = expected_allow_metadata_version
        self.expected_build_number = expected_build_number
        self.expected_dry_run = expected_dry_run
        self.expected_dependency_renames = []
        self.expected_download_index = expected_download_index
        self.expected_download_spec = expected_download_spec
        self.expected_extra_dependencies = list(expected_extra_dependencies)
        self.expected_interactive = expected_interactive
        self.expected_keep_pip = expected_keep_pip
        self.expected_out_dir = expected_out_dir
        self.expected_out_fmt = expected_out_fmt
        self.expected_overwrite = expected_overwrite
        self.expected_package_name = expected_package_name
        self.expected_parser_error = expected_parser_error
        self.expected_project_root = expected_project_root
        self.expected_prompts = []
        self.expected_python_version = expected_python_version
        self.expected_wheel_path = expected_wheel_path
        self.expected_stdrenames_update = expected_stdrenames_update
        self.responses = []

        self.project_dir = project_dir
        self.from_dir = (
            self.project_dir.joinpath(from_dir) if from_dir else self.project_dir
        )

    def run(self) -> None:
        """Run the test"""

        self.was_run = True
        prompts = iter(self.expected_prompts)
        responses = iter(self.responses)

        # pylint: disable=unused-argument
        def fake_build_wheel(
            project_root: Path,
            wheel_dir: Path,
            *,
            no_deps: bool = False,
            dry_run: bool = False,
            capture_output: bool = False,
        ) -> Path:
            # TODO validate no_deps, dry_run
            return wheel_dir.joinpath("fake-1.0-py3-none-any.whl")

        def fake_download_wheel(
            spec: str,
            index: str = "",
            into: Optional[Path] = None,
        ) -> Path:
            """Fake version of download_wheel"""
            assert spec == self.expected_download_spec
            assert index == self.expected_download_index
            _into = into or Path.cwd()
            return _into / "fake-1.0-py3-none-any.whl"

        def fake_input(prompt: str) -> str:
            expected_prompt = next(prompts)
            assert re.search(expected_prompt, prompt), (
                f"'{expected_prompt}' does not match prompt '{prompt}'"
            )
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
                conda_pkg_path.write_text("", encoding="utf8")
            return conda_pkg_path

        def fake_stdrenames_update(*_args, **_kwargs) -> bool:
            self.stdrenames_updated = True
            return True

        with self.monkeypatch.context() as mp:
            # TODO monkeypatch for --test-install
            mp.setattr(Wheel2CondaConverter, "convert", fake_convert)
            mp.setattr("builtins.input", fake_input)
            mp.setattr("whl2conda.cli.convert.do_build_wheel", fake_build_wheel)
            mp.setattr("whl2conda.impl.download.download_wheel", fake_download_wheel)
            mp.setattr("whl2conda.cli.convert.download_wheel", fake_download_wheel)
            mp.setattr(
                "whl2conda.api.stdrename.update_renames_file",
                fake_stdrenames_update,
            )
            if self.interactive is not is_interactive():
                monkeypatch_interactive(mp, self.interactive)
            mp.chdir(self.from_dir)

            self.capsys.readouterr()

            # Run the command
            exit_code: Any = None
            try:
                main(["convert"] + self.args, "whl2conda")
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
            assert self.stdrenames_updated == self.expected_stdrenames_update

    def add_dependency_rename(self, pypi_name: str, conda_name: str) -> CliTestCase:
        """Add an expected dependency rename

        Arguments:
            pypi_name: the original name from wheel
            conda_name: the resulting conda name
        """
        self.expected_dependency_renames.append(
            DependencyRename.from_strings(pypi_name, conda_name)
        )
        return self

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
        projects = self.project_dir
        expected_root = self.expected_project_root
        if expected_wheel := self.expected_wheel_path:
            assert converter.wheel_path == projects / expected_wheel
        expected_outdir = self.expected_out_dir
        if not expected_outdir:
            if expected_wheel:
                expected_outdir = os.path.dirname(expected_wheel)
            elif expected_root:
                expected_outdir = os.path.join(expected_root, "dist")
        if expected_outdir:
            assert converter.out_dir == projects / expected_outdir
        if self.expected_allow_metadata_version:
            assert (
                self.expected_allow_metadata_version
                in converter.SUPPORTED_METADATA_VERSIONS
            )
        assert converter.build_number == self.expected_build_number
        assert converter.dry_run is self.expected_dry_run
        if self.expected_package_name:
            assert converter.package_name == self.expected_package_name
        assert converter.out_format is self.expected_out_fmt
        assert converter.overwrite is self.expected_overwrite
        assert converter.keep_pip_dependencies is self.expected_keep_pip
        assert converter.extra_dependencies == list(self.expected_extra_dependencies)
        assert converter.dependency_rename == list(self.expected_dependency_renames)
        assert converter.python_version == self.expected_python_version


class CliTestCaseFactory:
    """Factory for CLI test case runners

    The factory copies the test-projects/ directory tree
    into tmp directory shared by all test cases produced
    by the factory rooted under the `project_dir` path.

    Note that all test cases will share the same tree
    and can see any changes introduced by previous test
    cases.
    """

    capsys: pytest.CaptureFixture
    monkeypatch: pytest.MonkeyPatch
    tmp_path: Path
    project_dir: Path

    cases: list[CliTestCase]

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

        orig_project_dir = root_dir.joinpath("test-projects")
        self.project_dir = tmp_path.joinpath("projects")
        shutil.copytree(orig_project_dir, self.project_dir)
        self.cases = []

    # pylint: disable=too-many-locals
    def __call__(
        self,
        args: Sequence[str],
        *,
        interactive: Optional[bool] = None,
        expected_allow_metadata_version: str = "",
        expected_build_number: Optional[int] = None,
        expected_download_index: str = "",
        expected_download_spec: str = "",
        expected_dry_run: bool = False,
        expected_package_name: str = "",
        expected_parser_error: str = "",
        expected_out_dir: str = "",
        expected_out_fmt: CondaPackageFormat = CondaPackageFormat.V2,
        expected_overwrite: bool = False,
        expected_keep_pip: bool = False,
        expected_extra_dependencies: Sequence[str] = (),
        expected_interactive: bool = True,
        expected_project_root: str = "",
        expected_python_version: str = "",
        expected_wheel_path: str = "",
        expected_stdrenames_update: bool = False,
        from_dir: str = "",
    ) -> CliTestCase:
        case = CliTestCase(
            caplog=self.caplog,
            capsys=self.capsys,
            monkeypatch=self.monkeypatch,
            tmp_path=self.tmp_path,
            project_dir=self.project_dir,
            args=args,
            interactive=interactive,
            expected_allow_metadata_version=expected_allow_metadata_version,
            expected_build_number=expected_build_number,
            expected_download_index=expected_download_index,
            expected_download_spec=expected_download_spec,
            expected_dry_run=expected_dry_run,
            expected_package_name=expected_package_name,
            expected_parser_error=expected_parser_error,
            expected_out_dir=expected_out_dir,
            expected_out_fmt=expected_out_fmt,
            expected_overwrite=expected_overwrite,
            expected_keep_pip=expected_keep_pip,
            expected_extra_dependencies=expected_extra_dependencies,
            expected_interactive=expected_interactive,
            expected_project_root=expected_project_root,
            expected_python_version=expected_python_version,
            expected_wheel_path=expected_wheel_path,
            expected_stdrenames_update=expected_stdrenames_update,
            from_dir=from_dir,
        )
        self.cases.append(case)
        return case

    def teardown(self) -> None:
        """Make sure all test cases have been run."""
        for i, case in enumerate(self.cases):
            if not case.was_run:
                pytest.fail(f"Case #{i + 1} was not run")


@pytest.fixture
def test_case(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Generator[CliTestCaseFactory, None, None]:
    """Yields test CLI case factory"""
    factory = CliTestCaseFactory(
        caplog=caplog, capsys=capsys, monkeypatch=monkeypatch, tmp_path=tmp_path
    )
    yield factory
    factory.teardown()


#
# Command line tests
#


def test_simple_default(test_case: CliTestCaseFactory) -> None:
    """
    Interactive mode run on project dir with no options.
    """
    case = test_case(
        ["simple"],
        interactive=False,
        expected_package_name="simple",
        expected_project_root="simple",
        expected_parser_error="No wheels found in directory",
    )
    case.run()

    case = test_case(
        ["simple"],
        interactive=True,
        expected_package_name="simple",
        expected_project_root="simple",
    )
    case.add_prompt(
        r"\[build\] build wheel",
        "build",
    )
    case.run()

    # run from project root dir without any positional args
    case = test_case(
        [],
        interactive=True,
        expected_package_name="simple",
        expected_project_root="simple",
        from_dir="simple",
    )
    case.add_prompt(
        r"\[build\] build wheel",
        "no-dep",
    )
    case.run()

    case = test_case(
        ["--project-root", "simple"],
        expected_package_name="simple",
        interactive=True,
        expected_project_root="simple",
    )
    case.add_prompt(
        r"\[build\] build wheel",
        "no-dep",
    )
    case.run()


def test_simple_log_level(
    test_case: CliTestCaseFactory,
) -> None:
    """
    Test log level setting using simple project
    """
    root_logger = logging.getLogger()
    wheel_file = test_case.tmp_path.joinpath("acme-1.0.whl")
    wheel_file.write_text("", encoding="utf8")

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
    test_case(
        ["does-not-exist"],
        expected_parser_error="'does-not-exist' does not exist",
    ).run()

    test_case(
        [str(Path(__file__).absolute())],
        expected_parser_error="does not have .whl suffix",
    ).run()

    test_case(
        ["simple", "--project-root", "simple"],
        expected_parser_error="project root as both positional and keyword",
    ).run()

    test_case(
        ["simple/simple"],
        expected_parser_error="No pyproject.toml",
    ).run()

    test_case(
        ["--project-root", "does-not-exist"],
        expected_parser_error="does not exist",
    ).run()

    not_a_dir = test_case.tmp_path.joinpath("not_a_dir")
    not_a_dir.write_text("")
    test_case(
        ["--project-root", str(not_a_dir.absolute())],
        expected_parser_error="is not a directory",
    ).run()

    test_case(
        ["--wheel-dir", str(not_a_dir)], expected_parser_error="is not a directory"
    ).run()

    test_case(
        ["--out-dir", str(not_a_dir)], expected_parser_error="is not a directory"
    ).run()


def test_out_format(test_case: CliTestCaseFactory) -> None:
    """
    Test --out-format
    """

    assert settings.conda_format is CondaPackageFormat.V2

    wheel_file = test_case.tmp_path.joinpath("fake-1.0.whl")
    wheel_file.write_text("")

    case = test_case([str(wheel_file)], expected_out_fmt=CondaPackageFormat.V2)
    case.run()

    settings.conda_format = CondaPackageFormat.V1

    case = test_case([str(wheel_file)], expected_out_fmt=CondaPackageFormat.V1)
    case.run()

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
    expected_no_deps = True
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

    monkeypatch.setattr("subprocess.run", fake_call)

    caplog.set_level("INFO")

    wheel_file = do_build_wheel(
        project_root, wheel_dir, dry_run=True, capture_output=True
    )
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
    wheel_file.unlink()
    assert not wheel_file.is_file()

    expected_no_build_isolation = False
    expected_no_deps = True
    wheel_file = do_build_wheel(project_root, wheel_dir, no_deps=True)
    assert wheel_file.parent == wheel_dir
    assert wheel_file.is_file()
    wheel_file.unlink()

    expected_no_build_isolation = True
    expected_no_deps = False
    wheel_file = do_build_wheel(
        project_root, wheel_dir, no_deps=False, no_build_isolation=True
    )
    assert wheel_file.parent == wheel_dir
    assert wheel_file.is_file()
    wheel_file.unlink()


# ignore redefinition of test_case
# ruff: noqa: F811


def test_input_wheel(
    test_case: CliTestCaseFactory,
    simple_wheel: Path,
) -> None:
    """Test whl2conda build with explicit wheel"""
    # Free standing wheel, not in project
    case = test_case(
        [str(simple_wheel)],
        interactive=False,
        expected_wheel_path=str(simple_wheel),
        expected_out_dir=str(simple_wheel.parent),
    )
    case.run()

    simple_root = test_case.project_dir / "simple"
    case = test_case(
        [str(simple_wheel), "--project-root", str(simple_root)],
        interactive=False,
        expected_wheel_path=str(simple_wheel),
        expected_out_dir=str(simple_wheel.parent),
        expected_project_root="simple",
    )
    case.run()

    # Put wheel in project subdir to test finding project
    dist = simple_root / "dist"
    subdist = dist / "subdist"
    subdist.mkdir(parents=True)
    subdist_wheel = subdist / simple_wheel.name
    shutil.copyfile(simple_wheel, subdist_wheel)

    case = test_case(
        [str(subdist_wheel)],
        interactive=False,
        expected_wheel_path=str(subdist_wheel),
        expected_out_dir=str(subdist_wheel.parent),
        expected_project_root="simple",
    )
    case.run()

    case = test_case(
        [str(subdist_wheel), "--wheel-dir", str(dist)],
        interactive=False,
        expected_wheel_path=str(subdist_wheel),
        # expected out taken from wheel dir even if wheel in different dir
        expected_out_dir=str(dist),
        expected_project_root="simple",
    )
    case.run()


def test_choose_wheel(
    test_case: CliTestCaseFactory,
    simple_wheel: Path,
) -> None:
    """Test finding/choosing wheel"""
    project_root = test_case.project_dir / "simple"
    dist = project_root / "dist"
    assert not dist.exists()

    case = test_case(
        ["simple"], interactive=False, expected_parser_error="No wheels found"
    )
    case.run()

    # add a wheel
    dist.mkdir(parents=True)
    dist_wheel = dist / simple_wheel.name
    shutil.copyfile(simple_wheel, dist_wheel)

    # wheel is chosen if only one
    case = test_case(
        ["simple"],
        interactive=False,
        expected_project_root="simple",
        expected_wheel_path=str(dist_wheel),
    )
    case.run()

    # add second copy of wheel
    # Use longer sleep on Windows due to lower timestamp resolution
    sleep_duration = 0.1 if platform.system() == "Windows" else 0.01
    time.sleep(sleep_duration)  # wait to ensure later timestamp
    dist_wheel2 = dist / f"{dist_wheel.stem}-2.whl"
    shutil.copyfile(simple_wheel, dist_wheel2)
    case = test_case(
        ["simple"],
        interactive=False,
        expected_project_root="simple",
        expected_wheel_path=str(dist_wheel),
        expected_parser_error="Cannot choose from multiple wheels",
    )
    case.run()

    # with --yes, the latest wheel will be chosen
    case = test_case(
        ["simple", "--yes"],
        interactive=False,
        expected_project_root="simple",
        expected_wheel_path=str(dist_wheel2),
    )
    case.run()


def test_download_wheel(
    test_case: CliTestCaseFactory,
    simple_wheel: Path,  # pylint: disable=unused-argument
) -> None:
    """Test downloading wheel"""

    case = test_case(
        ["--from-pypi", "simple"],
        interactive=False,
        expected_download_spec="simple",
    )
    case.run()

    case = test_case(
        ["--from-index", "https://somewhere.com/pypi", "simple >=1.2.3"],
        interactive=False,
        expected_download_spec="simple >=1.2.3",
        expected_download_index="https://somewhere.com/pypi",
    )
    case.run()


def test_outdir(
    test_case: CliTestCaseFactory,
    simple_wheel: Path,
) -> None:
    """Test whl2conda build output directory"""
    test_case(
        [str(simple_wheel)],
        expected_out_dir=str(simple_wheel.parent),
        expected_wheel_path=str(simple_wheel),
    ).run()

    test_case(
        [str(simple_wheel), "-w", "frob"],
        expected_out_dir="frob",
    ).run()

    test_case(
        [str(simple_wheel), "-w", "frob", "--out", "out"],
        expected_out_dir="out",
    ).run()


def test_pyproject(
    test_case: CliTestCaseFactory,
) -> None:
    """Test pyproject settings"""
    project_root = test_case.project_dir / "settings"

    test_case(
        [str(project_root), "--yes"],
        interactive=False,
        expected_project_root="settings",
        expected_out_dir="settings/conda-dist",
        expected_package_name="conda-settings",
        expected_out_fmt=CondaPackageFormat.V1,
        expected_extra_dependencies=["pytest"],
    ).add_dependency_rename('numpy', '').add_dependency_rename('mypy', 'pylint').run()

    test_case(
        [str(project_root), "--yes", "--ignore-pyproject"],
        interactive=False,
        expected_project_root="settings",
    ).run()


def test_rename_options(
    test_case: CliTestCaseFactory,
    simple_wheel: Path,
) -> None:
    """Test rename/drop dependency options"""
    test_case(
        [str(simple_wheel)],
        interactive=False,
        expected_wheel_path=str(simple_wheel),
        expected_out_dir=str(simple_wheel.parent),
    ).run()

    test_case(
        [
            str(simple_wheel),
            "-A",
            "foo",
            "--add-dependency",
            "bar",
            "-D",
            "quaternion",
        ],
        interactive=False,
        expected_wheel_path=str(simple_wheel),
        expected_out_dir=str(simple_wheel.parent),
        expected_extra_dependencies=["foo", "bar"],
    ).add_dependency_rename(
        "quaternion",
        "",
    ).run()

    test_case(
        [str(simple_wheel), "-R", "[bad", "bad"],
        expected_parser_error="Bad dependency rename pattern",
    ).run()

    test_case(
        [str(simple_wheel), "-R", "acme-(.*)", "acme.$2"],
        expected_parser_error="Bad dependency replacement",
    ).run()


def test_build_number(
    test_case: CliTestCaseFactory,
    simple_wheel: Path,
) -> None:
    """Test whl2conda build output directory"""
    test_case(
        [str(simple_wheel)],
        expected_build_number=None,
    ).run()

    test_case(
        [str(simple_wheel), "--build-number", "42"],
        expected_build_number=42,
    ).run()


def test_python_override(
    test_case: CliTestCaseFactory,
    simple_wheel: Path,
) -> None:
    """Test --python option"""
    test_case(
        [str(simple_wheel), "--python", ">=3.10"], expected_python_version=">=3.10"
    ).run()


def test_allow_metadata_version(
    test_case: CliTestCaseFactory,
    simple_wheel: Path,
) -> None:
    """Test processing of --allow-metadata-version option"""
    test_case(
        [str(simple_wheel), "--allow-metadata-version", "12.3"],
        expected_allow_metadata_version="12.3",
    ).run()


def test_stdrenames_update(
    test_case: CliTestCaseFactory,
    simple_wheel: Path,
) -> None:
    """
    Test --update-stdrenames options
    """
    assert not settings.auto_update_std_renames

    test_case(
        [str(simple_wheel)],
        expected_stdrenames_update=False,
    ).run()

    test_case(
        [str(simple_wheel), "--update-stdrenames"],
        expected_stdrenames_update=True,
    ).run()

    settings.auto_update_std_renames = True
    test_case(
        [str(simple_wheel)],
        expected_stdrenames_update=True,
    ).run()

    test_case(
        [str(simple_wheel), "--no-update-stdrenames"],
        expected_stdrenames_update=False,
    ).run()

    settings.auto_update_std_renames = False
