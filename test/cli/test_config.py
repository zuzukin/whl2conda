#  Copyright 2023-2024 Christopher Barber
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
Unit tests for `whl2conda config` CLI
"""

from __future__ import annotations

# standard
import json
from pathlib import Path
from typing import Optional
from urllib.error import URLError

# third party
from platformdirs import user_config_path
import pytest

# this project
from whl2conda.cli import main
from whl2conda.cli.config import update_std_renames
from whl2conda.api.stdrename import user_stdrenames_path
from whl2conda.impl.pyproject import CondaPackageFormat
from whl2conda.settings import Whl2CondaSettings, settings


# pylint: disable=too-many-statements
def test_update_std_renames(
    capsys: pytest.CaptureFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unit test for update_std_renames internal method"""

    fake_update_result = False
    expected_dry_run = True
    fake_exception: Optional[Exception] = None

    # pylint: disable=unused-argument
    def _fake_update(
        renames_file: Path, *, url: str = "", dry_run: bool = False
    ) -> bool:
        if fake_exception is not None:
            raise fake_exception
        assert dry_run is expected_dry_run
        return fake_update_result

    monkeypatch.setattr("whl2conda.api.stdrename.update_renames_file", _fake_update)
    monkeypatch.setattr("whl2conda.cli.config.update_renames_file", _fake_update)

    file = tmp_path.joinpath("stdrename.json")
    with pytest.raises(SystemExit):
        update_std_renames(file, dry_run=True)
    out, err = capsys.readouterr()
    assert not err
    assert f"Updating {file}" in out
    assert "No changes" in out

    fake_update_result = True
    with pytest.raises(SystemExit):
        update_std_renames(file, dry_run=True)
    out, err = capsys.readouterr()
    assert not err
    assert f"Updating {file}" in out
    assert "Update available" in out

    expected_dry_run = False
    with pytest.raises(SystemExit):
        update_std_renames(file, dry_run=False)
    out, err = capsys.readouterr()
    assert not err
    assert f"Updating {file}" in out
    assert "Updated" in out

    fake_update_result = False
    with pytest.raises(SystemExit):
        update_std_renames(file, dry_run=False)
    out, err = capsys.readouterr()
    assert not err
    assert f"Updating {file}" in out
    assert "No changes" in out

    fake_exception = URLError("could not connect")
    with pytest.raises(SystemExit) as exc_info:
        update_std_renames(file, dry_run=False)
    assert exc_info.value.code != 0
    out, err = capsys.readouterr()
    assert f"Updating {file}" in out
    assert "Cannot download" in err

    #
    # test command line
    #

    for var in ["HOME", "USERPROFILE"]:
        monkeypatch.setenv(var, str(tmp_path))

    renames_file = user_stdrenames_path()
    assert renames_file.relative_to(tmp_path)
    assert not renames_file.exists()

    fake_exception = None
    expected_dry_run = False
    fake_update_result = True

    with pytest.raises(SystemExit) as exc_info:
        main(["config", "--update-std-renames"])
    assert exc_info.value.code == 0
    out, err = capsys.readouterr()
    assert not err
    assert f"Updating {renames_file}" in out
    assert "Updated" in out

    fake_update_result = False
    expected_dry_run = True
    with pytest.raises(SystemExit) as exc_info:
        main(["config", "--update-std-renames", "--dry-run"])
    assert exc_info.value.code == 0
    out, err = capsys.readouterr()
    assert not err
    assert f"Updating {renames_file}" in out
    assert "No changes" in out

    expected_dry_run = False
    with pytest.raises(SystemExit) as exc_info:
        main(["config", "--update-std-renames", "here.json"])
    assert exc_info.value.code == 0
    out, err = capsys.readouterr()
    assert not err
    assert "Updating here.json" in out


def test_generate_pyproject(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """Unit test for whl2conda config --generate-pyproject

    More detailed tests of the output are in test_pyproject
    """
    main(["config"])  # does nothing

    main(["config", "--generate-pyproject"])
    out, err = capsys.readouterr()
    assert '[tool.whl2conda]' in out
    assert not err

    main(["config", "--generate-pyproject", "out"])
    out, err = capsys.readouterr()
    assert '[tool.whl2conda]' in out
    assert not err

    main(["config", "--generate-pyproject", "stdout"])
    out, err = capsys.readouterr()
    assert '[tool.whl2conda]' in out
    assert not err

    main(["config", "--generate-pyproject", str(tmp_path)])
    pyproj_file = tmp_path.joinpath("pyproject.toml")
    assert pyproj_file.is_file()
    contents = pyproj_file.read_text("utf8")
    assert '[tool.whl2conda]' in contents
    out, err = capsys.readouterr()
    assert not out
    assert not err

    alt_toml = tmp_path.joinpath("alt.toml")
    main(["config", "--generate-pyproject", str(alt_toml)])
    assert alt_toml.is_file()
    contents = alt_toml.read_text("utf8")
    assert '[tool.whl2conda]' in contents
    out, err = capsys.readouterr()
    assert not out
    assert not err

    with pytest.raises(SystemExit):
        main(["config", "--generate-pyproject", "foo.txt"])
    out, err = capsys.readouterr()
    assert "Cannot write to non .toml file" in err


@pytest.fixture
def tmp_settings_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    # override home directory
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home.resolve()))
    monkeypatch.setenv("USERPROFILE", str(home.resolve()))

    # point settings at location in fake home dir
    config_path = user_config_path("whl2conda")
    settings_file = config_path / settings.SETTINGS_FILENAME
    settings_file.relative_to(home) # no ValueError
    settings.load(settings_file)
    assert settings.settings_file == settings_file
    assert not settings_file.exists()

    return settings_file


def test_config_show(
    tmp_settings_file: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """
    Test config --show and --show-sources
    """

    main(["config", "--show"])
    out, err = capsys.readouterr()
    assert not err
    assert json.loads(out) == settings.to_dict()

    main(["config", "--show-sources"])
    out, err = capsys.readouterr()
    sourceheader, out = out.split("\n", maxsplit=1)
    assert not err
    assert str(settings.settings_file) in sourceheader
    assert json.loads(out) == settings.to_dict()

    main(["config", "--show", "conda-format"])
    out, err = capsys.readouterr()
    assert not err
    assert out.strip() == 'conda-format: ".conda"'

    main(["config", "--show", "auto-update-std-renames", "conda_format"])
    out, err = capsys.readouterr()
    assert not err
    line1, line2 = out.strip().split("\n", maxsplit=1)
    assert line1 == 'auto-update-std-renames: false'
    assert line2 == 'conda-format: ".conda"'


def test_config_set(
    tmp_settings_file: Path,
) -> None:
    """
    Test config --set
    """

    # dry-run: settings changed in memory but not saved
    main(["config", "--set", "conda-format", "V1", "--dry-run"])
    assert settings.conda_format is CondaPackageFormat.V1
    assert not tmp_settings_file.exists()

    main(["config", "--set", "conda-format", "V2", "--dry-run"])
    assert settings.conda_format is CondaPackageFormat.V2
    assert not tmp_settings_file.exists()

    main(["config", "--set", "conda-format", "V1"])
    assert settings.conda_format is CondaPackageFormat.V1
    assert tmp_settings_file.exists()

    settings2 = Whl2CondaSettings.from_file(tmp_settings_file)
    assert settings2.conda_format is CondaPackageFormat.V1


def test_config_remove(
    tmp_settings_file: Path,
) -> None:
    """
    Test config --remove
    """
    assert not tmp_settings_file.exists()
    main(["config", "--set", "conda-format", "V1"])
    main(["config", "--set", "pypi-indexes.foo", "https://foo.com/pypi"])
    main(["config", "--set", "pypi-indexes.bar", "https://bar.com/pypi"])
    assert tmp_settings_file.exists()
    assert settings.conda_format is CondaPackageFormat.V1
    assert settings.pypi_indexes["foo"] == "https://foo.com/pypi"
    assert settings.pypi_indexes["bar"] == "https://bar.com/pypi"

    main(["config", "--remove", "conda-format", "--dry-run"])
    assert settings.conda_format is CondaPackageFormat.V2  # prev default
    settings2 = Whl2CondaSettings.from_file(tmp_settings_file)
    assert settings2.conda_format is CondaPackageFormat.V1

    main(["config", "--remove", "conda-format"])
    assert settings.conda_format is CondaPackageFormat.V2  # prev default
    settings2 = Whl2CondaSettings.from_file(tmp_settings_file)
    assert settings2.conda_format is CondaPackageFormat.V2

    main(["config", "--remove", "pypi-indexes.foo"])
    settings2 = Whl2CondaSettings.from_file(tmp_settings_file)
    assert settings.pypi_indexes == dict(bar="https://bar.com/pypi")


def test_override_settings(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """
    Test whl2conda --settings option
    """

    new_path = tmp_path / "settings.json"
    main(["--settings", str(new_path), "config", "--show-sources"])
    out, err = capsys.readouterr()

    assert not err
    line1, rest = out.split("\n", maxsplit=1)
    assert str(new_path) in line1
    assert settings.settings_file == new_path
