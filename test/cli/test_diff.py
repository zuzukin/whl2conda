#  Copyright 2023-2026 Christopher Barber
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
import json
import re
from pathlib import Path

import conda_package_handling.api as cphapi
import pytest

from whl2conda.cli import main

# pylint: disable=unused-import
from ..test_packages import simple_conda_package, simple_wheel  # noqa: F401

# pylint: disable=redefined-outer-name

# ignore redefinition of simple_conda_package


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
    assert re.search(r"are required:.*package1.*package2", err)

    with pytest.raises(SystemExit):
        main(["diff", str(simple_conda_package)])
    _, err = capsys.readouterr()
    assert re.search(r"are required:.*package2", err)

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


def test_diff_missing_info_files(
    tmp_path: Path,
    simple_conda_package: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    diff tolerates packages with missing info files (#192)

    In particular, packages built by rattler-build do not contain
    an info/files entry.
    """
    # repackage the test package without most of its info files
    extract_dir = tmp_path / "extracted"
    cphapi.extract(str(simple_conda_package), str(extract_dir))
    for name in ["files", "about.json", "link.json", "index.json", "paths.json"]:
        (extract_dir / "info" / name).unlink()
    cphapi.create(
        str(extract_dir), None, simple_conda_package.name, out_folder=str(tmp_path)
    )
    stripped_package = tmp_path / simple_conda_package.name
    assert stripped_package.is_file()

    diff_ran = False

    def _fake_diff(cmd: list[str], **_kwargs) -> None:
        nonlocal diff_ran
        diff_ran = True
        for d in cmd[1:3]:
            assert (Path(d) / "info").is_dir()

    monkeypatch.setattr("subprocess.run", _fake_diff)
    monkeypatch.chdir(tmp_path)

    main(["diff", str(simple_conda_package), str(stripped_package), "-T", "diff"])
    assert diff_ran


def test_diff_analysis(
    capsys: pytest.CaptureFixture,
    tmp_path: Path,
    simple_conda_package: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Test semantic analysis mode (no -T)
    """
    monkeypatch.chdir(tmp_path)
    pkg = str(simple_conda_package)

    # self comparison: report with no errors, exit code 0
    main(["diff", pkg, pkg])
    out, err = capsys.readouterr()
    assert not err
    assert "0 errors, 0 notices" in out

    # --json produces valid json
    main(["diff", pkg, pkg, "--json"])
    out, err = capsys.readouterr()
    jobj = json.loads(out)
    assert jobj["ok"] is True
    assert jobj["differences"] == []

    # mutated copy: unexpected difference reported, exit code 1
    extract_dir = tmp_path / "mutated"
    cphapi.extract(pkg, str(extract_dir))
    index_file = extract_dir / "info" / "index.json"
    index = json.loads(index_file.read_text("utf8"))
    index["depends"].append("added-dep >=1")
    index_file.write_text(json.dumps(index))
    (extract_dir / "info" / "files").unlink()
    cphapi.create(
        str(extract_dir), None, simple_conda_package.name, out_folder=str(tmp_path)
    )
    mutated_pkg = str(tmp_path / simple_conda_package.name)

    with pytest.raises(SystemExit) as exc_info:
        main(["diff", pkg, mutated_pkg])
    assert exc_info.value.code == 1
    out, err = capsys.readouterr()
    assert "added-dep" in out
    assert "1 errors" in out

    # --ignore suppresses the error and restores exit code 0
    main(["diff", pkg, mutated_pkg, "--ignore", "dep-missing"])
    out, err = capsys.readouterr()
    assert "0 errors" in out

    # --all also reports expected differences (one-sided info/files)
    main(["diff", pkg, mutated_pkg, "--ignore", "dep-missing", "--all"])
    out, err = capsys.readouterr()
    assert "info/files" in out
