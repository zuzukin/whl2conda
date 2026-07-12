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
Conda recipe reading and rendering for `whl2conda build`.

Supports classic conda recipes (meta.yaml, rendered through conda-build)
and, in the future, v1 recipes (recipe.yaml, rendered through
rattler-build). Rendered recipes of both formats are normalized into a
common [RenderedRecipe][(m).] structure containing just what
`whl2conda build` needs.
"""

from __future__ import annotations

# standard
import enum
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "RecipeError",
    "RecipeFormat",
    "RecipeRenderError",
    "RenderedRecipe",
    "find_recipe_file",
    "render_recipe",
    "rewrite_build_script",
]


class RecipeError(RuntimeError):
    """A recipe cannot be used by whl2conda build."""


class RecipeRenderError(RecipeError):
    """A recipe could not be rendered."""


class RecipeFormat(enum.Enum):
    """Conda recipe file format."""

    META_YAML = "meta.yaml"
    """Classic conda-build recipe format."""

    V1 = "recipe.yaml"
    """v1 recipe format (CEP 13/14), used by rattler-build."""


@dataclass(slots=True)
class RenderedRecipe:
    """A rendered conda recipe, normalized across recipe formats."""

    format: RecipeFormat
    recipe_dir: Path
    name: str
    version: str
    build_number: int = 0
    build_script: list[str] = field(default_factory=list)
    noarch_python: bool = False
    raw: dict[str, Any] = field(default_factory=dict)
    """The full rendered recipe document."""


def find_recipe_file(recipe_dir: Path) -> tuple[Path, RecipeFormat]:
    """Locate the recipe file in a recipe directory.

    Args:
        recipe_dir: directory containing a `meta.yaml` or `recipe.yaml`

    Returns:
        Tuple of recipe file path and its format.

    Raises:
        RecipeError: if the directory contains no recipe file, or
            contains both formats.
    """
    meta_file = recipe_dir / "meta.yaml"
    v1_file = recipe_dir / "recipe.yaml"
    if meta_file.is_file() and v1_file.is_file():
        raise RecipeError(
            f"Recipe directory {recipe_dir} contains both meta.yaml and"
            " recipe.yaml - remove one"
        )
    if meta_file.is_file():
        return meta_file, RecipeFormat.META_YAML
    if v1_file.is_file():
        return v1_file, RecipeFormat.V1
    raise RecipeError(
        f"Recipe directory {recipe_dir} contains no meta.yaml or recipe.yaml"
    )


def render_recipe(
    recipe_dir: Path,
    work_dir: Path,
    *,
    variant_config: Sequence[Path] = (),
) -> RenderedRecipe:
    """Render the recipe in the given directory.

    Args:
        recipe_dir: directory containing the recipe file
        work_dir: scratch directory for rendering
        variant_config: variant configuration files, if any

    Returns:
        The rendered recipe, normalized.

    Raises:
        RecipeError: if the recipe cannot be found or is unusable.
        RecipeRenderError: if rendering fails.
    """
    recipe_file, recipe_format = find_recipe_file(recipe_dir)
    if recipe_format is RecipeFormat.V1:
        # implemented with #160
        raise RecipeError(
            f"v1 recipes are not yet supported by whl2conda build: {recipe_file}"
        )

    # local import so that recipe.py has no yaml dependency at import time
    from .render_meta import render_meta_yaml

    raw = render_meta_yaml(recipe_dir, work_dir)
    return _normalize_meta_yaml(raw, recipe_dir)


def _normalize_meta_yaml(raw: dict[str, Any], recipe_dir: Path) -> RenderedRecipe:
    """Normalize a rendered meta.yaml document."""
    package = raw.get("package") or {}
    build = raw.get("build") or {}
    script = build.get("script") or []
    if isinstance(script, str):
        script = [script]
    try:
        build_number = int(build.get("number") or 0)
    except (TypeError, ValueError):
        build_number = 0
    return RenderedRecipe(
        format=RecipeFormat.META_YAML,
        recipe_dir=recipe_dir,
        name=str(package.get("name") or ""),
        version=str(package.get("version") or ""),
        build_number=build_number,
        build_script=[str(line) for line in script],
        noarch_python=build.get("noarch") == "python",
        raw=raw,
    )


#: Matches a `pip install .` or `pip wheel .` line, possibly prefixed
#: with a python interpreter invocation and followed by extra options.
_PIP_BUILD_RE = re.compile(
    r"(?P<pre>.*?)"
    r"(?:python\d?(?:\.\d+)?\s+-m\s+)?"
    r"pip\s+(?P<cmd>install|wheel)\s+\.(?=\s|$)"
    r"(?P<post>.*)"
)


def rewrite_build_script(recipe: RenderedRecipe, dist_dir: Path) -> list[str]:
    """Rewrite the recipe build script to build a wheel.

    Rewrites the (single) `pip install .` or `pip wheel .` line in the
    recipe's build script into `pip wheel . -w <dist_dir>`, preserving
    any trailing pip options.

    Args:
        recipe: the rendered recipe
        dist_dir: directory into which the wheel should be built

    Returns:
        The rewritten script lines.

    Raises:
        RecipeError: unless exactly one script line matches.
    """
    rewritten: list[str] = []
    matched = 0
    for line in recipe.build_script:
        if m := _PIP_BUILD_RE.fullmatch(line):
            matched += 1
            line = f"{m.group('pre')}pip wheel . -w {dist_dir}{m.group('post')}"
        rewritten.append(line)
    if matched != 1:
        detail = "does not use" if matched == 0 else "uses more than one"
        raise RecipeError(
            f"Cannot build from recipe in {recipe.recipe_dir}: build script"
            f" {detail} 'pip install .' or 'pip wheel .'"
        )
    return rewritten
