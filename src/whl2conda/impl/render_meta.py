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
Render classic conda recipes (meta.yaml) using conda-build.

Uses conda-build's python API directly when conda-build is importable
in the current environment, and otherwise runs it in the conda `base`
environment. Either way, all conda-build scratch files are redirected
into a whl2conda-controlled work directory.
"""

from __future__ import annotations

# standard
import importlib.util
import logging
import subprocess
from pathlib import Path
from typing import Any

# third party
import yaml

# this project
from .recipe import RecipeRenderError

__all__ = ["render_meta_yaml"]

logger = logging.getLogger(__name__)

_RENDER_SCRIPT = """
import conda_build.api as api
config = api.Config(croot=r"{croot}")
mds = api.render(r"{recipe_dir}", config=config, bypass_env_check=True)
if len(mds) > 1:
    import sys
    print("WARNING: recipe has multiple variants; using the first",
          file=sys.stderr)
api.output_yaml(mds[0][0], file_path=r"{out_file}")
"""


def render_meta_yaml(recipe_dir: Path, work_dir: Path) -> dict[str, Any]:
    """Render a classic meta.yaml recipe using conda-build.

    Args:
        recipe_dir: directory containing meta.yaml
        work_dir: whl2conda scratch directory; conda-build's own
            scratch files are redirected into `<work_dir>/croot`

    Returns:
        The rendered recipe as a dictionary.

    Raises:
        RecipeRenderError: if rendering fails.
    """
    out_file = work_dir / "rendered-meta.yaml"
    croot = work_dir / "croot"
    croot.mkdir(parents=True, exist_ok=True)

    if importlib.util.find_spec("conda_build") is not None:
        _render_in_process(recipe_dir, croot, out_file)
    else:
        _render_in_base_env(recipe_dir, croot, out_file)

    if not out_file.is_file():
        raise RecipeRenderError(
            f"conda-build did not produce a rendered recipe for {recipe_dir}"
        )
    return yaml.safe_load(out_file.read_text("utf8"))


def _render_in_process(recipe_dir: Path, croot: Path, out_file: Path) -> None:
    """Render using conda-build imported into this process."""
    logger.debug("Rendering %s with in-process conda-build", recipe_dir)
    # conda-build is an optional runtime dependency, not installed here
    import conda_build.api as api  # type: ignore[import-untyped,import-not-found]

    try:
        config = api.Config(croot=str(croot))
        mds = api.render(str(recipe_dir), config=config, bypass_env_check=True)
        if len(mds) > 1:
            logger.warning("Recipe has multiple variants; using the first")
        api.output_yaml(mds[0][0], file_path=str(out_file))
    except Exception as ex:
        raise RecipeRenderError(
            f"conda-build failed to render {recipe_dir}: {ex}"
        ) from ex


def _render_in_base_env(recipe_dir: Path, croot: Path, out_file: Path) -> None:
    """Render by running conda-build in the conda base environment."""
    logger.debug("Rendering %s with conda-build from base env", recipe_dir)
    script = _RENDER_SCRIPT.format(
        croot=croot, recipe_dir=recipe_dir, out_file=out_file
    )
    cmd = ["conda", "run", "-n", "base", "python", "-c", script]
    result = subprocess.run(cmd, capture_output=True, encoding="utf8", check=False)
    if result.stdout:
        logger.debug("conda-build render output:\n%s", result.stdout)
    if result.returncode != 0:
        stderr_tail = "\n".join(result.stderr.splitlines()[-15:])
        raise RecipeRenderError(
            f"conda-build failed to render {recipe_dir}"
            f" (exit status {result.returncode}):\n{stderr_tail}\n"
            "Note: conda-build must be installed in the conda base environment."
        )
    if result.stderr:
        logger.warning("%s", result.stderr.strip())
