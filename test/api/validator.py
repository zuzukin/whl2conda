#  Copyright 2023-2025 Christopher Barber
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

import configparser
import hashlib
import json
import logging
import os.path
import re
import shutil
from pathlib import Path
from typing import Any, Generator, Optional, Sequence

import conda_package_handling.api as cphapi
import pytest

from whl2conda.__about__ import __version__
from whl2conda.api.converter import RequiresDistEntry, Wheel2CondaConverter
from whl2conda.impl.wheel import unpack_wheel


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
    _keep_pip_dependencies: bool = False
    _build_number: int | None = None
    _expected_python_version: str = ""

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
        expected_python_version: str = "",
        keep_pip_dependencies: bool = False,
        build_number: int | None = None,
    ) -> None:
        """Validate conda package against wheel from which it was generated"""
        self._override_name = name
        self._renamed_dependencies = renamed or {}
        self._std_renames = std_renames or {}
        self._extra_dependencies = extra
        self._expected_python_version = expected_python_version
        self._keep_pip_dependencies = keep_pip_dependencies
        self._build_number = build_number

        wheel_dir = self._unpack_wheel(wheel)
        self._unpack_package(conda_pkg)

        self._wheel_md = self._parse_wheel_metadata(wheel_dir)

        self._validate_unpacked()

    # pylint: disable=too-many-locals
    @classmethod
    def _parse_wheel_metadata(cls, wheel_dir: Path) -> dict[str, Any]:
        dist_info_dir = next(wheel_dir.glob("*.dist-info"))
        md_file = dist_info_dir / "METADATA"
        md_msg = Wheel2CondaConverter.read_metadata_file(md_file)

        list_keys = set(s.lower() for s in Wheel2CondaConverter.MULTI_USE_METADATA_KEYS)
        md: dict[str, Any] = {}
        for key, value in md_msg.items():
            key = key.lower()
            if key in list_keys:
                md.setdefault(key, []).append(value)
            else:
                md[key] = value

        wheel_file = dist_info_dir / "WHEEL"
        wheel_msg = Wheel2CondaConverter.read_metadata_file(wheel_file)
        if build := wheel_msg.get("Build"):
            md["build"] = build

        entry_points_file = dist_info_dir / "entry_points.txt"
        if entry_points_file.exists():
            entry_points: list[str] = []
            wheel_entry_points = configparser.ConfigParser()
            wheel_entry_points.read(entry_points_file)
            for section_name in wheel_entry_points.sections():
                if section_name in ["console_scripts", "gui_scripts"]:
                    if section := wheel_entry_points[section_name]:
                        entry_points.extend(f"{k}={v}" for k, v in section.items())
            if entry_points:
                md["entry_points"] = sorted(entry_points)

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
            unpack_wheel(wheel_path, unpack_dir)

        return unpack_dir

    def _validate_unpacked(self) -> None:
        info_dir = self._unpacked_conda.joinpath("info")
        assert info_dir.exists()

        self._validate_about(info_dir)
        self._validate_index(info_dir)
        self._validate_link(info_dir)
        self._validate_paths(info_dir)
        self._validate_file_copy()
        self._validate_hash_input(info_dir)

        # TODO - validate *.data/ files

        self._validate_dist_info()

    # pylint: disable=too-many-locals,too-many-branches
    def _validate_about(self, info_dir: Path) -> None:
        about_file = info_dir.joinpath("about.json")
        assert about_file.is_file()
        md = self._wheel_md
        _about: dict[str, Any] = json.loads(about_file.read_text())

        assert _about.get("home") == md.get("home-page")
        if keywords := md.get("keywords"):
            assert _about["keywords"] == keywords.split(",")
        else:
            assert "keywords" not in _about
        assert _about.get("summary") == md.get("summary")
        assert _about.get("description") == md.get("description")
        extra = _about.get("extra", {})
        assert extra.get("classifiers") == md.get("classifier")
        assert extra.get("whl2conda_version") == __version__

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
            assert extra.get(key) == url, f"{key=} {extra.get(key)} != {url}"
            first_word = re.split(r"\W+", key)[0].lower()
            if first_word in {"doc", "documentation"}:
                doc_url = url
            if first_word in {"dev", "development", "repo", "repository"}:
                dev_url = url
        assert _about.get("doc_url", "") == doc_url
        assert _about.get("dev_url", "") == dev_url

        license_files = md.get("license-file", ())
        licenses_dir = info_dir / "licenses"
        assert extra.get("license_files", ()) == license_files
        if license_files:
            assert licenses_dir.is_dir()
            expected_license_files: list[Path] = []
            for fname in license_files:
                if os.path.isabs(fname):
                    expected_file = licenses_dir / os.path.basename(fname)
                else:
                    expected_file = licenses_dir / fname
                expected_license_files.append(expected_file)
            expected_license_files = sorted(expected_license_files)
            assert sorted(licenses_dir.glob("**/*")) == expected_license_files
        else:
            assert not licenses_dir.exists()

        for key in ["author", "maintainer"]:
            assert extra.get(key) == md.get(key)
        # TODO : check author-email, maintainer-email

    def _validate_dist_info(self) -> None:
        site_packages = self._unpacked_conda / "site-packages"
        dist_md = self._parse_wheel_metadata(site_packages)
        wheel_md = dict(self._wheel_md)
        if self._keep_pip_dependencies:
            assert dist_md == wheel_md
        else:
            # Check extra == 'original' markers
            dist_requires: dict[str, RequiresDistEntry] = {}
            for entry in dist_md.get("requires_dist", ()):
                require = RequiresDistEntry.parse(entry)
                dist_requires[require.name] = require
            wheel_requires: dict[str, RequiresDistEntry] = {}
            for entry in wheel_md.get("requires_dist", ()):
                require = RequiresDistEntry.parse(entry)
                wheel_requires[require.name] = require
            assert dist_requires.keys() == wheel_requires.keys()
            for wheel_require in wheel_requires.values():
                dist_require = dist_requires[wheel_require.name]
                if wheel_require.extra_marker_name:
                    assert dist_require == wheel_require
                else:
                    assert wheel_require.version == dist_require.version
                    assert dist_require.extra_marker_name == "original"
                    assert wheel_require.extras == dist_require.extras
                    assert wheel_require.generic == dist_require.generic
            for md in [dist_md, wheel_md]:
                try:
                    del md["requires-dist"]
                except KeyError:
                    pass
            provides_extra: list[str] = dist_md["provides-extra"]
            assert 'original' in provides_extra
            provides_extra.remove('original')
            if not provides_extra:
                del dist_md["provides-extra"]
            if dist_md != wheel_md:
                print("== dist-info metadata ==")
                print(json.dumps(dist_md, sort_keys=True, indent=2))
                print("== original wheel metadata ==")
                print(json.dumps(wheel_md, sort_keys=True, indent=2))
                assert dist_md == wheel_md

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

        if self._build_number is not None:
            build_number = self._build_number
        else:
            try:
                build_number = int(wheel_md.get("build", 0))
            except ValueError:
                build_number = 0
        assert index['build_number'] == build_number

        assert index["platform"] is None
        assert index["subdir"] == "noarch"
        assert index.get("license") == wheel_md.get(
            "license-expression", wheel_md.get("license")
        )

        self._validate_dependencies(index["depends"])

    def _validate_dependencies(self, dependencies: Sequence[str]) -> None:
        """
        Validates dependencies
        """
        output_depends = set(dependencies)
        expected_depends: set[str] = set()

        # Only used for version translation
        cvt = Wheel2CondaConverter(self.tmp_dir, self.tmp_dir)
        cvt.logger = logging.Logger(__name__, logging.CRITICAL)

        wheel_md = self._wheel_md
        if self._expected_python_version:
            expected_depends.add(f"python {self._expected_python_version}")
        elif python_ver := wheel_md.get("requires-python"):
            expected_depends.add(f"python {python_ver}")
        for dep in wheel_md.get("requires-dist", []):
            try:
                entry = RequiresDistEntry.parse(dep)
            except SyntaxError:
                continue
            if entry.marker:
                continue
            name = entry.name
            version = entry.version
            conda_version = cvt.translate_version_spec(version)
            renamed = False
            for pat, template in self._renamed_dependencies.items():
                if m := re.fullmatch(name, pat):
                    name = m.expand(template)
                    renamed = True
                    break
            if not renamed:
                name = self._std_renames.get(name, name)
            if name:
                expected_depends.add(f"{name} {conda_version}")

        expected_depends.update(self._extra_dependencies)

        if not output_depends == expected_depends:
            pytest.fail(
                "Dependencies don't match\n"
                + f"Unexpected entries: {output_depends - expected_depends}\n"
                + f"Missing entries: {expected_depends - output_depends}"
            )

    def _validate_link(self, info_dir: Path) -> None:
        """
        Validates the contents of the info/link.json file
        """
        link_file = info_dir / "link.json"
        assert link_file.is_file()
        jobj = json.loads(link_file.read_text("utf8"))
        assert jobj["package_metadata_version"] == 1
        noarch = jobj["noarch"]
        assert noarch["type"] == "python"
        entry_points = noarch.get("entry_points")
        if entry_points:
            entry_points = sorted(entry_points)
        md = self._wheel_md
        expected_entry_points = md.get("entry_points")
        assert entry_points == expected_entry_points

    def _validate_paths(self, info_dir: Path) -> None:
        """
        Validate info/files and info/paths.json files

        Performs the following checks:
        - checks correspondence betweens files and paths.json entries
        - checks size an hash values of paths.json entries
        - verifies that file/paths.json entries exist in the conda distribution

        Args:
            info_dir: location of info/ conda subdirectory
        """
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
            assert isinstance(path_entry, dict)
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

    def _validate_file_copy(self) -> None:
        """
        Validates that files have been copied from wheel into corresponding location in conda package
        """
        pkg_dir = self._unpacked_conda
        wheel_dir = self._unpacked_wheel
        assert wheel_dir.is_dir()
        all_wheel_files = set(wheel_dir.glob("**/*"))
        wheel_distinfo_files = set(wheel_dir.glob("*.dist-info/**/*"))
        wheel_data_files = set(wheel_dir.glob("*.data/**/*"))
        wheel_site_package_files = (
            all_wheel_files - wheel_distinfo_files
        ) - wheel_data_files

        # Check that all package files were copied into site-packages/
        site_packages_dir = pkg_dir / "site-packages"
        for wheel_file in wheel_site_package_files:
            if wheel_file.is_dir():
                continue
            rel_path = wheel_file.relative_to(wheel_dir)
            conda_file = site_packages_dir / rel_path
            assert conda_file.exists(), (
                f"{conda_file.relative_to(pkg_dir)} does not exist"
            )
            assert wheel_file.read_bytes() == conda_file.read_bytes()

        # Check that all *.data/data/ files get copied into top level
        wheel_data_data_files = set(wheel_dir.glob("*.data/data/**/*"))
        for wheel_file in wheel_data_data_files:
            if wheel_file.is_dir():
                continue
            rel_path = wheel_file.relative_to(wheel_dir)
            rel_path = Path(
                *rel_path.parts[2:]
            )  # strip *.data/data/ from head of rel path
            conda_file = pkg_dir / rel_path
            assert conda_file.exists(), (
                f"{conda_file.relative_to(pkg_dir)} does not exist"
            )
            # NOTE: in theory this could fail if there is more than one *.data dir that
            #  specify the same file path with different contents, but in practice we do not
            #  expect that to ever happen.
            assert wheel_file.read_bytes() == conda_file.read_bytes()

        # Check that all *.data/script/ files get copied into python-scripts/
        wheel_data_script_files = set(wheel_dir.glob("*.data/scripts/**/*"))
        for wheel_file in wheel_data_script_files:
            if wheel_file.is_dir():
                continue
            rel_path = wheel_file.relative_to(wheel_dir)
            rel_path = Path(
                *rel_path.parts[2:]
            )  # strip *.data/scripts/ from head of rel path
            conda_file = pkg_dir / "python-scripts" / rel_path
            assert conda_file.exists(), (
                f"{conda_file.relative_to(pkg_dir)} does not exist"
            )
            # NOTE: in theory this could fail if there is more than one *.data dir that
            #  specify the same file path with different contents, but in practice we do not
            #  expect that to ever happen.
            assert wheel_file.read_bytes() == conda_file.read_bytes()

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
