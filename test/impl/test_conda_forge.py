#  Copyright 2026 Christopher Barber
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
Unit tests for whl2conda.impl.conda_forge
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest

from whl2conda.impl import conda_forge
from whl2conda.impl.conda_forge import (
    CondaForgeBuild,
    download_conda_forge_package,
    native_conda_subdir,
    query_conda_forge_builds,
)

FAKE_FILES = [
    {
        "basename": "noarch/foo-1.0-pyhd8ed1ab_0.conda",
        "version": "1.0",
        "download_url": "//api.anaconda.org/download/conda-forge/foo/1.0/noarch/foo-1.0-pyhd8ed1ab_0.conda",
        "attrs": {"build": "pyhd8ed1ab_0", "build_number": 0, "subdir": "noarch"},
    },
    {
        "basename": "osx-arm64/foo-1.1-py312h1234567_2.conda",
        "version": "1.1",
        "download_url": "https://example.com/osx-arm64/foo-1.1-py312h1234567_2.conda",
        "attrs": {
            "build": "py312h1234567_2",
            "build_number": 2,
            "subdir": "osx-arm64",
        },
    },
]


def test_query_conda_forge_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whitebox test of anaconda.org files query"""
    urls: list[str] = []

    def fake_urlopen(url: str, timeout: float = 0.0):
        urls.append(url)
        return io.BytesIO(json.dumps(FAKE_FILES).encode("utf8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    builds = query_conda_forge_builds("foo")
    assert urls == ["https://api.anaconda.org/package/conda-forge/foo/files"]
    assert len(builds) == 2

    noarch, arm64 = builds
    assert noarch == CondaForgeBuild(
        name="foo",
        version="1.0",
        build="pyhd8ed1ab_0",
        build_number=0,
        subdir="noarch",
        filename="foo-1.0-pyhd8ed1ab_0.conda",
        url="https://api.anaconda.org/download/conda-forge/foo/1.0/noarch/foo-1.0-pyhd8ed1ab_0.conda",
    )
    assert arm64.subdir == "osx-arm64"
    assert arm64.build_number == 2
    assert arm64.url.startswith("https://example.com/")


def test_download_conda_forge_package(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Whitebox test of package download"""

    def fake_urlopen(url: str, timeout: float = 0.0):
        assert url == "https://example.com/foo-1.1-py312h1234567_2.conda"
        return io.BytesIO(b"package-bytes")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    build = CondaForgeBuild(
        name="foo",
        version="1.1",
        build="py312h1234567_2",
        build_number=2,
        subdir="osx-arm64",
        filename="foo-1.1-py312h1234567_2.conda",
        url="https://example.com/foo-1.1-py312h1234567_2.conda",
    )
    target = download_conda_forge_package(build, tmp_path / "cache")
    assert target == tmp_path / "cache" / build.filename
    assert target.read_bytes() == b"package-bytes"


def test_native_conda_subdir(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit test for native_conda_subdir"""
    assert re.fullmatch(r"(linux|osx|win)-\w+", native_conda_subdir())

    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr(conda_forge.platform, "machine", lambda: "x86_64")
    assert native_conda_subdir() == "linux-64"
    monkeypatch.setattr(conda_forge.platform, "machine", lambda: "aarch64")
    assert native_conda_subdir() == "linux-aarch64"

    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(conda_forge.platform, "machine", lambda: "arm64")
    assert native_conda_subdir() == "osx-arm64"
    monkeypatch.setattr(conda_forge.platform, "machine", lambda: "x86_64")
    assert native_conda_subdir() == "osx-64"

    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(conda_forge.platform, "machine", lambda: "amd64")
    assert native_conda_subdir() == "win-64"
