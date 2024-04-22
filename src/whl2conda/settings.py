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
from pathlib import Path
from typing import Any, Callable, ClassVar, NamedTuple, Union

# third party
from platformdirs import user_config_path

# this project
from .__about__ import __version__
from .impl.pyproject import CondaPackageFormat

__all__ = ["Whl2CondaSettings", "settings"]


class FieldDefault(NamedTuple):
    factory: Callable


class StringConversionField:
    def __init__(self, *, default):
        if callable(default):
            self._default = FieldDefault(default)
        else:
            self._default = default

    def __set_name__(self, owner, name):
        self._name = "_" + name

    def __get__(self, obj, type):
        if obj is None:
            return self._default
        return getattr(obj, self._name)

    def __set__(self, obj, value):
        if isinstance(value, FieldDefault):
            value = value.factory()
        elif isinstance(value, str):
            value = self._convert_from_str(value)
        setattr(obj, self._name, value)

    def __delete__(self, obj):
        self.__set__(obj, self._default)

    def _convert_from_str(self, value: str):
        return value


class BoolField(StringConversionField):
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


class CondaPackageFormatField(StringConversionField):
    def __init__(self):
        super().__init__(default=CondaPackageFormat.V2)

    def _convert_from_str(self, value: str):
        return CondaPackageFormat.from_string(value)


def toidentifier(name: str) -> str:
    return name.replace("-", "_")


def fromidentifier(name: str) -> str:
    return name.replace("_", "-")


@dataclasses.dataclass(kw_only=True)
class Whl2CondaSettings:
    SETTINGS_FILENAME: ClassVar[str] = "whl2conda.json"
    DEFAULT_SETTINGS_FILE: ClassVar[Path] = user_config_path() / SETTINGS_FILENAME

    # TODO:
    #   - difftool
    #   - pyproject defaults

    auto_update_std_renames: BoolField = BoolField()

    conda_format: CondaPackageFormatField = CondaPackageFormatField()

    pypi_indexes: StringConversionField = StringConversionField(default=dict)

    #
    # Internal attributes
    #

    _settings_file: Path = dataclasses.field(
        default=DEFAULT_SETTINGS_FILE, compare=False
    )

    _fieldnames: ClassVar[frozenset[str]] = frozenset()

    @property
    def settings_file(self) -> Path:
        """
        Settings file for this settings object.

        Set from [from_file][..] constructor or else will be
        [DEFAULT_SETTINGS_FILE][(c).].
        """
        return self._settings_file

    def to_dict(self) -> dict[str, Any]:
        return {
            k: v for k, v in dataclasses.asdict(self).items() if not k.startswith("_")
        }

    def get(self, key: str) -> Any:
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

    def _split_key(self, key: str) -> tuple[str, str]:
        parts = key.split(".", maxsplit=1)
        name = toidentifier(parts[0])
        if name not in self._fieldnames:
            raise KeyError(f"Unknown settings key '{key}'")
        return name, parts[1] if len(parts) > 1 else ""

    @classmethod
    def from_file(cls, filename: Union[Path, str] = "") -> Whl2CondaSettings:
        settings = cls()
        settings.load(filename or cls.DEFAULT_SETTINGS_FILE)
        return settings

    def load(self, filename: Union[Path, str], reset_all: bool = False) -> None:
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

    def unset_all(self) -> None:
        """
        Unset all settings, and revert to default values.
        """
        for k in self._fieldnames:
            self.unset(k)


Whl2CondaSettings._fieldnames = frozenset(
    f.name for f in dataclasses.fields(Whl2CondaSettings) if not f.name.startswith("_")
)

settings = Whl2CondaSettings.from_file()
