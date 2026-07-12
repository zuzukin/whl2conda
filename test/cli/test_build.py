#  Copyright 2026 Christopher Barber
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
Unit tests for `whl2conda build` subcommand
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Any

import pytest

from whl2conda.api.converter import (
    CondaPackageFormat,
    CondaTargetInfo,
    MetadataFromWheel,
    Wheel2CondaConverter,
    noarch_build_string,
)
from whl2conda.cli import main
from whl2conda.cli.build import (
    _IGNORED_OPTIONS,
    _UNSUPPORTED_OPTIONS,
    CondaBuild,
    predict_package_path,
)
from whl2conda.impl.recipe import RecipeError, RecipeFormat, RenderedRecipe

RENDERED_RAW: dict[str, Any] = {
    "package": {"name": "simple", "version": "1.2.3"},
    "build": {"noarch": "python", "number": 0, "script": "pip install ."},
    "test": {"imports": ["simple"]},
}


class FakeBuild:
    """Fakes the external actions of the build pipeline."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.converter: Wheel2CondaConverter | None = None
        self.test_calls: list[dict[str, Any]] = []
        self.install_calls: list[tuple[list[Path], str, dict[str, Any]]] = []
        self.rendered_raw: dict[str, Any] = dict(RENDERED_RAW)

        fake = self

        def fake_render(recipe_dir: Path, work_dir: Path, **_kwargs) -> RenderedRecipe:
            raw = dict(fake.rendered_raw)
            build = raw.get("build") or {}
            script = build.get("script") or []
            if isinstance(script, str):
                script = [script]
            return RenderedRecipe(
                format=RecipeFormat.META_YAML,
                recipe_dir=recipe_dir,
                name=raw["package"]["name"],
                version=raw["package"]["version"],
                build_number=int(build.get("number") or 0),
                build_script=script,
                noarch_python=build.get("noarch") == "python",
                raw=raw,
            )

        def fake_build_wheel(builder: CondaBuild, dist_dir: Path) -> Path:
            wheel = dist_dir / "simple-1.2.3-py3-none-any.whl"
            wheel.parent.mkdir(parents=True, exist_ok=True)
            wheel.write_bytes(b"")
            return wheel

        def fake_convert(converter: Wheel2CondaConverter) -> Path:
            fake.converter = converter
            converter.conda_target = CondaTargetInfo.from_wheel_metadata(
                MetadataFromWheel(
                    md={},
                    package_name="simple",
                    version="1.2.3",
                    wheel_build_number="",
                    license=None,
                    dependencies=[],
                    wheel_info_dir=fake.tmp_path,
                    is_pure_python=True,
                    python_tag="py3",
                    abi_tag="none",
                    platform_tag="any",
                )
            )
            pkg = Path(converter.out_dir) / "simple-1.2.3-py_0.conda"
            pkg.parent.mkdir(parents=True, exist_ok=True)
            pkg.write_bytes(b"")
            return pkg

        def fake_run_tests(pkg: Path, spec, **kwargs) -> None:
            fake.test_calls.append({"pkg": pkg, "spec": spec, **kwargs})

        def fake_install(package_files, subdir, **kwargs) -> None:
            fake.install_calls.append((list(package_files), subdir, kwargs))

        monkeypatch.setattr("whl2conda.cli.build.render_recipe", fake_render)
        monkeypatch.setattr(CondaBuild, "_build_wheel", fake_build_wheel)
        monkeypatch.setattr(Wheel2CondaConverter, "convert", fake_convert)
        monkeypatch.setattr("whl2conda.cli.build.run_package_tests", fake_run_tests)
        monkeypatch.setattr("whl2conda.cli.build.install_into_conda_bld", fake_install)


@pytest.fixture
def fake_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[FakeBuild, Path]:
    """Fake build pipeline plus a recipe directory."""
    recipe_dir = tmp_path / "recipe"
    recipe_dir.mkdir()
    (recipe_dir / "meta.yaml").write_text("package: {name: simple}")
    return FakeBuild(monkeypatch, tmp_path), recipe_dir


def test_build_default(fake_build: tuple[FakeBuild, Path]) -> None:
    """Default build: build, test, and install into conda-bld"""
    fake, recipe_dir = fake_build
    main(["build", str(recipe_dir)])

    assert fake.converter is not None
    assert fake.converter.out_format is CondaPackageFormat.V2
    assert fake.converter.extra_dependencies == []
    assert fake.converter.python_version == ""
    assert fake.converter.build_number == 0

    assert len(fake.test_calls) == 1
    test_call = fake.test_calls[0]
    assert test_call["spec"].imports == ("simple",)
    assert test_call["channels"] == []
    assert test_call["keep_env"] is False
    assert test_call["source_root"] == recipe_dir

    assert len(fake.install_calls) == 1
    files, subdir, kwargs = fake.install_calls[0]
    assert files[0].name == "simple-1.2.3-py_0.conda"
    assert subdir == "noarch"
    assert kwargs["conda_bld_path"] is None


def test_build_options(
    fake_build: tuple[FakeBuild, Path],
    tmp_path: Path,
) -> None:
    """Converter and test options are wired through"""
    fake, recipe_dir = fake_build
    out_folder = tmp_path / "out"
    main([
        "build",
        str(recipe_dir),
        "--output-folder",
        str(out_folder),
        "--package-format",
        "tar.bz2",
        "--extra-deps",
        "extra-one >=1",
        "--extra-deps",
        "extra-two",
        "--python",
        ">=3.10",
        "-c",
        "my-channel",
        "--keep-test-env",
        "--mamba",
    ])

    converter = fake.converter
    assert converter is not None
    assert converter.out_format is CondaPackageFormat.V1
    assert Path(converter.out_dir) == out_folder / "noarch"
    assert converter.extra_dependencies == ["extra-one >=1", "extra-two"]
    assert converter.python_version == ">=3.10"

    test_call = fake.test_calls[0]
    assert test_call["channels"] == ["my-channel"]
    assert test_call["keep_env"] is True
    assert test_call["use_mamba"] is True

    # package written to --output-folder: no conda-bld install
    assert not fake.install_calls


def test_build_modes(fake_build: tuple[FakeBuild, Path], tmp_path: Path) -> None:
    """Build mode options select the pipeline shape"""
    fake, recipe_dir = fake_build

    main(["build", str(recipe_dir), "--no-test"])
    assert not fake.test_calls
    assert len(fake.install_calls) == 1

    fake.test_calls.clear()
    fake.install_calls.clear()
    main(["build", str(recipe_dir), "-b"])
    assert not fake.test_calls
    assert not fake.install_calls

    # empty test section: no test run
    fake.rendered_raw = {**RENDERED_RAW, "test": {}}
    main(["build", str(recipe_dir)])
    assert not fake.test_calls

    # --croot passes through to the conda-bld install
    croot = tmp_path / "croot"
    main(["build", str(recipe_dir), "--croot", str(croot)])
    assert fake.install_calls[-1][2]["conda_bld_path"] == croot

    # both spellings of the V2 package format
    for fmt in ("2", "conda", ".conda"):
        main(["build", str(recipe_dir), "-b", "--package-format", fmt])
        assert fake.converter is not None
        assert fake.converter.out_format is CondaPackageFormat.V2


def test_build_verbosity(fake_build: tuple[FakeBuild, Path]) -> None:
    """-q and --debug map onto root log levels"""
    import logging

    _fake, recipe_dir = fake_build
    root = logging.getLogger()
    original_level = root.level
    try:
        for args, level in [
            ([], logging.INFO),
            (["-q"], logging.WARNING),
            (["-qq"], logging.ERROR),
            (["--debug"], logging.DEBUG),
        ]:
            main(["build", str(recipe_dir), "-b", *args])
            assert root.level == level, args
    finally:
        root.setLevel(original_level)


def test_build_wheel_step(
    fake_build: tuple[FakeBuild, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Whitebox test of the wheel build step"""
    from whl2conda.cli.build import BuildArgs

    _fake, recipe_dir = fake_build
    # the FakeBuild harness patches _build_wheel on the class;
    # recover the real implementation for this test
    monkeypatch.undo()

    commands: list[str] = []
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()

    def fake_check_call(cmd, shell=False) -> None:
        assert shell is True
        commands.append(cmd)

    monkeypatch.setattr("whl2conda.cli.build.subprocess.check_call", fake_check_call)

    parser_defaults: dict[str, Any] = {
        f.name: False for f in dataclasses.fields(BuildArgs)
    }
    parser_defaults.update({
        "recipe_path": [recipe_dir],
        "channels": [],
        "croot": None,
        "extra_deps": [],
        "output_folder": None,
        "package_format": None,
        "python": "",
        "quiet": 0,
    })
    builder = CondaBuild(BuildArgs(**parser_defaults))
    builder.build_script = [f"pip wheel . -w {dist_dir}"]

    # build script ran but produced no wheel
    with pytest.raises(RecipeError, match="did not produce a wheel"):
        builder._build_wheel(dist_dir)
    assert commands == [f"pip wheel . -w {dist_dir}"]

    wheel = dist_dir / "simple-1.2.3-py3-none-any.whl"
    wheel.write_bytes(b"")
    assert builder._build_wheel(dist_dir) == wheel

    # cleanup tolerates a work dir that was never created
    assert not builder.work_dir.exists()
    builder._cleanup()


def test_predict_package_path(tmp_path: Path) -> None:
    """Unit test for predict_package_path"""
    rendered = RenderedRecipe(
        format=RecipeFormat.META_YAML,
        recipe_dir=tmp_path,
        name="My_Package.name",
        version="1.2.3",
        build_number=5,
        noarch_python=True,
    )
    assert (
        predict_package_path(rendered, tmp_path, CondaPackageFormat.V2)
        == tmp_path / "noarch" / "my-package-name-1.2.3-py_5.conda"
    )
    assert (
        predict_package_path(rendered, tmp_path, CondaPackageFormat.V1)
        == tmp_path / "noarch" / "my-package-name-1.2.3-py_5.tar.bz2"
    )

    # the build string comes from the same helper the converter uses
    wheel_md = MetadataFromWheel(
        md={},
        package_name="my-package-name",
        version="1.2.3",
        wheel_build_number="",
        license=None,
        dependencies=[],
        wheel_info_dir=tmp_path,
        is_pure_python=True,
        python_tag="py3",
        abi_tag="none",
        platform_tag="any",
    )
    target = CondaTargetInfo.from_wheel_metadata(wheel_md, build_number=5)
    assert target.build_string == noarch_build_string(5) == "py_5"

    rendered.noarch_python = False
    with pytest.raises(RecipeError, match="noarch: python"):
        predict_package_path(rendered, tmp_path, CondaPackageFormat.V2)


def test_build_output_mode(
    fake_build: tuple[FakeBuild, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """--output prints the predicted package path without building"""
    fake, recipe_dir = fake_build

    out_folder = tmp_path / "out"
    main(["build", str(recipe_dir), "--output", "--output-folder", str(out_folder)])
    out, _err = capsys.readouterr()
    assert out.strip() == str(out_folder / "noarch" / "simple-1.2.3-py_0.conda")
    assert fake.converter is None  # nothing was built
    assert not fake.test_calls
    assert not fake.install_calls

    # --croot and --package-format are reflected in the prediction
    croot = tmp_path / "croot"
    main([
        "build",
        str(recipe_dir),
        "--output",
        "--croot",
        str(croot),
        "--package-format",
        "tar.bz2",
    ])
    out, _err = capsys.readouterr()
    assert out.strip() == str(croot / "noarch" / "simple-1.2.3-py_0.tar.bz2")

    # defaults to the configured conda-bld directory
    monkeypatch.setattr(
        "whl2conda.cli.build.get_conda_bld_path", lambda: tmp_path / "bld"
    )
    main(["build", str(recipe_dir), "--output"])
    out, _err = capsys.readouterr()
    assert out.strip() == str(tmp_path / "bld" / "noarch" / "simple-1.2.3-py_0.conda")

    # prediction matches where the actual build puts the package
    main(["build", str(recipe_dir), "--no-test", "--output-folder", str(out_folder)])
    assert fake.converter is not None
    actual = Path(fake.converter.out_dir) / "simple-1.2.3-py_0.conda"
    assert actual == out_folder / "noarch" / "simple-1.2.3-py_0.conda"
    assert actual.is_file()


def test_build_check_mode(
    fake_build: tuple[FakeBuild, Path],
    capsys: pytest.CaptureFixture,
) -> None:
    """--check renders and validates without building"""
    fake, recipe_dir = fake_build

    main(["build", str(recipe_dir), "--check"])
    assert fake.converter is None
    assert not fake.install_calls

    # a recipe whl2conda cannot build fails the check
    fake.rendered_raw = {**RENDERED_RAW, "build": {"script": "make install"}}
    with pytest.raises(SystemExit):
        main(["build", str(recipe_dir), "--check"])
    _out, err = capsys.readouterr()
    assert "does not use" in err


def test_build_test_only(
    fake_build: tuple[FakeBuild, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """-t/--test tests the already-built package"""
    fake, recipe_dir = fake_build
    out_folder = tmp_path / "out"
    pkg = out_folder / "noarch" / "simple-1.2.3-py_0.conda"

    # package has not been built yet
    with pytest.raises(SystemExit):
        main(["build", str(recipe_dir), "-t", "--output-folder", str(out_folder)])
    _out, err = capsys.readouterr()
    assert "build it first" in err
    assert not fake.test_calls

    pkg.parent.mkdir(parents=True)
    pkg.write_bytes(b"")
    main(["build", str(recipe_dir), "-t", "--output-folder", str(out_folder)])
    assert fake.converter is None  # nothing was rebuilt
    assert not fake.install_calls
    assert len(fake.test_calls) == 1
    test_call = fake.test_calls[0]
    assert test_call["pkg"] == pkg
    assert test_call["spec"].imports == ["simple"]
    assert test_call["source_root"] == recipe_dir


def test_build_skip_existing(
    fake_build: tuple[FakeBuild, Path],
    tmp_path: Path,
) -> None:
    """--skip-existing short-circuits when the package exists"""
    fake, recipe_dir = fake_build
    out_folder = tmp_path / "out"

    # package does not exist: build proceeds
    main([
        "build",
        str(recipe_dir),
        "--skip-existing",
        "--output-folder",
        str(out_folder),
    ])
    assert fake.converter is not None
    assert len(fake.test_calls) == 1

    # package now exists: build is skipped
    fake.converter = None
    fake.test_calls.clear()
    main([
        "build",
        str(recipe_dir),
        "--skip-existing",
        "--output-folder",
        str(out_folder),
    ])
    assert fake.converter is None
    assert not fake.test_calls


def test_build_mode_conflicts(
    fake_build: tuple[FakeBuild, Path],
    capsys: pytest.CaptureFixture,
) -> None:
    """Build mode options are mutually exclusive"""
    _fake, recipe_dir = fake_build
    for combo in [
        ["--output", "-b"],
        ["--check", "--output"],
        ["-t", "--no-test"],
        ["-t", "--check"],
        ["-b", "--no-test"],
    ]:
        with pytest.raises(SystemExit):
            main(["build", str(recipe_dir), *combo])
        _out, err = capsys.readouterr()
        assert "not allowed with argument" in err


def test_build_errors(
    fake_build: tuple[FakeBuild, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """Parser-level errors"""
    fake, recipe_dir = fake_build

    recipe_dir2 = tmp_path / "recipe2"
    recipe_dir2.mkdir()
    with pytest.raises(SystemExit):
        main(["build", str(recipe_dir), str(recipe_dir2)])
    _out, err = capsys.readouterr()
    assert "only one recipe path" in err

    with pytest.raises(SystemExit):
        main(["build", str(recipe_dir), "--package-format", "zip"])
    _out, err = capsys.readouterr()
    assert "invalid package format" in err

    # RecipeError from the pipeline becomes a parser error
    fake.rendered_raw = {**RENDERED_RAW, "build": {"script": "make install"}}
    with pytest.raises(SystemExit):
        main(["build", str(recipe_dir)])
    _out, err = capsys.readouterr()
    assert "does not use" in err


@pytest.mark.parametrize(
    ("flags", "nargs"),
    _IGNORED_OPTIONS,
    ids=lambda val: val[0] if isinstance(val, tuple) else str(val),
)
def test_build_ignored_options(
    fake_build: tuple[FakeBuild, Path],
    caplog: pytest.LogCaptureFixture,
    flags: tuple[str, ...],
    nargs: int,
) -> None:
    """Ignored conda build options warn and proceed"""
    fake, recipe_dir = fake_build
    # pass the option twice: only one warning is issued
    args = ["build", str(recipe_dir), flags[0]]
    if nargs:
        args.append("value")
    args += args[2:]
    with caplog.at_level("WARNING"):
        main(args)
    assert len(re.findall(rf"ignoring.*{re.escape(flags[0])}", caplog.text)) == 1
    assert fake.install_calls  # build still completed


@pytest.mark.parametrize(
    ("flags", "nargs"),
    _UNSUPPORTED_OPTIONS,
    ids=lambda val: val[0] if isinstance(val, tuple) else str(val),
)
def test_build_unsupported_options(
    fake_build: tuple[FakeBuild, Path],
    capsys: pytest.CaptureFixture,
    flags: tuple[str, ...],
    nargs: int,
) -> None:
    """Unsupported conda build options are rejected loudly"""
    _fake, recipe_dir = fake_build
    args = ["build", str(recipe_dir), flags[0]]
    if nargs:
        args.append("value")
    with pytest.raises(SystemExit):
        main(args)
    _out, err = capsys.readouterr()
    assert f"{flags[0]} is not supported" in err
