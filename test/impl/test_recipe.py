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

import subprocess
from pathlib import Path

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
        lambda _recipe_dir, _work_dir: dict(RENDERED_META),
        raising=False,
    )
    monkeypatch.setattr(
        "whl2conda.impl.render_meta.render_meta_yaml",
        lambda _recipe_dir, _work_dir: dict(RENDERED_META),
    )

    rendered = render_recipe(recipe_dir, tmp_path / "work")
    assert rendered.format is RecipeFormat.META_YAML
    assert rendered.recipe_dir == recipe_dir
    assert rendered.name == "simple"
    assert rendered.version == "1.2.3"
    assert rendered.build_number == 2
    assert rendered.build_script == ["pip install . -vv"]
    assert rendered.noarch_python
    assert rendered.raw == RENDERED_META


def test_render_recipe_v1_unsupported(tmp_path: Path) -> None:
    """v1 recipes are rejected until #160 lands"""
    recipe_dir = tmp_path / "recipe"
    recipe_dir.mkdir()
    (recipe_dir / "recipe.yaml").write_text("package: {name: foo}")
    with pytest.raises(RecipeError, match="not yet supported"):
        render_recipe(recipe_dir, tmp_path / "work")


def make_rendered(script: str | list[str]) -> RenderedRecipe:
    """Make a RenderedRecipe with the given build script"""
    if isinstance(script, str):
        script = [script]
    return RenderedRecipe(
        format=RecipeFormat.META_YAML,
        recipe_dir=Path("recipe"),
        name="simple",
        version="1.0",
        build_script=script,
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
        (
            '{{ PYTHON }} pip install . -vv',
            f"{{{{ PYTHON }}}} pip wheel . -w {dist} -vv",
        ),
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
        return subprocess.CompletedProcess(cmd, 0, stdout="rendered ok", stderr="")

    monkeypatch.setattr("whl2conda.impl.render_meta.subprocess.run", fake_run)

    rendered = render_meta_yaml(recipe_dir, work_dir)
    assert rendered["package"]["name"] == "simple"

    cmd = commands[0]
    assert cmd[:6] == ["conda", "run", "-n", "base", "python", "-c"]
    assert str(recipe_dir) in cmd[6]
    assert str(work_dir / "croot") in cmd[6]
    assert (work_dir / "croot").is_dir()


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
        render_meta_yaml(recipe_dir, work_dir)

    # zero exit but no output file also fails clearly
    def fake_run_noop(cmd, capture_output=False, encoding="", check=False):
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("whl2conda.impl.render_meta.subprocess.run", fake_run_noop)
    with pytest.raises(RecipeRenderError, match="did not produce"):
        render_meta_yaml(recipe_dir, work_dir)
