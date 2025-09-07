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

import email.utils
import json
import os
import platform
import time
from email.utils import parsedate_to_datetime
from http import HTTPStatus
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest
from platformdirs import user_cache_path

from whl2conda.api.stdrename import (
    NAME_MAPPINGS_DOWNLOAD_URL,
    NotModified,
    download_mappings,
    load_std_renames,
    update_renames_file,
    user_stdrenames_path,
    DownloadedMappings,
)


def test_download_mappings() -> None:
    """Unit test for download_mappings function"""
    try:
        d = download_mappings()
    except (HTTPError, URLError) as err:
        assert not isinstance(err, NotModified)
        pytest.skip(f"download url not accessible?: {err}")

    assert d.mappings
    assert d.url == NAME_MAPPINGS_DOWNLOAD_URL
    assert d.etag
    assert d.date
    assert d.date == parsedate_to_datetime(d.headers["Date"])
    assert d.etag == d.headers["ETag"].strip('"')
    assert d.expires == parsedate_to_datetime(d.headers["Expires"])
    assert d.max_age > 0

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

    # Test properties
    del d.headers["Etag"]
    assert d.etag == ""
    del d.headers["Cache-Control"]
    assert d.max_age == (d.expires - d.date).seconds  # type: ignore[operator]
    now = email.utils.localtime()
    del d.headers["Date"]
    later = email.utils.localtime()
    assert (d.expires - later).seconds <= d.max_age <= (d.expires - now).seconds  # type: ignore[operator]
    del d.headers["Expires"]
    assert d.max_age == -1
    d.headers.add_header("Cache-Control", "max-age=42")
    assert d.max_age == 42
    d.headers.replace_header("Cache-Control", "something, s-max-age=23")
    assert d.max_age == 23
    d.headers.replace_header("Cache-Control", "no-cache")
    assert d.max_age == -1


def test_load_std_renames(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit test for load_std_renames function"""

    # set fake home dir for ~
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert Path("~").expanduser().absolute() == tmp_path

    # Make sure the cache dir is in our fake home dir
    local_renames_file = user_stdrenames_path()
    # Only check relative path on non-Windows systems to avoid platform-specific path issues
    if platform.system() != "Windows":
        assert os.path.pardir not in os.path.relpath(local_renames_file, tmp_path)
        assert local_renames_file.relative_to(tmp_path)
    assert not local_renames_file.exists()

    # Don't bother with actual update, just make sure it is called.
    fake_update_path: list[Path] = []

    def fake_update(fpath: Path) -> bool:
        fake_update_path.clear()
        fake_update_path.append(fpath)
        return True

    monkeypatch.setattr("whl2conda.api.stdrename.update_renames_file", fake_update)

    renames = load_std_renames()
    assert isinstance(renames, dict)
    assert renames["torch"] == "pytorch"
    assert renames["numpy-quaternion"] == "quaternion"
    assert list(renames.keys()) == sorted(renames.keys())
    assert "$etag" in renames
    assert "$date" in renames
    assert "$source" in renames
    assert not fake_update_path

    assert local_renames_file.is_file()

    renames2 = load_std_renames(update=True)
    assert renames == renames2
    assert fake_update_path[0] == local_renames_file


# pylint: disable=too-many-statements,too-many-locals
def test_update_renames_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit test for update_renames_file function"""
    renames_file = tmp_path.joinpath("renames.json")
    try:
        assert update_renames_file(renames_file)
    except (HTTPError, URLError) as err:
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

    datestr = renames["$date"]
    # temporarily remove date to force use of etags
    del renames["$date"]
    renames_file.write_text(json.dumps(renames, indent=2), "utf8")

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

    renames["$date"] = datestr
    renames_file.write_text(json.dumps(renames, indent=2), "utf8")

    download_invoked = False
    expected_etag = etag
    expected_url = NAME_MAPPINGS_DOWNLOAD_URL

    def fake_download(*, url: str, etag: str):
        assert etag == expected_etag
        assert url == expected_url
        nonlocal download_invoked
        download_invoked = True
        return DownloadedMappings(
            url=url, headers=email.message.EmailMessage(), mappings=()
        )

    monkeypatch.setattr("whl2conda.api.stdrename.download_mappings", fake_download)

    renames["$max-age"] = 99999999
    renames_file.write_text(json.dumps(renames, indent=2), "utf8")
    assert not update_renames_file(renames_file)
    assert not download_invoked

    renames["$date"] = email.utils.formatdate(usegmt=True)
    del renames["$max-age"]
    renames_file.write_text(json.dumps(renames, indent=2), "utf8")
    assert not update_renames_file(renames_file)
    assert not download_invoked

    renames["$max-age"] = "bogus"
    renames_file.write_text(json.dumps(renames, indent=2), "utf8")
    assert not update_renames_file(renames_file)
    assert not download_invoked

    renames["$date"] = email.utils.formatdate(time.time() - 99999, usegmt=True)
    renames_file.write_text(json.dumps(renames, indent=2), "utf8")
    assert update_renames_file(renames_file, dry_run=True)
    assert download_invoked

    # dry run - file not changed
    assert renames == json.loads(renames_file.read_text("utf8"))


def test_user_stdrenames_path() -> None:
    """Test user_stdrenames_path function"""
    path = user_stdrenames_path()
    assert isinstance(path, Path)

    assert path.name == "stdrename.json"
    assert path.parent == user_cache_path("whl2conda")

    # cache should be under user's home directory (except on Windows)
    if platform.system() != "Windows":
        assert path.relative_to(Path("~").expanduser())
