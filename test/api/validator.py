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
"""
Conda package validator for unit tests.
"""

from __future__ import annotations

import email
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Generator, Optional, Sequence

import conda_package_handling.api as cphapi
import pytest
from wheel.wheelfile import WheelFile

from whl2conda.__about__ import __version__
from whl2conda.api.converter import RequiresDistEntry, Wheel2CondaConverter


class PackageValidator:
    """
    Conda package validator.

    You can either call the `validate` method or call
    this object as a function.
    """

    tmp_dir: Path

    _unpacked_wheel: Path
    _unpacked_conda: Path
    _wheel_md: dict[str, Any]
    _override_name: str
    _renamed_dependencies: dict[str, Any]
    _std_renames: dict[str, Any]
    _extra_dependencies: Sequence[str]

    def __init__(self, tmp_dir: Path) -> None:
        self.tmp_dir = tmp_dir
        self._unpacked_conda = self.tmp_dir.joinpath("unpacked-pkg")
        self._unpacked_wheel = self.tmp_dir.joinpath("unpacked-wheel")
        self._wheel_md = {}

    def validate(
        self,
        wheel: Path,
        conda_pkg: Path,
        *,
        name: str = "",
        renamed: Optional[dict[str, str]] = None,
        std_renames: Optional[dict[str, str]] = None,
        extra: Sequence[str] = (),
    ) -> None:
        """Validate conda package against wheel from which it was generated"""
        self._override_name = name
        self._renamed_dependencies = renamed or {}
        self._std_renames = std_renames or {}
        self._extra_dependencies = extra

        wheel_dir = self._unpack_wheel(wheel)
        self._unpack_package(conda_pkg)

        self._wheel_md = self._parse_wheel_metadata(wheel_dir)

        self._validate_unpacked()

    def _parse_wheel_metadata(self, wheel_dir: Path) -> dict[str, Any]:
        metdata_files = list(wheel_dir.glob("*.dist-info/METADATA"))
        assert metdata_files
        md_file = metdata_files[0]
        md_msg = email.message_from_string(md_file.read_text())

        list_keys = set(s.lower() for s in Wheel2CondaConverter.MULTI_USE_METADATA_KEYS)
        md: dict[str, Any] = {}
        for key, value in md_msg.items():
            key = key.lower()
            if key in list_keys:
                md.setdefault(key, []).append(value)
            else:
                md[key] = value
        return md

    def _unpack_package(self, pkg_path: Path) -> Path:
        unpack_dir = self._unpacked_conda
        shutil.rmtree(unpack_dir, ignore_errors=True)
        unpack_dir.mkdir()

        if pkg_path.is_dir():
            shutil.copytree(pkg_path, unpack_dir, dirs_exist_ok=True)
        else:
            cphapi.extract(str(pkg_path), unpack_dir)

        return unpack_dir

    def _unpack_wheel(self, wheel_path: Path) -> Path:
        unpack_dir = self._unpacked_wheel
        shutil.rmtree(unpack_dir, ignore_errors=True)
        unpack_dir.mkdir()

        if wheel_path.is_dir():
            shutil.copytree(wheel_path, unpack_dir, dirs_exist_ok=True)
        else:
            wheel = WheelFile(wheel_path)
            wheel.extractall(unpack_dir)

        return unpack_dir

    def _validate_unpacked(self) -> None:
        info_dir = self._unpacked_conda.joinpath("info")
        assert info_dir.exists()

        self._validate_about(info_dir)
        self._validate_index(info_dir)
        self._validate_paths(info_dir)
        self._validate_hash_input(info_dir)

    def _validate_about(self, info_dir: Path) -> None:
        about_file = info_dir.joinpath("about.json")
        assert about_file.is_file()
        md = self._wheel_md
        _about: dict[str, Any] = json.loads(about_file.read_text())

        assert _about.get("home") == md.get("home-page")
        assert _about.get("keywords") == md.get("keywords")
        assert _about.get("summary") == md.get("summary")
        assert _about.get("description") == md.get("description")
        assert _about.get("classifiers") == md.get("classifier")
        assert _about.get("whl2conda_version") == __version__

        license = _about.get("license")
        if license_expr := md.get("license-expression"):
            assert license == license_expr
        else:
            assert license == md.get("license")

        extra = _about.get("extra", {})
        dev_url = ""
        doc_url = ""
        for urlpair in md.get("project-url", ()):
            key, url = re.split(r"\s*,\s*", urlpair)
            assert extra.get(key) == url
            first_word = re.split(r"\W+", key)[0].lower()
            if first_word in {"doc", "documentation"}:
                doc_url = url
            if first_word in {"dev", "development", "repo", "repository"}:
                dev_url = url
        assert _about.get("doc_url", "") == doc_url
        assert _about.get("dev_url", "") == dev_url

        assert extra.get("license_files", ()) == md.get("license-file", ())
        for key in ["author", "maintainer", "author-email", "maintainer-email"]:
            assert extra.get(key) == md.get(key)

    def _validate_hash_input(self, info_dir: Path) -> None:
        hash_input_file = info_dir.joinpath("hash_input.json")
        assert hash_input_file.is_file()

        assert json.loads(hash_input_file.read_text()) == {}

    def _validate_index(self, info_dir: Path) -> None:
        index_file = info_dir.joinpath("index.json")
        assert index_file.exists()

        wheel_md = self._wheel_md

        index = json.loads(index_file.read_text())
        name = str(index["name"])
        version = str(index["version"])

        if self._override_name:
            assert name == self._override_name
        else:
            assert name == wheel_md["name"]
        assert version == wheel_md["version"]
        # TODO support pinned python version...
        assert index["arch"] is None
        assert index['build'] == 'py_0'
        assert index['build_number'] == 0  # TODO support setting build #
        assert index["platform"] is None
        assert index["subdir"] == "noarch"
        assert index.get("license") == wheel_md.get(
            "license-expression", wheel_md.get("license")
        )

        self._validate_dependencies(index["depends"])

    def _validate_dependencies(self, dependencies: Sequence[str]) -> None:
        output_depends = set(dependencies)
        expected_depends: set[str] = set()

        wheel_md = self._wheel_md
        if python_ver := wheel_md.get("requires-python"):
            expected_depends.add(f"python {python_ver}")
        for dep in wheel_md.get("requires-dist", []):
            entry = RequiresDistEntry.parse(dep)
            if entry.marker:
                continue
            name = entry.name
            version = entry.version
            renamed = False
            for pat, template in self._renamed_dependencies.items():
                if m := re.fullmatch(name, pat):
                    name = m.expand(template)
                    renamed = True
                    break
            if not renamed:
                name = self._std_renames.get(name, name)
            if name:
                expected_depends.add(f"{name} {version}")

        expected_depends.update(self._extra_dependencies)

        if not output_depends == expected_depends:
            pytest.fail(
                "Dependencies don't match\n"
                + f"Unexpected entries: {output_depends - expected_depends}\n"
                + f"Missing entries: {expected_depends - output_depends}"
            )

    def _validate_paths(self, info_dir: Path) -> None:
        rel_files = info_dir.joinpath("files").read_text().splitlines()
        pkg_dir = self._unpacked_conda
        files: set[Path] = set(
            pkg_dir.joinpath(rel_file.strip()) for rel_file in rel_files
        )
        for file in files:
            assert file.is_file()

        path_files: set[Path] = set()
        paths = json.loads(info_dir.joinpath("paths.json").read_text())
        assert set(paths.keys()) == {"paths", "paths_version"}
        assert paths["paths_version"] == 1
        entry_keys = {"_path", "path_type", "sha256", "size_in_bytes"}
        for path_entry in paths["paths"]:
            assert isinstance(path_entry, Dict)
            assert set(path_entry.keys()) == entry_keys
            rel_path = path_entry["_path"]
            file = pkg_dir.joinpath(rel_path)
            assert file.is_file()
            path_files.add(file)

            file_bytes = file.read_bytes()
            assert path_entry["size_in_bytes"] == len(file_bytes)
            assert path_entry["sha256"] == hashlib.sha256(file_bytes).hexdigest()

        assert files == path_files

        all_files = set(f for f in pkg_dir.glob("**/*") if f.is_file())
        info_files = set(info_dir.glob("**/*"))
        non_info_files = all_files - info_files

        assert files == non_info_files

    __call__ = validate


@pytest.fixture
def validate_package(tmp_path: Path) -> Generator[PackageValidator, None, None]:
    """
    Yields a validator object that can be called as a function, e.g.

    ```python
    def test_stuff(validate_package: PackageValidator) -> None:
        ...
        validate_package(wheel1, pkg1)
    ```

    See PackageValidator.validate for function details.
    """
    yield PackageValidator(tmp_path)
