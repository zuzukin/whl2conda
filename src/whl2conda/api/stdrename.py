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
Support for standard pypi to conda renames drawn from conda-forge.

There are files generated automatically by conda-forge bots
that include information about pypi/conda package names. These
are available from:

   https://github.com/regro/cf-graph-countyfair/blob/master/mappings/pypi

This package provides utility functions for downlaading mappings
from that site and extracting a standard pypi to conda name
mapping dictionary.

**NOTE: this module should not be considered stable! The API
may change incompatibly in a future release.**
"""

from __future__ import annotations

import datetime
import email.message
import importlib.resources
import json
import re
import urllib.request
import sys
import time
from email.utils import formatdate, parsedate_to_datetime
from http import HTTPStatus
from pathlib import Path
from typing import NamedTuple, Optional, Sequence, TypedDict, Union
from urllib.error import HTTPError

from platformdirs import user_cache_path

from whl2conda.__about__ import __version__

__all__ = [
    "load_std_renames",
    "update_renames_file",
    "user_stdrenames_path",
]

MAPPINGS_URL = "https://github.com/regro/cf-graph-countyfair/blob/master/mappings/pypi"

RAW_MAPPINGS_URL = (
    "https://raw.githubusercontent.com/regro/cf-graph-countyfair/master/mappings/pypi"
)

NAME_MAPPINGS_FILENAME = "name_mapping.json"

NAME_MAPPINGS_DOWNLOAD_URL = f"{RAW_MAPPINGS_URL}/{NAME_MAPPINGS_FILENAME}"
"""
URL from which automatically generated pypi to conda name mappings are downloaded.
"""

DEFAULT_MIN_EXPIRATION = 300
"""
Default minimum expiration in seconds for cached renames
"""


def parse_datetime(s: str) -> Optional[datetime.datetime]:
    """Parse datetime string from HTTP header

    Returns None if string is empty or time is malformed.
    """
    try:
        return parsedate_to_datetime(s)
    except Exception:  # pylint: disable=broad-exception-caught
        return None


def user_stdrenames_path() -> Path:
    r"""Path to user's cached copy of standard pypi to conda renames file

    The location of this file depends on the operating system:

    * Linux: ~/.cache/whl2conda/stdrename.json
    * MacOS: ~/Library/Caches/whl2conda/stdrename.json
    * Windows: ~\AppData\Local\whl2conda\Cache\stdrename.json
    """
    return user_cache_path("whl2conda").joinpath("stdrename.json")


def load_std_renames(
    *,
    update: bool = False,
) -> dict[str, str]:
    """
    Load standard pypi to conda package rename table.

    A copy of this table is kept in a local a cache
    file (see [user_stdrenames_path][(m).])
    The table will be read from that file, it it exists, otherwise the
    table included in this package will be copied to the
    user cache file.

    Arguments:
        update: if true, this will update the table from online
            list generated from conda-forge and saves it as the
            new cached copy.

    Returns:
        Dictionary of pypi to conda package name mappings. The
        returned dictionary will also contain the entries "$etag",
        "$date" and "$source" taken from the downloaded web file
        from which it was computed.
    """
    # Look for local copy of stdrenames
    local_std_rename_file = user_stdrenames_path()
    if not local_std_rename_file.exists():
        # pylint: disable=no-member
        if sys.version_info >= (3, 9):  # pragma: no cover
            resources = importlib.resources.files('whl2conda.api')
            s = resources.joinpath("stdrename.json").read_text("utf8")
        else:  # pragma: no cover
            s = importlib.resources.read_text(
                "whl2conda.api",
                "stdrename.json",
                encoding="utf",
            )
        local_std_rename_file.parent.mkdir(parents=True, exist_ok=True)
        local_std_rename_file.write_text(s, "utf8")

    if update:
        update_renames_file(local_std_rename_file)

    s = local_std_rename_file.read_text("utf8")
    return json.loads(s)


class NameMapping(TypedDict):
    """Expected format of github name_mapping.json table"""

    pypi_name: str
    conda_name: str
    import_name: str


class DownloadedMappings(NamedTuple):
    """
    Holds downloaded mapping table from github with HTTP headers.
    """

    url: str
    headers: email.message.EmailMessage
    mappings: Sequence[NameMapping]

    @property
    def date(self) -> Optional[datetime.datetime]:
        """Date from header"""
        return parse_datetime(self.datestr)

    @property
    def datestr(self) -> str:
        """Date string from header"""
        return self.headers.get("Date", "")

    @property
    def etag(self) -> str:
        """ETag string from header"""
        return self.headers.get("ETag", "").strip('"')

    @property
    def expires(self) -> Optional[datetime.datetime]:
        """Expires date string frome header"""
        return parse_datetime(self.headers.get("Expires", ""))

    @property
    def max_age(self) -> int:
        """Max age from Cache-Control header

        Max age in seconds from cache control header, or
        else difference between [expires][..] and [date][..] or else -1.
        """
        if cc := self.headers.get("Cache-Control", ""):
            if m := re.search(r"max-age=(\d+)", cc):
                return int(m.group(1))
        if expires := self.expires:
            date = self.date or datetime.datetime.now(datetime.timezone.utc)
            return (expires - date).seconds
        return -1


def process_name_mapping_dict(mappings: DownloadedMappings) -> dict[str, str]:
    """
    Convert name mapping table from github to simple rename table.

    This only returns mappings where the name is different.

    Args:
        mappings: downlaoded mappings

    Returns:
        dictionary mapping pypi to conda package names
    """
    renames: dict[str, str] = {
        "$source": mappings.url,
        "$date": mappings.datestr or formatdate(usegmt=True),
        "$etag": mappings.etag,
        "$max-age": str(max(mappings.max_age, DEFAULT_MIN_EXPIRATION)),
    }
    for entry in mappings.mappings:
        pypi_name = entry.get("pypi_name")
        conda_name = entry.get("conda_name")
        if pypi_name and conda_name and pypi_name != conda_name:
            renames[pypi_name] = conda_name
    return renames


def update_renames_file(
    renames_file: Union[Path, str],
    *,
    url: str = NAME_MAPPINGS_DOWNLOAD_URL,
    min_expiration: int = DEFAULT_MIN_EXPIRATION,
    dry_run: bool = False,
) -> bool:
    """
    Update standard renames file from github if changed

    This will only download new data if the existing
    data has passed its expiration.

    Args:
        renames_file: path to renames file, which does not have to
            exist initially
        url: url of name mapping file to download. This file is
            expected to contain a JSON array of dictionary
            containing "pypi_name" and "conda_name" entries.
        min_expiration: minimum seconds before existing data expires.
            Default is 5 minutes.
        dry_run: does not update the file, but still does download
            and returns True if file would change

    Returns:
        True if file was updated. False if file has not expired yet
        or upstream data has not changed.
    """
    renames_path = Path(renames_file).expanduser()

    etag = ""
    if renames_path.is_file():
        # check expiration information from existing file
        current_renames = json.loads(renames_path.read_text("utf8"))
        if date := parse_datetime(current_renames.get("$date", "")):
            try:
                max_age = int(current_renames.get("$max-age", 0))
            except Exception:  # pylint: disable=broad-exception-caught
                max_age = 0
            max_age = max(min_expiration, max_age)
            if (date.timestamp() + max_age) > time.time():
                # Not expired yet
                return False
        etag = current_renames.get("$etag")

    try:
        downloaded = download_mappings(url=url, etag=etag)
    except NotModified:
        return False

    new_renames = process_name_mapping_dict(downloaded)
    if not dry_run:
        renames_path.parent.mkdir(parents=True, exist_ok=True)
        renames_path.write_text(
            json.dumps(new_renames, sort_keys=True, indent=2),
            encoding="utf8",
        )

    return True


class NotModified(HTTPError):  # pylint: disable=too-many-ancestors
    """Indicates content was not modified"""


def download_mappings(
    url: str = NAME_MAPPINGS_DOWNLOAD_URL,
    *,
    etag: str = "",
    timeout: float = 20.0,
) -> DownloadedMappings:
    """
    Download pypi to conda name mappings from github

    Args:
        url: download url of mappings file on github
        etag: ETag from previous download
        timeout: max seconds to wait for connection

    Returns:
        Mapping table and HTTP headers.

    Raises:
        NotModified: if etag was specified and content has not changed
        HttpError: other HTTP errors (e.g. 404 etc)
        URLError: connection errors
    """

    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"whl2conda/{__version__}"},
    )
    if etag:
        req.add_header("If-None-Match", f'"{etag}"')

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            headers = response.headers
            content = response.read()
            mappings = json.loads(content)
    except HTTPError as err:
        if err.status == HTTPStatus.NOT_MODIFIED:  # type: ignore
            raise NotModified(
                url,
                err.code,
                err.reason,
                err.headers,
                err.fp,
            ) from err
        raise

    return DownloadedMappings(url, headers, mappings)
