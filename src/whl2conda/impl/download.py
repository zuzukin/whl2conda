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

import configparser
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from ..settings import settings

__all__ = [
    "download_dist",
    "lookup_pypi_index",
]


def lookup_pypi_index(index: str) -> str:
    """
    Translate index aliases

    First looks for exact match in user settings
    pyproject_indexes table and then looks for
    matching entry in the ~/.pypirc file.

    Otherwise returns the original string
    """
    if new_index := settings.pypi_indexes.get(index):
        return new_index

    pypirc_path = Path("~/.pypirc").expanduser()
    if pypirc_path.exists():
        pypirc = configparser.ConfigParser()
        pypirc.read(pypirc_path)
        try:
            return pypirc[index]["repository"]
        except Exception:
            pass
    return index


def download_dist(
    spec: str,
    index: str = "",
    into: Optional[Path] = None,
    *,
    sdist: bool = False,
) -> Path:
    """
    Downloads wheel or sdist with given specification from pypi index.

    Args:
        spec: requirement specifier for package to download: package name and optional version
        index: URL of index from which to download. Defaults to pypi.org
        into: directory into which distribution will be download. Defaults to current directory.
        sdist: if True, download source distribution instead of wheel

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
            "--no-binary" if sdist else "--only-binary",
            ":all:",
            "--no-deps",
            "--ignore-requires-python",  # TODO: support specific python version
            "--implementation",
            "py",
        ]
        if index:
            index = lookup_pypi_index(index)
        if index:
            cmd.extend(["-i", index])
        cmd.extend(["-d", str(tmpdirname)])
        cmd.append(spec)

        try:
            subprocess.run(cmd, check=True, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as ex:
            if b"ConnectionError" in ex.stderr:
                raise ConnectionError(
                    f"Cannot connect to {index or 'pypi'}: {ex.stderr.decode().strip()}"
                ) from ex
            raise FileNotFoundError(
                f"Cannot download {spec} from {index or 'pypi'}: {ex.stderr.decode().strip()}"
            ) from ex

        dist_glob = "*.tar.gz" if sdist else "*.whl"
        dist_type = "sdist" if sdist else "wheel"

        dists = list(tmpdir.glob(dist_glob))

        # these should not happen if check_call does not throw, but check anyway
        if not dists:
            raise FileNotFoundError(f"No {dist_type}s downloaded")
        if len(dists) > 1:
            raise AssertionError(
                f"More than one {dist_type} downloaded: {list(w.name for w in dists)}"
            )

        tmp_wheel = dists[0]
        out_dir = into or Path.cwd()
        out_dir.mkdir(parents=True, exist_ok=True)
        dist = out_dir / tmp_wheel.name
        shutil.copyfile(tmp_wheel, dist)

        return dist
