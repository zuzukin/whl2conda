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
Render v1 conda recipes (recipe.yaml) using rattler-build.

Uses the py-rattler-build python bindings when they are importable in
the current environment, and otherwise runs the `rattler-build`
executable in render-only mode. Neither is a runtime dependency of
whl2conda; a clear error is raised if both are missing.
"""

from __future__ import annotations

# standard
import importlib.util
import json
import logging
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# this project
from .recipe import RecipeError, RecipeRenderError

__all__ = ["render_v1_yaml"]

logger = logging.getLogger(__name__)


def render_v1_yaml(
    recipe_file: Path,
    variant_config: Sequence[Path] = (),
) -> dict[str, Any]:
    """Render a v1 recipe.yaml recipe using rattler-build.

    Args:
        recipe_file: the recipe.yaml file
        variant_config: variant configuration files, needed by recipes
            using variant-dependent expressions like `stdlib('c')`

    Returns:
        The rendered recipe as a dictionary.

    Raises:
        RecipeError: if no rattler-build tooling is available or the
            recipe renders to more than one output.
        RecipeRenderError: if rendering fails.
    """
    raw = _render_in_process(recipe_file, variant_config)
    if raw is None:
        raw = _render_with_cli(recipe_file, variant_config)
    return raw


def _render_in_process(
    recipe_file: Path,
    variant_config: Sequence[Path],
) -> dict[str, Any] | None:
    """Render using py-rattler-build, or return None if unavailable."""
    if importlib.util.find_spec("rattler_build") is None:
        return None
    import rattler_build  # type: ignore # noqa: PLC0415

    if not hasattr(rattler_build, "Stage0Recipe"):
        # unexpected python binding version - fall back to the executable
        return None
    logger.debug("Rendering %s with py-rattler-build", recipe_file)

    try:
        recipe = rattler_build.Stage0Recipe.from_file(str(recipe_file))
    except Exception as ex:
        raise RecipeRenderError(
            f"rattler-build cannot parse {recipe_file}: {ex}"
        ) from ex
    try:
        recipe.as_single_output()
    except TypeError:
        raise _multiple_outputs_error(recipe_file) from None
    try:
        config = None
        if variant_config:
            config = rattler_build.VariantConfig.from_files([
                str(f) for f in variant_config
            ])
        variants = recipe.render(variant_config=config)
    except Exception as ex:
        raise RecipeRenderError(
            f"rattler-build failed to render {recipe_file}: {ex}"
        ) from ex
    if len(variants) != 1:
        raise _multiple_outputs_error(recipe_file)
    return variants[0].recipe.to_dict()


def _render_with_cli(
    recipe_file: Path,
    variant_config: Sequence[Path],
) -> dict[str, Any]:
    """Render by running the rattler-build executable."""
    exe = shutil.which("rattler-build")
    if exe is None:
        raise RecipeError(
            f"Cannot render {recipe_file}: v1 recipe support requires either"
            " the py-rattler-build python package or the rattler-build"
            " command on the PATH"
        )
    logger.debug("Rendering %s with %s", recipe_file, exe)

    cmd = [exe, "build", "--render-only", "--recipe", str(recipe_file)]
    for config_file in variant_config:
        cmd.extend(["-m", str(config_file)])
    result = subprocess.run(cmd, capture_output=True, encoding="utf8", check=False)
    if result.returncode != 0:
        stderr_tail = "\n".join(result.stderr.splitlines()[-15:])
        raise RecipeRenderError(
            f"rattler-build failed to render {recipe_file}"
            f" (exit status {result.returncode}):\n{stderr_tail}"
        )
    try:
        outputs = json.loads(result.stdout)
    except json.JSONDecodeError as ex:
        raise RecipeRenderError(
            f"Cannot parse rattler-build render output for {recipe_file}: {ex}"
        ) from ex
    if not isinstance(outputs, list) or len(outputs) != 1:
        raise _multiple_outputs_error(recipe_file)
    return outputs[0]["recipe"]


def _multiple_outputs_error(recipe_file: Path) -> RecipeError:
    return RecipeError(
        f"Recipe {recipe_file} renders to multiple outputs or variants,"
        " which is not supported by whl2conda build"
    )
