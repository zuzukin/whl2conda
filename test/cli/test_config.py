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
Unit tests for `whl2conda config` CLI
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.error import URLError

import pytest

from whl2conda.cli import main
from whl2conda.cli.config import update_std_renames
from whl2conda.stdrename import user_stdrenames_path


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

    monkeypatch.setattr("whl2conda.stdrename.update_renames_file", _fake_update)
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
