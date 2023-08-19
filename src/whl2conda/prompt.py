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
Interactive prompt utilities.
"""
from __future__ import annotations

import sys

__all__ = [
    "bool_input",
    "is_interactive"
]

def is_interactive() -> bool:
    """
    True if input appears to be connected to an interactive terminal
    """
    return sys.__stdin__.isatty()

def bool_input(prompt: str) -> bool:
    """Boolean interactive prompt, accepts y/n, yes/no, true/false"""
    assert is_interactive()
    true_vals = {"y", "yes", "true"}
    false_vals = {"n", "no", "false"}
    while True:
        answer = input(prompt).lower()
        if answer in true_vals:
            return True
        if answer in false_vals:
            return False
