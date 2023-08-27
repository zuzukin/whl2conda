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
Unit tests for whl2conda.stdrename module
"""

from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path
from typing import List
from urllib.error import HTTPError

import pytest

from whl2conda.stdrename import (
    NAME_MAPPINGS_DOWNLOAD_URL,
    NotModified,
    download_mappings,
    load_std_renames,
    update_renames_file,
)


def test_download_mappings() -> None:
    """Unit test for download_mappings function"""
    try:
        d = download_mappings()
    except HTTPError as err:
        assert not isinstance(err, NotModified)
        pytest.skip(f"download url not accessible?: {err}")

    assert d.mappings
    assert d.url == NAME_MAPPINGS_DOWNLOAD_URL
    assert d.etag
    assert d.date
    assert d.date == d.headers["Date"]
    assert d.etag == d.headers["ETag"].strip('"')

    with pytest.raises(NotModified):
        download_mappings(etag=d.etag)

    mappings = d.mappings
    assert isinstance(mappings, list)
    for entry in mappings:
        assert isinstance(entry, dict)
        assert "pypi_name" in entry
        assert "conda_name" in entry

    with pytest.raises(HTTPError) as exc_info:
        download_mappings(url=NAME_MAPPINGS_DOWNLOAD_URL + "xxx")

    assert exc_info.value.status == HTTPStatus.NOT_FOUND  # type: ignore


def test_load_std_renames(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit test for load_std_renames function"""

    # set fake home dir for ~
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert Path("~").expanduser().absolute() == tmp_path

    # Don't bother with actual update, just make sure it is called.
    fake_update_path: List[Path] = []

    def fake_update(fpath: Path) -> bool:
        fake_update_path.clear()
        fake_update_path.append(fpath)
        return True

    monkeypatch.setattr("whl2conda.stdrename.update_renames_file", fake_update)

    renames = load_std_renames()
    assert isinstance(renames, dict)
    assert renames["torch"] == "pytorch"
    assert renames["numpy-quaternion"] == "quaternion"
    assert list(renames.keys()) == sorted(renames.keys())
    assert "$etag" in renames
    assert "$date" in renames
    assert "$source" in renames
    assert not fake_update_path

    local_renames_file = tmp_path.joinpath(".config", "whl2conda", "stdrename.json")
    assert local_renames_file.is_file()

    renames2 = load_std_renames(update=True)
    assert renames == renames2
    assert fake_update_path[0] == local_renames_file


def test_update_renames_file(tmp_path: Path) -> None:
    """Unit test for update_renames_file function"""
    renames_file = tmp_path.joinpath("renames.json")
    try:
        assert update_renames_file(renames_file)
    except HTTPError as err:
        pytest.skip(f"download url not accessible?: {err}")

    assert renames_file.is_file()

    renames = json.loads(renames_file.read_text("utf8"))
    assert isinstance(renames, dict)
    assert renames["$etag"]
    assert renames["$source"] == NAME_MAPPINGS_DOWNLOAD_URL
    assert renames["$date"]
    etag = renames["$etag"]

    assert len(renames) > 3
    for key, val in renames.items():
        if not key.startswith("$"):
            assert key != val

    # nothing changed (unless we got really unlucky)
    mod_time = renames_file.stat().st_mtime_ns
    if update_renames_file(renames_file):
        # this is highly unlikely but possible
        renames2 = json.loads(renames_file.read_text("utf8"))
        etag2 = renames2["$"]
        assert etag2 != etag
        assert renames_file.stat().st_mtime_ns > mod_time
    else:
        assert renames_file.stat().st_mtime_ns == mod_time

    with pytest.raises(HTTPError):
        update_renames_file(
            renames_file,
            url=NAME_MAPPINGS_DOWNLOAD_URL + "xyz",
        )
