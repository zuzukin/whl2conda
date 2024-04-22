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
Unit tests for whl2conda.settings module
"""

import tempfile
from pathlib import Path
from typing import Any

import pytest

from whl2conda.impl.pyproject import CondaPackageFormat
from whl2conda.settings import Whl2CondaSettings, _fromidentifier

# ruff: noqa: F811


def test_Whl2CondaSettings(tmp_path: Path):
    """
    Unit test for Whl2CondaSettings class
    """

    settings = Whl2CondaSettings()

    # check defaults
    assert settings.settings_file
    assert settings.auto_update_std_renames is False
    assert settings.conda_format is CondaPackageFormat.V2
    assert settings.pypi_indexes == {}

    check_settings(settings, tmp_path)

    settings.auto_update_std_renames = True
    assert settings.auto_update_std_renames is True
    settings.auto_update_std_renames = "Yes"
    assert settings.auto_update_std_renames is True
    with pytest.raises(ValueError):
        settings.auto_update_std_renames = "bogus"

    settings.conda_format = "V1"
    assert settings.conda_format is CondaPackageFormat.V1

    settings.pypi_indexes["somewhere"] = "https://somewhere.com/pypi"
    assert settings.pypi_indexes == {"somewhere": "https://somewhere.com/pypi"}
    check_settings(settings, tmp_path)


def test_settings_get() -> None:
    """Unit test for Whl2CondaSettings.get method"""
    settings = Whl2CondaSettings()

    settings.auto_update_std_renames = True
    assert settings.get("auto-update-std-renames") is True

    with pytest.raises(KeyError, match=r"Unknown settings key 'barf'"):
        settings.get("barf")

    assert settings.get("pypi_indexes") is settings.pypi_indexes

    with pytest.raises(KeyError, match="'pypi-indexes.somewhere' is not set"):
        settings.get("pypi-indexes.somewhere")

    with pytest.raises(KeyError, match="Bad settings key 'conda_format.value'"):
        settings.get("conda_format.value")

    settings.pypi_indexes["somewhere"] = "https://somewhere.com/pypi"
    assert settings.get("pypi_indexes.somewhere") == "https://somewhere.com/pypi"


def test_settings_set(tmp_path: Path) -> None:
    """Unit test for Whl2CondaSettings.set method"""
    settings = Whl2CondaSettings()

    settings.set("auto-update-std-renames", True)
    assert settings.auto_update_std_renames is True

    settings.set("auto-update-std-renames", "no")
    assert settings.auto_update_std_renames is False

    settings.set("pypi-indexes.somewhere", "https://somewhere.com/pypi")
    assert settings.pypi_indexes == {"somewhere": "https://somewhere.com/pypi"}

    settings.set("pypi-indexes.somewhere-else", "https://other.com/pypi")
    assert settings.pypi_indexes == {
        "somewhere": "https://somewhere.com/pypi",
        "somewhere-else": "https://other.com/pypi",
    }

    settings.set("pypi-indexes.somewhere", "https://whoops")
    assert settings.pypi_indexes == {
        "somewhere": "https://whoops",
        "somewhere-else": "https://other.com/pypi",
    }

    with pytest.raises(KeyError, match="'conda_format' is not a dictionary"):
        settings.set("conda_format.value", "V2")

    check_settings(settings, tmp_path)


def test_settings_unset(tmp_path: Path) -> None:
    """
    Unit test for Whl2CondaSettings.unset method
    """
    settings = Whl2CondaSettings()

    settings.conda_format = "V1"
    assert settings.conda_format is CondaPackageFormat.V1

    settings.pypi_indexes["somewhere"] = "https://somewhere.com/pypi"
    settings.pypi_indexes["nowhere"] = "https://nowhere.com/pypi"

    settings.unset("pypi-indexes.somewhere")
    assert settings.pypi_indexes == {"nowhere": "https://nowhere.com/pypi"}

    settings.unset("pypi-indexes")
    assert settings.pypi_indexes == {}

    settings.unset("conda_format")
    assert settings.conda_format is CondaPackageFormat.V2

    # no error
    settings.unset("pypi-indexes.notset")

    with pytest.raises(KeyError, match="'conda_format' is not a dictionary"):
        settings.unset("conda_format.value")


def check_settings(settings: Whl2CondaSettings, tmp_path: Path) -> None:
    """
    Check invariants on Whl2CondaSettings instance
    """
    fname = tempfile.mktemp(prefix="whl2conda", suffix=".json", dir=tmp_path)
    settings.save(fname)
    settings2 = Whl2CondaSettings.from_file(fname)
    assert settings2.settings_file == Path(fname)
    assert settings == settings2

    for name in Whl2CondaSettings._fieldnames:
        assert settings.get(_fromidentifier(name)) == getattr(settings, name)

    settings_dict = settings.to_dict()

    def _check_dict(d: dict[str, Any], prefix="") -> None:
        for k, v in d.items():
            key = f"{prefix}{k}"
            if isinstance(v, dict):
                _check_dict(v, prefix=key + ".")
            else:
                assert settings.get(key) == v

    _check_dict(settings_dict)
