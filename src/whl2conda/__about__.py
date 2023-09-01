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
"""
Static project info
"""

import importlib.resources as res
import sys

# pylint: disable=no-member
if sys.version_info >= (3, 9):  # pragma: no cover
    __version__ = res.files('whl2conda').joinpath("VERSION").read_text().strip()
else:
    __version__ = res.read_text('whl2conda', "VERSION").strip()
