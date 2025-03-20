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
#
"""
Unit test for `whl2conda diff` subcommand
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from whl2conda.cli import main

# pylint: disable=unused-import
from ..test_packages import simple_conda_package, simple_wheel  # noqa: F401

# pylint: disable=redefined-outer-name

# ignore redefinition of simple_conda_package
# ruff: noqa: F811


def test_diff_errors(
    capsys: pytest.CaptureFixture,
    tmp_path: Path,
    simple_conda_package: Path,
) -> None:
    """
    Unit test for `whl2conda diff` arg errors
    """

    with pytest.raises(SystemExit):
        main(["diff"])
    _, err = capsys.readouterr()
    assert re.search(r"are required:.*package1.*package2.*--diff-tool", err)

    with pytest.raises(SystemExit):
        main(["diff", str(simple_conda_package)])
    _, err = capsys.readouterr()
    assert re.search(r"are required:.*package2.*--diff-tool", err)

    with pytest.raises(SystemExit):
        main(["diff", str(simple_conda_package), str(simple_conda_package)])
    _, err = capsys.readouterr()
    assert re.search(r"are required:.*--diff-tool", err)

    with pytest.raises(SystemExit):
        main(["diff", str(simple_conda_package), "does-not-exist"])
    _, err = capsys.readouterr()
    assert "does not exist" in err

    not_a_package = tmp_path / "not-a-package.txt"
    not_a_package.write_text("hi")
    with pytest.raises(SystemExit):
        main(["diff", str(simple_conda_package), str(not_a_package)])
    _, err = capsys.readouterr()
    assert "is not a conda package" in err


def test_diff(
    capsys: pytest.CaptureFixture,  # pylint: disable=unused-argument
    tmp_path: Path,
    simple_conda_package: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    whitebox test for whl2conda diff
    """
    monkeypatch.chdir(tmp_path)

    expected_diff = "diff"
    expected_r = True

    def _fake_diff(
        cmd: list[str],
        **_kwargs,
    ):
        assert cmd[0] == expected_diff
        parser = argparse.ArgumentParser(prog="diff")
        parser.add_argument("dir1")
        parser.add_argument("dir2")
        parser.add_argument("-r", action="store_true")
        parsed = parser.parse_args(cmd[1:])

        # TODO: Use Path.is_relative method introduced in Python 3.9

        assert parsed.r == expected_r
        for d in [parsed.dir1, parsed.dir2]:
            dirpath = Path(d)
            assert dirpath.is_dir()
            dirpath.relative_to(tmp_path)
            info = dirpath / "info"
            assert info.is_dir()

    monkeypatch.setattr("subprocess.run", _fake_diff)

    pkg = str(simple_conda_package)

    main(["diff", pkg, pkg, "-T", 'diff', "-A", "-r"])

    expected_diff = "kdiff3"
    expected_r = False
    main(["diff", "--diff-tool", "kdiff3", pkg, pkg])

    # make sure temp directories are gone
    assert not list(tmp_path.glob("**/*"))

    # TODO test file normalization has happened
