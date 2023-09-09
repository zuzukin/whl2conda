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
Unit tests for whl2conda.prompt module
"""

import time
from collections import deque
from pathlib import Path
from typing import Deque, Iterator

import pytest

from whl2conda.impl.prompt import is_interactive, bool_input, choose_wheel

__all__ = ["monkeypatch_interactive"]

# pylint: disable=unused-argument


def monkeypatch_interactive(monkeypatch: pytest.MonkeyPatch, interactive: bool) -> None:
    """monkeypatch is_interactive() to return given value"""
    monkeypatch.setattr('sys.__stdin__.isatty', lambda: interactive)


def test_is_interactive(
    monkeypatch: pytest.MonkeyPatch,
    # include capsys to make sure that monkeypatch works with capsys
    capsys: pytest.CaptureFixture,
) -> None:
    """Unit test for is_interactive"""
    # whitebox test
    monkeypatch_interactive(monkeypatch, True)
    assert is_interactive()
    monkeypatch_interactive(monkeypatch, False)
    assert not is_interactive()


def test_bool_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit test for bool_input function"""
    input_calls: Iterator[tuple[str, str]] = iter(())

    def fake_input(prompt: str) -> str:
        try:
            expected, response = next(input_calls)
        except StopIteration:
            pytest.fail(f"Unexpected input({repr(prompt)}) call")
        assert expected in prompt
        return response

    monkeypatch.setattr("builtins.input", fake_input)

    for yes in ["yes", "y", "Yes", "true", "True"]:
        input_calls = iter([("do something?", yes)])
        assert bool_input("do something? ")

    for no in ["no", "n", "No", "False", "false"]:
        input_calls = iter([("do something?", no)])
        assert not bool_input("do something? ")

    input_calls = iter([("continue:", "maybe"), ("continue:", "yes")])
    assert bool_input("continue:")


def test_choose_wheel(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unit test for choose_wheel function."""

    #
    # Non-interactive cases
    #

    with pytest.raises(FileNotFoundError, match="No wheels found"):
        choose_wheel(tmp_path)

    with pytest.raises(FileNotFoundError, match="No wheels found"):
        choose_wheel(tmp_path, interactive=True, choose_first=False)

    wheel1 = tmp_path.joinpath("wheel1.whl")
    wheel1.write_bytes(b'')

    assert choose_wheel(tmp_path) == wheel1
    assert choose_wheel(tmp_path, interactive=True, choose_first=True) == wheel1

    time.sleep(0.01)  # wait to ensure mod time is later
    wheel2 = tmp_path.joinpath("wheel2.whl")
    wheel2.write_bytes(b'')

    with pytest.raises(FileExistsError, match="multiple wheels"):
        choose_wheel(tmp_path)

    assert choose_wheel(tmp_path, choose_first=True) == wheel2

    #
    # Interactive cases
    #

    inputs: Deque[str] = deque()

    def fake_input(prompt: str) -> str:
        print(prompt)
        return inputs.popleft()

    monkeypatch.setattr("builtins.input", fake_input)

    with pytest.raises(SystemExit):
        inputs.append("quit")
        choose_wheel(tmp_path, interactive=True)

    out, err = capsys.readouterr()
    assert not err
    assert "[0] wheel2.whl" in out
    assert "[1] wheel1.whl" in out
    assert "build" not in out

    inputs.append("bad-option")
    inputs.append("1")
    wheel = choose_wheel(tmp_path, interactive=True, can_build=True)

    assert wheel == wheel1
    out, err = capsys.readouterr()
    assert "[build] build wheel" in out
    assert "[no-dep] build wheel with --no-deps" in out
