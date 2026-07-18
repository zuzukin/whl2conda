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
Unit tests for whl2conda.impl.recipe and whl2conda.impl.render_meta
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path
from typing import ClassVar

import pytest
import yaml

from whl2conda.impl.recipe import (
    RecipeError,
    RecipeFormat,
    RecipeRenderError,
    RenderedRecipe,
    find_recipe_file,
    render_recipe,
    rewrite_build_script,
)
from whl2conda.impl.render_meta import render_meta_yaml
from whl2conda.impl.render_v1 import render_v1_yaml

RENDERED_META = {
    "package": {"name": "simple", "version": "1.2.3"},
    "build": {"noarch": "python", "number": 2, "script": "pip install . -vv"},
    "test": {"imports": ["simple"]},
}


def test_find_recipe_file(tmp_path: Path) -> None:
    """Unit test for find_recipe_file"""
    with pytest.raises(RecipeError, match=r"no meta\.yaml or recipe\.yaml"):
        find_recipe_file(tmp_path)

    meta_file = tmp_path / "meta.yaml"
    meta_file.write_text("")
    assert find_recipe_file(tmp_path) == (meta_file, RecipeFormat.META_YAML)

    v1_file = tmp_path / "recipe.yaml"
    v1_file.write_text("")
    with pytest.raises(RecipeError, match=r"both meta\.yaml and recipe\.yaml"):
        find_recipe_file(tmp_path)

    meta_file.unlink()
    assert find_recipe_file(tmp_path) == (v1_file, RecipeFormat.V1)


def test_render_recipe_meta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """render_recipe normalizes rendered meta.yaml recipes"""
    recipe_dir = tmp_path / "recipe"
    recipe_dir.mkdir()
    (recipe_dir / "meta.yaml").write_text("unrendered")
    monkeypatch.setattr(
        "whl2conda.impl.recipe.render_meta_yaml",
        lambda _recipe_dir, **_kwargs: dict(RENDERED_META),
        raising=False,
    )
    monkeypatch.setattr(
        "whl2conda.impl.render_meta.render_meta_yaml",
        lambda _recipe_dir, **_kwargs: dict(RENDERED_META),
    )

    rendered = render_recipe(recipe_dir, work_dir=tmp_path / "work")
    assert rendered.format is RecipeFormat.META_YAML
    assert rendered.recipe_dir == recipe_dir
    assert rendered.name == "simple"
    assert rendered.version == "1.2.3"
    assert rendered.build_number == 2
    assert rendered.build_script == ("pip install . -vv",)
    assert rendered.noarch_python
    assert rendered.raw == RENDERED_META

    # list-valued script and unparseable build number
    monkeypatch.setattr(
        "whl2conda.impl.render_meta.render_meta_yaml",
        lambda _recipe_dir, **_kwargs: {
            "package": {"name": "simple", "version": "1.2.3"},
            "build": {"number": "not-a-number", "script": ["pip install ."]},
        },
    )
    rendered = render_recipe(recipe_dir, work_dir=tmp_path / "work")
    assert rendered.build_number == 0
    assert rendered.build_script == ("pip install .",)
    assert not rendered.noarch_python


RENDERED_V1 = {
    "schema_version": 1,
    "package": {"name": "simple", "version": "1.2.3"},
    "source": [{"path": "../"}],
    "build": {
        "number": 2,
        "string": "pyh4616a5c_2",
        "script": "pip install . -vv",
        "noarch": "python",
    },
    "tests": [{"python": {"imports": ["simple"]}}],
}


def test_render_recipe_v1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """render_recipe normalizes rendered v1 recipes"""
    recipe_dir = tmp_path / "recipe"
    recipe_dir.mkdir()
    recipe_file = recipe_dir / "recipe.yaml"
    recipe_file.write_text("unrendered")

    rendered_raw = dict(RENDERED_V1)
    monkeypatch.setattr(
        "whl2conda.impl.render_v1.render_v1_yaml",
        lambda _recipe_file, *_args: dict(rendered_raw),
    )

    rendered = render_recipe(recipe_dir, work_dir=tmp_path / "work")
    assert rendered.format is RecipeFormat.V1
    assert rendered.recipe_dir == recipe_dir
    assert rendered.name == "simple"
    assert rendered.version == "1.2.3"
    assert rendered.build_number == 2
    assert rendered.build_script == ("pip install . -vv",)
    assert rendered.noarch_python
    assert rendered.raw == RENDERED_V1

    # the v1 object script form
    rendered_raw["build"] = {
        "noarch": "python",
        "script": {"content": ["echo before", "pip install ."], "env": {"X": "1"}},
    }
    rendered = render_recipe(recipe_dir, work_dir=tmp_path / "work")
    assert rendered.build_script == ("echo before", "pip install .")
    assert rendered.build_number == 0

    # a missing script is normalized to an empty tuple
    rendered_raw["build"] = {"noarch": "python"}
    rendered = render_recipe(recipe_dir, work_dir=tmp_path / "work")
    assert rendered.build_script == ()

    # non-noarch v1 recipes are accepted for binary conversion (#216)
    rendered_raw["build"] = {"script": "pip install ."}
    rendered = render_recipe(recipe_dir, work_dir=tmp_path / "work")
    assert not rendered.noarch_python


def make_rendered(script: str | list[str]) -> RenderedRecipe:
    """Make a RenderedRecipe with the given build script"""
    if isinstance(script, str):
        script = [script]
    return RenderedRecipe(
        format=RecipeFormat.META_YAML,
        recipe_dir=Path("recipe"),
        name="simple",
        version="1.0",
        build_script=tuple(script),
    )


def test_rewrite_build_script(tmp_path: Path) -> None:
    """Unit test for rewrite_build_script"""
    dist = tmp_path / "dist"

    for script, expected in [
        ("pip install .", f"pip wheel . -w {dist}"),
        (
            "pip install . -vv --no-deps --no-build-isolation",
            f"pip wheel . -w {dist} -vv --no-deps --no-build-isolation",
        ),
        ("pip wheel . --no-deps", f"pip wheel . -w {dist} --no-deps"),
        ("python -m pip install .", f"pip wheel . -w {dist}"),
        ("python3 -m pip install .", f"pip wheel . -w {dist}"),
        ("python3.12 -m pip install .", f"pip wheel . -w {dist}"),
        # interpreter templates are dropped, since they are not
        # resolved in rendered v1 scripts
        ("{{ PYTHON }} pip install . -vv", f"pip wheel . -w {dist} -vv"),
        (
            "${{ PYTHON }} -m pip install . -vv --no-deps --no-build-isolation",
            f"pip wheel . -w {dist} -vv --no-deps --no-build-isolation",
        ),
        ("$PYTHON -m pip install .", f"pip wheel . -w {dist}"),
    ]:
        assert rewrite_build_script(make_rendered(script), dist) == [expected]

    # multi-line scripts: only the pip line is rewritten
    rewritten = rewrite_build_script(
        make_rendered(["echo before", "pip install .", "echo after"]), dist
    )
    assert rewritten == ["echo before", f"pip wheel . -w {dist}", "echo after"]

    # no matching line
    with pytest.raises(RecipeError, match="does not use"):
        rewrite_build_script(make_rendered("make install"), dist)
    with pytest.raises(RecipeError, match="does not use"):
        rewrite_build_script(make_rendered("pip install foo"), dist)
    with pytest.raises(RecipeError, match="does not use"):
        rewrite_build_script(make_rendered([]), dist)

    # more than one matching line
    with pytest.raises(RecipeError, match="more than one"):
        rewrite_build_script(make_rendered(["pip install .", "pip wheel ."]), dist)


def test_render_meta_yaml_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Whitebox test of the base-env subprocess render backend"""
    recipe_dir = tmp_path / "recipe"
    recipe_dir.mkdir()
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    # force the subprocess path even if conda_build is importable
    monkeypatch.setattr(
        "whl2conda.impl.render_meta.importlib.util.find_spec", lambda _name: None
    )

    commands: list[list[str]] = []

    def fake_run(cmd, capture_output=False, encoding="", check=False):
        commands.append(cmd)
        out_file = work_dir / "rendered-meta.yaml"
        out_file.write_text(yaml.safe_dump(RENDERED_META))
        return subprocess.CompletedProcess(
            cmd, 0, stdout="rendered ok", stderr="WARNING: check your recipe"
        )

    monkeypatch.setattr("whl2conda.impl.render_meta.subprocess.run", fake_run)

    with caplog.at_level("WARNING"):
        rendered = render_meta_yaml(recipe_dir, work_dir=work_dir)
    assert rendered["package"]["name"] == "simple"
    # stderr from a successful render is passed through as a warning
    assert "check your recipe" in caplog.text

    cmd = commands[0]
    assert cmd[:6] == ["conda", "run", "-n", "base", "python", "-c"]
    assert str(recipe_dir) in cmd[6]
    assert str(work_dir / "croot") in cmd[6]
    assert (work_dir / "croot").is_dir()
    # the render script is dedented to column zero
    assert cmd[6].lstrip("\n").startswith("import conda_build")

    # use_mamba runs conda-build through mamba instead
    render_meta_yaml(recipe_dir, work_dir=work_dir, use_mamba=True)
    assert commands[1][:2] == ["mamba", "run"]


def test_render_meta_yaml_in_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Whitebox test of the in-process conda-build render backend"""
    recipe_dir = tmp_path / "recipe"
    recipe_dir.mkdir()
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    class FakeCondaBuildApi(types.ModuleType):
        """Stands in for conda_build.api"""

        croots: ClassVar[list[str]] = []
        variant_files: ClassVar[list[str]] = []
        variants = 1
        fail = False

        @classmethod
        def Config(cls, croot: str, variant_config_files=()) -> str:
            cls.croots.append(croot)
            cls.variant_files = list(variant_config_files)
            return croot

        @classmethod
        def render(cls, recipe: str, config: str, bypass_env_check: bool) -> list:
            if cls.fail:
                raise ValueError("bad recipe")
            return [(f"metadata for {recipe}", True, True)] * cls.variants

        @staticmethod
        def output_yaml(metadata: str, file_path: str) -> None:
            Path(file_path).write_text(yaml.safe_dump(RENDERED_META))

    fake_api = FakeCondaBuildApi("conda_build.api")
    fake_pkg = types.ModuleType("conda_build")
    fake_pkg.api = fake_api  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "conda_build", fake_pkg)
    monkeypatch.setitem(sys.modules, "conda_build.api", fake_api)
    monkeypatch.setattr(
        "whl2conda.impl.render_meta.importlib.util.find_spec",
        lambda _name: object(),
    )

    rendered = render_meta_yaml(recipe_dir, work_dir=work_dir)
    assert rendered["package"]["name"] == "simple"
    assert FakeCondaBuildApi.croots == [str(work_dir / "croot")]

    # multiple variants only produce a warning
    FakeCondaBuildApi.variants = 2
    with caplog.at_level("WARNING"):
        render_meta_yaml(recipe_dir, work_dir=work_dir)
    assert "multiple variants" in caplog.text

    # render errors are wrapped in RecipeRenderError
    FakeCondaBuildApi.fail = True
    with pytest.raises(RecipeRenderError, match="bad recipe"):
        render_meta_yaml(recipe_dir, work_dir=work_dir)


def test_render_meta_yaml_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Render failures raise RecipeRenderError with stderr detail"""
    recipe_dir = tmp_path / "recipe"
    recipe_dir.mkdir()
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    monkeypatch.setattr(
        "whl2conda.impl.render_meta.importlib.util.find_spec", lambda _name: None
    )

    def fake_run_fail(cmd, capture_output=False, encoding="", check=False):
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="boom: no such recipe"
        )

    monkeypatch.setattr("whl2conda.impl.render_meta.subprocess.run", fake_run_fail)

    with pytest.raises(RecipeRenderError, match="no such recipe"):
        render_meta_yaml(recipe_dir, work_dir=work_dir)

    # zero exit but no output file also fails clearly
    def fake_run_noop(cmd, capture_output=False, encoding="", check=False):
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("whl2conda.impl.render_meta.subprocess.run", fake_run_noop)
    with pytest.raises(RecipeRenderError, match="did not produce"):
        render_meta_yaml(recipe_dir, work_dir=work_dir)


#
# render_v1 backends
#


def _fake_rattler_module(
    *, multi=False, parse_fail=False, render_fail=False, variants=1
):
    """Create a fake rattler_build module rendering RENDERED_V1."""
    mod = types.ModuleType("rattler_build")

    class FakeRendered:
        class recipe:
            @staticmethod
            def to_dict() -> dict:
                return dict(RENDERED_V1)

    class Stage0Recipe:
        paths: ClassVar[list[str]] = []

        @classmethod
        def from_file(cls, path: str) -> Stage0Recipe:
            if parse_fail:
                raise ValueError("bad yaml")
            cls.paths.append(path)
            return cls()

        def as_single_output(self) -> None:
            if multi:
                raise TypeError("multi-output recipe")

        def render(self, variant_config=None) -> list:
            if render_fail:
                raise ValueError("render boom")
            return [FakeRendered() for _ in range(variants)]

    class VariantConfig:
        files: ClassVar[list[str]] = []

        @classmethod
        def from_files(cls, files: list) -> VariantConfig:
            cls.files = list(files)
            return cls()

    mod.Stage0Recipe = Stage0Recipe  # type: ignore[attr-defined]
    mod.VariantConfig = VariantConfig  # type: ignore[attr-defined]
    return mod


def test_render_v1_yaml_in_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whitebox test of the py-rattler-build render backend"""
    recipe_file = tmp_path / "recipe.yaml"
    recipe_file.write_text("unrendered")
    monkeypatch.setattr(
        "whl2conda.impl.render_v1.importlib.util.find_spec",
        lambda _name: object(),
    )

    fake = _fake_rattler_module()
    monkeypatch.setitem(sys.modules, "rattler_build", fake)
    assert render_v1_yaml(recipe_file) == RENDERED_V1
    assert fake.Stage0Recipe.paths == [str(recipe_file)]

    # variant config files are loaded and passed to the renderer
    variants_file = tmp_path / "variants.yaml"
    variants_file.write_text("c_stdlib: [sysroot]\n")
    assert render_v1_yaml(recipe_file, [variants_file]) == RENDERED_V1
    assert fake.VariantConfig.files == [str(variants_file)]

    monkeypatch.setitem(sys.modules, "rattler_build", _fake_rattler_module(multi=True))
    with pytest.raises(RecipeError, match="multiple outputs"):
        render_v1_yaml(recipe_file)

    # multiple rendered variants are also rejected
    monkeypatch.setitem(sys.modules, "rattler_build", _fake_rattler_module(variants=2))
    with pytest.raises(RecipeError, match="multiple outputs"):
        render_v1_yaml(recipe_file)

    # unexpected binding version (no Stage0Recipe): falls back to the CLI
    monkeypatch.setitem(sys.modules, "rattler_build", types.ModuleType("rattler_build"))
    monkeypatch.setattr(
        "whl2conda.impl.render_v1.shutil.which", lambda _name: "/bin/rattler-build"
    )
    monkeypatch.setattr(
        "whl2conda.impl.render_v1.subprocess.run",
        lambda cmd, **_kwargs: subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps([{"recipe": RENDERED_V1}]), stderr=""
        ),
    )
    assert render_v1_yaml(recipe_file) == RENDERED_V1

    monkeypatch.setitem(
        sys.modules, "rattler_build", _fake_rattler_module(parse_fail=True)
    )
    with pytest.raises(RecipeRenderError, match="bad yaml"):
        render_v1_yaml(recipe_file)

    monkeypatch.setitem(
        sys.modules, "rattler_build", _fake_rattler_module(render_fail=True)
    )
    with pytest.raises(RecipeRenderError, match="render boom"):
        render_v1_yaml(recipe_file)


def test_render_v1_yaml_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whitebox test of the rattler-build executable render backend"""
    recipe_file = tmp_path / "recipe.yaml"
    recipe_file.write_text("unrendered")

    # force the executable path even if py-rattler-build is importable
    monkeypatch.setattr(
        "whl2conda.impl.render_v1.importlib.util.find_spec", lambda _name: None
    )

    # no rattler-build executable either
    monkeypatch.setattr("whl2conda.impl.render_v1.shutil.which", lambda _name: None)
    with pytest.raises(RecipeError, match="requires either"):
        render_v1_yaml(recipe_file)

    monkeypatch.setattr(
        "whl2conda.impl.render_v1.shutil.which", lambda _name: "/bin/rattler-build"
    )

    commands: list[list[str]] = []
    stdout = json.dumps([{"recipe": RENDERED_V1}])
    returncode = 0

    def fake_run(cmd, capture_output=False, encoding="", check=False):
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

    monkeypatch.setattr("whl2conda.impl.render_v1.subprocess.run", fake_run)

    assert render_v1_yaml(recipe_file) == RENDERED_V1
    cmd = commands[0]
    assert cmd[0] == "/bin/rattler-build"
    assert "--render-only" in cmd
    assert str(recipe_file) in cmd

    # variant config files are passed with -m
    variants_file = tmp_path / "variants.yaml"
    variants_file.write_text("c_stdlib: [sysroot]\n")
    render_v1_yaml(recipe_file, [variants_file])
    assert commands[-1][commands[-1].index("-m") + 1] == str(variants_file)

    # multiple outputs are rejected
    stdout = json.dumps([{"recipe": RENDERED_V1}, {"recipe": RENDERED_V1}])
    with pytest.raises(RecipeError, match="multiple outputs"):
        render_v1_yaml(recipe_file)

    # unparseable output
    stdout = "this is not json"
    with pytest.raises(RecipeRenderError, match="Cannot parse"):
        render_v1_yaml(recipe_file)

    # render failure reports stderr
    returncode = 1

    def fake_run_fail(cmd, capture_output=False, encoding="", check=False):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no such recipe")

    monkeypatch.setattr("whl2conda.impl.render_v1.subprocess.run", fake_run_fail)
    with pytest.raises(RecipeRenderError, match="no such recipe"):
        render_v1_yaml(recipe_file)
