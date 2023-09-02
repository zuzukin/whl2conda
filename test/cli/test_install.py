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
Unit tests for `whl2conda install` subcommand
"""
import re
from pathlib import Path
from typing import Any, Dict, List

import pytest

from whl2conda.cli import main
from ..test_conda import conda_config, conda_output, conda_json

# pylint: disable=unused-import
from ..test_packages import simple_conda_package, simple_wheel

# pylint: disable=redefined-outer-name


def test_errors(capsys: pytest.CaptureFixture, tmp_path: Path):
    """Test parser errors in whl2conda install"""
    with pytest.raises(SystemExit):
        main(["install"])
    _out, err = capsys.readouterr()
    assert re.search(r"required.*<package-file>", err)

    with pytest.raises(SystemExit):
        main(["install", "does-not-exist.conda"])
    _out, err = capsys.readouterr()
    assert "does not exist" in err

    pkg_file = tmp_path.joinpath("my-package.conda")
    pkg_file.write_text("", "utf8")
    with pytest.raises(SystemExit):
        main(["install", str(pkg_file)])
    _out, err = capsys.readouterr()
    assert re.search("one of.*--conda-bld.*is required", err)

    not_pkg_file = tmp_path.joinpath("foo.not-conda")
    not_pkg_file.write_text("", "utf8")
    with pytest.raises(SystemExit):
        main(["install", str(not_pkg_file), "-n", "foo"])
    _out, err = capsys.readouterr()
    assert "unsupported suffix" in err

    with pytest.raises(SystemExit):
        main(["install", str(pkg_file), "-n", "foo"])
    _out, err = capsys.readouterr()
    assert "Cannot extract" in err


# pylint: disable=too-many-locals
def test_bld_install(
    simple_conda_package: Path,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Unit tests for `whl2conda install --conda-bld`"""
    condarc_file = tmp_path.joinpath(".condarc")
    croot = tmp_path.joinpath("croot")
    croot_noarch = croot.joinpath("noarch")
    croot_pkg = croot_noarch.joinpath(simple_conda_package.name)
    bld_path = tmp_path.joinpath("bld_path")
    bld_path_noarch = bld_path.joinpath("noarch")
    bld_path_pkg = bld_path_noarch.joinpath(simple_conda_package.name)

    # make conda use temporary .condarc file so we can change bld dir
    monkeypatch.setenv("CONDARC", str(condarc_file))

    # override croot location
    conda_output("config", "--file", str(condarc_file), "--set", "croot", str(croot))
    conda_output("config", "--file", str(condarc_file), "--set", "bld_path", "")
    config = conda_config()
    assert config.get("croot") == str(croot)
    assert not config.get("bld_path")

    cmd_start = ["install", str(simple_conda_package), "--conda-bld"]

    main(cmd_start + ["--dry-run"])
    out, err = capsys.readouterr()
    assert not err
    assert f"Installing {simple_conda_package} into {croot}" in out
    assert not croot.exists()

    main(cmd_start)
    out, err = capsys.readouterr()
    assert not err
    assert f"Installing {simple_conda_package} into {croot}" in out
    assert croot_noarch.exists()
    assert croot_pkg.is_file()

    result = conda_json("search", "--use-local", "--offline", "--json", "simple")
    matches = result["simple"]
    assert matches
    assert matches[0]["channel"] == croot_noarch.as_uri()

    # bld_path should take precedence over croot if defined
    conda_output(
        "config", "--file", str(condarc_file), "--set", "bld_path", str(bld_path)
    )
    croot_pkg.unlink()
    conda_output("index", str(croot))

    main(cmd_start)
    out, err = capsys.readouterr()
    assert not err
    assert f"Installing {simple_conda_package} into {bld_path}" in out
    assert bld_path_noarch.is_dir()
    assert bld_path_pkg.is_file()

    result = conda_json("search", "--use-local", "--offline", "--json", "simple")
    matches = result["simple"]
    assert matches
    assert matches[0]["channel"] == bld_path_noarch.as_uri()


# TODO create faster monkeypatch version of this test
@pytest.mark.slow
def test_env_install(
    simple_conda_package: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Unit tests for `whl2conda install -p/-n"""
    condarc_file = tmp_path.joinpath(".condarc")
    envs = tmp_path.joinpath("envs")
    prefix = tmp_path.joinpath("prefix")
    test_env = envs.joinpath("test-env")
    # make conda use temporary .condarc file so we can change bld dir
    monkeypatch.setenv("CONDARC", str(condarc_file))
    # override envs base dir
    conda_output(
        "config", "--file", str(condarc_file), "--append", "envs_dirs", str(envs)
    )

    main(
        [
            "install",
            str(simple_conda_package),
            "-p",
            str(prefix),
            "--create",
            "--yes",
            "--dry-run",
        ]
    )

    assert not prefix.exists()

    main(
        [
            "install",
            str(simple_conda_package),
            "-p",
            str(prefix),
            "--create",
            "--yes",
            "--extra",
            "python=3.9",
            "pytest >=7.4",
        ]
    )

    assert prefix.is_dir()
    packages = conda_json("list", "-p", str(prefix))
    packages_by_name = {p["name"]: p for p in packages}
    assert packages_by_name["python"]["version"].startswith("3.9.")
    assert "pytest" in packages_by_name
    assert "quaternion" in packages_by_name
    assert "simple" in packages_by_name

    conda_output("create", "-n", "test-env", "python=3.9")
    assert test_env.is_dir()

    main(
        ["install", str(simple_conda_package), "-n", "test-env", "--yes", "--only-deps"]
    )

    packages = conda_json("list", "-n", "test-env")
    packages_by_name = {p["name"]: p for p in packages}
    assert "quaternion" in packages_by_name
    assert "simple" not in packages_by_name
