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
Settings for whl2conda.
"""

from __future__ import annotations

# standard
import dataclasses
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Callable, ClassVar, Dict, NamedTuple, Union

# third party
from platformdirs import user_config_path

# this project
from .__about__ import __version__
from .impl.pyproject import CondaPackageFormat

__all__ = ["Whl2CondaSettings", "settings"]


class _FieldDefault(NamedTuple):
    factory: Callable


class _SettingsField:
    """
    Base class for Whl2CondaSettings dataclass
    """

    def __init__(self, *, default):
        if callable(default):
            self._default = _FieldDefault(default)
        else:
            self._default = default

    def __set_name__(self, owner, name):
        self._name = "_" + name

    def __get__(self, obj, type):
        if obj is None:
            return self._default
        return getattr(obj, self._name)

    def __set__(self, obj, value):
        if isinstance(value, _FieldDefault):
            value = value.factory()
        elif isinstance(value, str):
            value = self._convert_from_str(value)
        setattr(obj, self._name, value)

    def __delete__(self, obj):
        self.__set__(obj, self._default)

    def _convert_from_str(self, value: str):
        """
        Maybe overridden to support conversion from string (from command line)
        """
        return value


class _BoolField(_SettingsField):
    """
    Boolean valued field.

    Supports string conversion from true/false, yes/no, y/n
    """

    def __init__(self, *, default: bool = False):
        super().__init__(default=default)

    def _convert_from_str(self, value: str):
        value = value.lower()
        if value in {"true", "t", "yes", "y"}:
            return True
        elif value in {"false", "f", "no", "n"}:
            return False
        else:
            raise ValueError(f"Invalid value {value!r} for bool field")


class _CondaPackageFormatField(_SettingsField):
    """
    CondaPackageFormat valued field
    """

    def __init__(self):
        super().__init__(default=CondaPackageFormat.V2)

    def _convert_from_str(self, value: str):
        return CondaPackageFormat.from_string(value)


def _toidentifier(name: str) -> str:
    """
    Convert name to an identifier (dashes to underscores)
    """
    return name.replace("-", "_")


def _fromidentifier(name: str) -> str:
    """
    Convert name from identifier (underscores to dashes)
    """
    return name.replace("_", "-")


if sys.version_info >= (3, 10):
    # kw_only is not available until 3.10
    dataclass_args: Dict[str, Any] = dict(kw_only=True)
else:
    dataclass_args: Dict[str, Any] = {}


@dataclasses.dataclass(**dataclass_args)
class Whl2CondaSettings:
    """
    User settings for whl2conda.

    These are accessed through the global [settings][(m).] variable.
    """

    SETTINGS_FILENAME: ClassVar[str] = "whl2conda.json"
    """Default base filename for saved settings."""

    DEFAULT_SETTINGS_FILE: ClassVar[Path] = user_config_path() / SETTINGS_FILENAME
    """Default filepath for saved settings."""

    # TODO:
    #   - difftool
    #   - pyproject defaults

    auto_update_std_renames: _BoolField = _BoolField()
    """
    Whether to automatically update the standard renames for operations
    that need them. Default is false.
    """

    conda_format: _CondaPackageFormatField = _CondaPackageFormatField()
    """
    The default output conda package format if not specified. Default is V2.
    """

    pypi_indexes: _SettingsField = _SettingsField(default=dict)
    """
    Dictionary of aliases for pypi package indexes from which wheels can be
    downloaded. Default is empty.
    """

    #
    # Internal attributes
    #

    _settings_file: Path = dataclasses.field(
        default=DEFAULT_SETTINGS_FILE, compare=False
    )
    """
    Location of underlying settings file.
    """

    _fieldnames: ClassVar[frozenset[str]] = frozenset()
    """
    Set of public field names.
    """

    @property
    def settings_file(self) -> Path:
        """
        Settings file for this settings object.

        Set from [from_file][..] constructor or else will be
        [DEFAULT_SETTINGS_FILE][(c).].
        """
        return self._settings_file

    #
    # Settings access/modification methods
    #

    def to_dict(self) -> dict[str, Any]:
        """
        Return dictionary containing public settings data.
        """
        return {
            k: v for k, v in dataclasses.asdict(self).items() if not k.startswith("_")
        }

    def get(self, key: str) -> Any:
        """
        Get a value from the settings by string key.

        The key may either be just the field name (e.g. 'conda-format')
        or can refer to am entry within dictionary-valued field
        (e.g. 'pypi-indexes.acme'). Note that the dashes in the first
        component of the key will be converted to underscores.
        """
        name, subkey = self._split_key(key)
        value = getattr(self, name)

        if subkey:
            if not isinstance(value, dict):
                raise KeyError(
                    f"Bad settings key '{key}': '{name}' is not a dictionary"
                )
            if subkey not in value:
                raise KeyError(f"'{key}' is not set'")
            value = value[subkey]

        return value

    def set(self, key: str, value: Any) -> None:
        """
        Set a value in the settings by string key.

        See [get][..] for details on key format.

        This does not save the settings file.
        """
        name, subkey = self._split_key(key)

        if not subkey:
            setattr(self, name, value)

        else:
            d = getattr(self, name)
            if not isinstance(d, dict):
                raise KeyError(
                    f"Bad settings key '{key}': '{name}' is not a dictionary"
                )
            d[subkey] = value

    def unset(self, key: str) -> None:
        """
        Unset attribute with given key.

        The setting will revert to its original value.

        See [get][..] for details on key format.

        This does not save the settings file.
        """
        name, subkey = self._split_key(key)

        if not subkey:
            delattr(self, name)

        else:
            d = getattr(self, name)
            if not isinstance(d, dict):
                raise KeyError(
                    f"Bad settings key '{key}': '{name}' is not a dictionary"
                )
            try:
                del d[subkey]
            except KeyError:
                pass

    def unset_all(self) -> None:
        """
        Unset all settings, and revert to default values.
        """
        for k in self._fieldnames:
            self.unset(k)

    #
    # File operations
    #

    @classmethod
    def from_file(cls, filename: Union[Path, str] = "") -> Whl2CondaSettings:
        """
        Return settings read from file.

        Arguments:
              filename: relative path to settings file (may start with '~')
                defaults to [DEFAULT_SETTINGS_FILE][(c).] if not specified.
        """
        settings = cls()
        settings.load(filename or cls.DEFAULT_SETTINGS_FILE)
        return settings

    def load(self, filename: Union[Path, str], reset_all: bool = False) -> None:
        """
        Reload settings from file

        Args:
            filename: relative path to settings file (may start with '~')
            reset_all: if True, then all settings will be unset and reverted
                to default value prior to loading.
        """
        filepath = Path(Path(filename).expanduser())
        self._settings_file = filepath
        if reset_all:
            self.unset_all()
        if filepath.exists():
            contents = filepath.read_text("utf8")
            json_obj = json.loads(contents)
            for k, v in json_obj.items():
                if k in self._fieldnames:
                    setattr(self, k, v)

    def save(self, filename: Union[Path, str] = "") -> None:
        """
        Write settings to specified file in JSON format.

        Args:
            filename: file to write. Defaults to [settings_file][..]
        """
        filepath = Path(filename or self._settings_file)
        json_obj = self.to_dict()
        json_obj["$whl2conda-version"] = __version__
        json_obj["$created"] = str(dt.datetime.now())
        filepath.write_text(json.dumps(json_obj, indent=2))

    #
    # Internal methods
    #

    def _split_key(self, key: str) -> tuple[str, str]:
        parts = key.split(".", maxsplit=1)
        name = _toidentifier(parts[0])
        if name not in self._fieldnames:
            raise KeyError(f"Unknown settings key '{key}'")
        return name, parts[1] if len(parts) > 1 else ""


Whl2CondaSettings._fieldnames = frozenset(
    f.name for f in dataclasses.fields(Whl2CondaSettings) if not f.name.startswith("_")
)

settings = Whl2CondaSettings.from_file()
"""
User settings.
"""
