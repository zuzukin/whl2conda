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
Unit tests for main `whl2conda` CLI
"""

from __future__ import annotations

import re
import subprocess
import sys

import pytest

from whl2conda import __version__
from whl2conda.cli import main


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

    subcmds = ["build", "convert", "config", "diff", "install"]
    for subcmd in subcmds:
        assert re.search(rf"^\s+{subcmd}\s+\w+", out, flags=re.MULTILINE)

    with pytest.raises(SystemExit) as exc_info:
        main(["--list-subcommands"], "whl2conda")
    out, err = capsys.readouterr()
    assert err == ""
    assert set(out.strip().split()) == set(subcmds)
    assert exc_info.value.code == 0

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


def test_main_module() -> None:
    """
    Test running using python -m
    """
    version = subprocess.check_output(
        [sys.executable, "-m", "whl2conda", "--version"], encoding="utf8"
    )
    assert version.strip() == __version__

    # pylint: disable=import-outside-toplevel
    import whl2conda.__main__

    assert whl2conda.__main__.main is main
