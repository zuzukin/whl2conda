#  Copyright 2023-2026 Christopher Barber
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
External pypi converter tests
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from whl2conda.api.converter import Wheel2CondaError

from .converter import (
    ConverterTestCaseFactory,  # pylint: disable=unused-import
    test_case,  # noqa: F401
)

# pylint: disable=redefined-outer-name

#
# External pypi tests
#

# ignore redefinition of test_case


@pytest.mark.external
def test_pypi_tomlkit(test_case: ConverterTestCaseFactory):
    """
    Test tomlkit package from pypi
    """
    test_case("pypi:tomlkit").build()


@pytest.mark.external
def test_pypi_sphinx(test_case: ConverterTestCaseFactory):
    """
    Test sphinx package from pypi
    """
    test_case("pypi:sphinx").build()


@pytest.mark.external
def test_pypi_zstandard(test_case: ConverterTestCaseFactory):
    """
    Test zstandard package - not pure python
    """
    with pytest.raises(Wheel2CondaError, match="not pure python"):
        test_case("pypi:zstandard").build()


@pytest.mark.external
def test_pypi_colorama(test_case: ConverterTestCaseFactory):
    """
    Test colorama package
    """
    test_case(
        "pypi:colorama",
    ).build()


@pytest.mark.external
def test_argcomplete(test_case: ConverterTestCaseFactory):
    """
    Test argcomplete package

    This package uses *.data/scripts (at least as of 3.2.1)
    """
    test_case(
        "pypi:argcomplete ==3.2.1",
    ).build()


@pytest.mark.external
def test_linkchecker(test_case: ConverterTestCaseFactory):
    """
    Test linkchecker package

    This package uses *.data/data/
    """
    test_case(
        "pypi:linkchecker ==10.4.0",
    ).build()


@pytest.mark.external
@pytest.mark.skip
def test_pypi_orix(test_case: ConverterTestCaseFactory) -> None:
    """
    Test orix package
    """
    case = test_case("pypi:orix")
    orix_pkg = case.build()
    assert orix_pkg.is_file()

    test_env = case.install(orix_pkg)

    subprocess.check_call(["conda", "install", "-p", str(test_env), "pytest", "--yes"])

    subprocess.check_call([
        "conda",
        "run",
        "-p",
        str(test_env),
        "pytest",
        "--pyargs",
        "orix.tests",
        "-k",
        "not test_restrict_to_fundamental_sector",
    ])


#
# Binary (impure) wheel tests
#


@pytest.mark.external
def test_pypi_markupsafe_binary(test_case: ConverterTestCaseFactory) -> None:
    """
    Test converting markupsafe binary wheel (simple C extension).
    """
    case = test_case("pypi:markupsafe", allow_impure=True)
    pkg = case.build()
    assert pkg.is_file()


@pytest.mark.external
def test_pypi_wrapt_binary(test_case: ConverterTestCaseFactory) -> None:
    """
    Test converting wrapt binary wheel (simple C extension).
    """
    case = test_case("pypi:wrapt", allow_impure=True)
    pkg = case.build()
    assert pkg.is_file()


#
# Binary conversion integration tests with conda environment
#


def _get_target_python_version() -> str:
    """Return a Python version different from the current one for testing."""
    import sys

    v = sys.version_info
    return f"{v.major}.{v.minor - 1}" if v.minor >= 11 else f"{v.major}.{v.minor + 1}"


def _get_native_platform_tag() -> str:
    """Return the native wheel platform tag for the current OS/arch."""
    import platform as plat
    import sys

    machine = plat.machine()
    tag_map: dict[tuple[str, str], str] = {
        ("darwin", "arm64"): "macosx_11_0_arm64",
        ("darwin", "x86_64"): "macosx_10_9_x86_64",
        ("linux", "aarch64"): "manylinux2014_aarch64",
        ("linux", "x86_64"): "manylinux2014_x86_64",
        ("win32", "AMD64"): "win_amd64",
        ("win32", "x86"): "win32",
    }
    tag = tag_map.get((sys.platform, machine))
    if tag is None:
        pytest.skip(f"Unsupported platform: {sys.platform}/{machine}")
    return tag


# Packages to test: (spec, import_name, test_code)
_BINARY_TEST_PACKAGES = [
    (
        "markupsafe",
        "markupsafe",
        "from markupsafe import Markup, escape; "
        "assert str(escape('<b>hi</b>')) == '&lt;b&gt;hi&lt;/b&gt;'; "
        "assert Markup('<em>%s</em>') % 'hello' == '<em>hello</em>'; "
        "print('markupsafe OK')",
    ),
    (
        "pyyaml",
        "yaml",
        "import yaml; "
        "data = yaml.safe_load('[1, 2, 3]'); "
        "assert data == [1, 2, 3]; "
        "assert yaml.dump({'key': 'value'}).strip() == 'key: value'; "
        "print('pyyaml OK')",
    ),
    (
        "wrapt",
        "wrapt",
        "import wrapt; "
        "assert callable(wrapt.decorator); "
        "assert callable(wrapt.ObjectProxy); "
        "print('wrapt OK')",
    ),
    (
        "msgpack",
        "msgpack",
        "import msgpack; "
        "packed = msgpack.packb({'key': 'value'}); "
        "unpacked = msgpack.unpackb(packed, raw=False); "
        "assert unpacked == {'key': 'value'}; "
        "print('msgpack OK')",
    ),
]


@pytest.mark.external
@pytest.mark.slow
def test_binary_conversion_install_and_run(tmp_path: Path) -> None:
    """Integration test: download binary wheels for a different Python version,
    convert to conda, install into a fresh conda environment, and run test code.
    """
    from whl2conda.api.converter import Wheel2CondaConverter
    from whl2conda.impl.download import download_wheel

    target_py = _get_target_python_version()
    platform_tag = _get_native_platform_tag()
    abi_tag = f"cp{target_py.replace('.', '')}"

    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    out_dir = tmp_path / "conda-out"
    out_dir.mkdir()

    # Download and convert each package
    conda_packages: list[Path] = []
    for spec, _import_name, _test_code in _BINARY_TEST_PACKAGES:
        try:
            wheel_path = download_wheel(
                spec,
                into=download_dir,
                platform=platform_tag,
                python_version=target_py,
                abi=abi_tag,
            )
        except (RuntimeError, FileNotFoundError):
            pytest.skip(f"Could not download {spec} for {platform_tag}/cp{target_py}")

        converter = Wheel2CondaConverter(wheel_path, out_dir)
        converter.allow_impure = True
        conda_pkg = converter.convert()
        assert conda_pkg.is_file(), f"Failed to convert {spec}"
        conda_packages.append(conda_pkg)

    # Create a fresh conda environment with the target Python version
    env_dir = tmp_path / "test-env"
    subprocess.check_call([
        "conda",
        "create",
        "-p",
        str(env_dir),
        f"python={target_py}",
        "--yes",
        "--quiet",
    ])

    # Install all converted packages into the environment
    for pkg in conda_packages:
        subprocess.check_call([
            "conda",
            "install",
            "-p",
            str(env_dir),
            str(pkg),
            "--yes",
            "--quiet",
            "--offline",
        ])

    # Run test code for each package
    for spec, import_name, test_code in _BINARY_TEST_PACKAGES:
        pkg_file = next(
            (p for p in conda_packages if spec in p.name.lower()),
            None,
        )
        if pkg_file is None:
            continue

        result = subprocess.run(
            ["conda", "run", "-p", str(env_dir), "python", "-c", test_code],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"Test code for {spec} failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
