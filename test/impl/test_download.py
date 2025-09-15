#  Copyright 2024-2025 Christopher Barber
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
Unit tests for whl2conda.impl.download module
"""

import argparse
import subprocess
from pathlib import Path
from textwrap import dedent

import pytest

from whl2conda.impl.download import download_dist, lookup_pypi_index
from whl2conda.settings import settings


def test_lookup_pypi_index(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Unit test for lookup_pypi_index function"""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    assert lookup_pypi_index("foo") == "foo"

    pypirc_file = home / ".pypirc"
    pypirc_file.write_text(
        dedent(
            """
        [foo]
        repository = foo-pypirc
        """
        )
    )
    assert pypirc_file == Path("~/.pypirc").expanduser()

    assert lookup_pypi_index("foo") == "foo-pypirc"
    assert lookup_pypi_index("bar") == "bar"

    settings.pypi_indexes["foo"] = "foo-settings"

    assert lookup_pypi_index("foo") == "foo-settings"


def test_download_wheel_whitebox(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """
    Whitebox test of download_wheel function. This does not do any
    downloading and just tests that the expected pip command is
    issued.
    """
    n_wheels = 1
    download_args: list[argparse.Namespace] = []
    stderr = b""

    def call_pip_download(cmd: list[str], **_kwargs) -> subprocess.CompletedProcess:
        """
        Fake implementation of check_call for pip download
        """
        assert cmd[:2] == ["pip", "download"]

        parser = argparse.ArgumentParser()
        binary_opts = parser.add_mutually_exclusive_group()
        binary_opts.add_argument("--only-binary")
        binary_opts.add_argument("--no-binary")
        parser.add_argument("--no-deps", action="store_true")
        parser.add_argument("--ignore-requires-python", action="store_true")
        parser.add_argument("--implementation")
        parser.add_argument("-i", "--index")
        parser.add_argument("--no-build-isolation", action="store_true")
        parser.add_argument("-d", "--dest")
        parser.add_argument("spec")

        parsed = parser.parse_args(cmd[2:])

        download_args[:] = [parsed]
        assert parsed.only_binary == ":all:" or parsed.no_binary == ":all:"
        assert parsed.no_deps
        assert parsed.ignore_requires_python
        if parsed.no_binary:
            assert not parsed.no_build_isolation
        assert parsed.implementation == "py"
        get_sdist = bool(parsed.no_binary)

        download_tmpdir = Path(parsed.dest)
        assert download_tmpdir.is_dir()

        ext = ".tar.gz" if get_sdist else ".whl"
        if n_wheels > 0:
            fake_dist_file = download_tmpdir / f"fake{ext}"
            fake_dist_file.write_text(parsed.spec)
        for n in range(1, n_wheels):
            fake_dist_file = download_tmpdir / f"fake{n}{ext}"
            fake_dist_file.write_text(parsed.spec)

        return subprocess.CompletedProcess(cmd, 0, "", stderr)

    monkeypatch.setattr(subprocess, "run", call_pip_download)

    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.chdir(home_dir)
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("USERPROFILE", str(home_dir))
    assert Path.home() == home_dir

    whl = download_dist("pylint")
    assert whl.parent == home_dir
    assert whl.name == "fake.whl"
    assert whl.is_file()
    assert whl.read_text() == "pylint"
    assert download_args[0].spec == "pylint"
    assert download_args[0].index is None
    out, err = capsys.readouterr()
    assert not out and not err

    sdist = download_dist("pylint", sdist=True)
    assert sdist.parent == home_dir
    assert sdist.name == "fake.tar.gz"
    assert sdist.is_file()
    assert sdist.read_text() == "pylint"
    assert download_args[0].spec == "pylint"
    assert download_args[0].index is None
    out, err = capsys.readouterr()
    assert not out and not err

    somewhere_from_pypirc = "https://pypirc.somewhere.com/pypi/"

    pypirc_file = home_dir / ".pypirc"
    pypirc_file.write_text(
        dedent(
            f"""
        [somewhere]
        repository = {somewhere_from_pypirc}
        """
        )
    )
    assert pypirc_file == Path("~/.pypirc").expanduser()

    alt_dir = tmp_path / "alt"
    assert not alt_dir.exists()

    whl = download_dist("foobar >=1.2.3", index="alt-index", into=alt_dir)
    assert whl.parent == alt_dir
    assert whl.name == "fake.whl"
    assert whl.is_file()
    assert whl.read_text() == "foobar >=1.2.3"
    assert download_args[0].index == "alt-index"

    out, err = capsys.readouterr()
    assert not out
    assert not err

    whl = download_dist("foo", index="somewhere")
    assert download_args[0].index == somewhere_from_pypirc

    somewhere_from_settings = "https://settings.somewhere.com/pypi/"
    settings.pypi_indexes["somewhere"] = somewhere_from_settings
    whl = download_dist("foo", index="somewhere")
    assert download_args[0].index == somewhere_from_settings

    n_wheels = 0
    with pytest.raises(FileNotFoundError, match="No wheels downloaded"):
        download_dist("bar")

    n_wheels = 2
    with pytest.raises(AssertionError, match="More than one wheel downloaded"):
        download_dist("bar")


def test_download(tmp_path: Path) -> None:
    """
    Test actual downloads
    """
    try:
        whl = download_dist("tomlkit", into=tmp_path)
        assert whl.is_file()
        assert whl.name.startswith("tomlkit")
        assert whl.name.endswith(".whl")
        assert whl.parent == tmp_path
    except ConnectionError:
        pytest.skip("Cannot connect to pypi index ")

    try:
        sdist = download_dist("tomlkit", into=tmp_path, sdist=True)
        assert sdist.is_file()
        assert sdist.name.startswith("tomlkit")
        assert sdist.name.endswith(".tar.gz")
        assert sdist.parent == tmp_path
    except ConnectionError:
        pytest.skip("Cannot connect to pypi index ")
