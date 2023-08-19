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

import io
import sys
from typing import Iterator, Tuple

import pytest

import whl2conda.prompt
from whl2conda.prompt import is_interactive, bool_input


def test_is_interactive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit test for is_interactive"""
    # whitebox test
    with io.StringIO() as f:
        assert not f.isatty()
        monkeypatch.setattr(sys, "__stdin__", f)
        assert not is_interactive()
        monkeypatch.setattr(f, "isatty", lambda: True)
        assert is_interactive()


def test_bool_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit test for bool_input function"""
    if is_interactive():
        monkeypatch.setattr(whl2conda.prompt, "is_interactive", lambda: False)
    with pytest.raises(AssertionError):
        bool_input("")
    monkeypatch.undo()

    if not is_interactive():
        monkeypatch.setattr(whl2conda.prompt, "is_interactive", lambda: True)

    input_calls: Iterator[Tuple[str, str]] = iter(())

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
