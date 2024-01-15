#  Copyright 2024 Christopher Barber
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
Support for downloading wheels
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

__all__ = [
    "download_wheel",
]


def download_wheel(
    spec: str,
    index: str = "",
    into: Optional[Path] = None,
) -> Path:
    """
    Downloads wheel with given specification from pypi index.

    Args:
        spec: requirement specifier for wheel to download: package name and optional version
        index: URL of index from which to download. Defaults to pypi.org
        into: directory into which wheel will be download. Defaults to current directory.

    Returns:
        Path of downloaded file.
    """

    with tempfile.TemporaryDirectory(
        dir=Path.cwd(), prefix="whl2conda-download-"
    ) as tmpdirname:
        tmpdir = Path(tmpdirname)
        cmd = [
            "pip",
            "download",
            "--only-binary",  # TODO support building from a source distribution
            ":all:",
            "--no-deps",
            "--ignore-requires-python",  # TODO: support specific python version
            "--implementation",
            "py",
        ]
        if index:
            cmd.extend(["-i", index])
        cmd.extend(["-d", str(tmpdirname)])
        cmd.append(spec)

        p = subprocess.run(cmd, check=True, stderr=subprocess.PIPE)
        if p.stderr:
            print(p.stderr, file=sys.stderr)

        wheels = list(tmpdir.glob("*.whl"))

        # these should not happen if check_call does not throw, but check anyway
        if not wheels:
            raise FileNotFoundError("No wheels downloaded")
        if len(wheels) > 1:
            raise AssertionError(
                f"More than one wheel downloaded: {list(w.name for w in wheels)}"
            )

        tmp_wheel = wheels[0]
        out_dir = into or Path.cwd()
        out_dir.mkdir(parents=True, exist_ok=True)
        wheel = out_dir / tmp_wheel.name
        shutil.copyfile(tmp_wheel, wheel)

        return wheel
