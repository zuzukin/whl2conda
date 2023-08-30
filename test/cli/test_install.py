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
Unit tests for `whl2conda install` subcommand
"""
import json
import re
from pathlib import Path
from typing import Sequence

import pytest

from whl2conda.cli import main


def test_errors(capsys: pytest.CaptureFixture, tmp_path: Path):
    with pytest.raises(SystemExit):
        main(["install"])
    out, err = capsys.readouterr()
    assert re.search(r"required.*<package-file>", err)

    with pytest.raises(SystemExit):
        main(["install", "does-not-exist.conda"])
    out, err = capsys.readouterr()
    assert "does not exist" in err

    pkg_file = tmp_path.joinpath("my-package.conda")
    pkg_file.write_text("", "utf8")
    with pytest.raises(SystemExit):
        main(["install", str(pkg_file)])
    out, err = capsys.readouterr()
    assert re.search("one of.*--conda-bld.*is required", err)

    not_pkg_file = tmp_path.joinpath("foo.not-conda")
    not_pkg_file.write_text("", "utf8")
    with pytest.raises(SystemExit):
        main(["install", str(not_pkg_file), "-n", "foo"])
    out, err = capsys.readouterr()
    assert "unsupported suffix" in err

    with pytest.raises(SystemExit):
        main(["install", str(pkg_file), "-n", "foo"])
    out, err = capsys.readouterr()
    assert "Cannot extract" in err


def test_bld_install_whitebox(
    capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    Monkey patched whitebox test of --conda-bld install.

    Just makes sure expected conda command is called
    """
    conda_bld_dir = tmp_path.joinpath("conda-bld")

    bld_path: str = ""
    croot: str = str(conda_bld_dir)

    def fake_check_output(cmd: Sequence[str], enconding: str = ""):
        assert cmd[0] == "conda"
        if cmd[1] == "config":
            assert "--show" in cmd
            assert "--json" in cmd
            return json.dumps(dict(bld_path=bld_path, croot=croot))
        else:
            assert cmd[1] == "index"
            assert cmd[2] == str(conda_bld_dir)
            subdir_index = cmd.index("--subdir")
            assert subdir_index > 0
            assert cmd[subdir_index] == "noarch"

    monkeypatch.setattr("subprocess.check_call", fake_check_output)
    monkeypatch.setattr("subprocess.check_output", fake_check_output)

    # pkg_file = tmp_path.joinpath("conda-pkg.conda")
    # main(["install", str(pkg_file), "--conda-bld", "--dry-run"])
