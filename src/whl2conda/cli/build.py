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
whl2conda build implementation
"""

from __future__ import annotations

import argparse
import dataclasses
import os.path
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, List, Optional, Sequence

# third party
import yaml

# this project
from .common import add_markdown_help, dedent, existing_dir, get_conda_bld_path
from ..api.converter import Wheel2CondaConverter
from .install import install_main

__all__ = ["build_main"]


@dataclasses.dataclass
class BuildArgs:
    """Parsed arguments for whl2conda build"""

    recipe_path: Path
    no_test: bool
    channels: list[str]


def build_main(
    args: Optional[Sequence[str]] = None,
    prog: Optional[str] = None,
) -> None:
    """Main procedure for `whl2conda build` command"""
    parser = argparse.ArgumentParser(
        description=dedent("""
            Build a conda package from a pure python wheel.
            
            This command is limited drop-in replacement for `conda build`.
            It requires that the conda recipe has a build script entry
            of the form `pip install` or `pip wheel`.
            
            This is an experimental feature and is still under active
            change and development.
            """),
        formatter_class=argparse.RawTextHelpFormatter,
        prog=prog,
    )

    parser.add_argument(
        "recipe_path",
        metavar="RECIPE_PATH",
        type=existing_dir,
    )
    parser.add_argument(
        "--no-test",
        action="store_true",
    )
    parser.add_argument(
        "-c",
        "--channel",
        action="append",
        dest="channels",
        default=[],
    )

    add_markdown_help(parser)

    parsed = parser.parse_args(args)
    buildargs = BuildArgs(**vars(parsed))

    builder = CondaBuild(buildargs)

    builder.run()


class CondaBuild:
    """Implement build command"""

    args: BuildArgs
    recipe: dict[str, Any]
    work_dir: Path
    build_script: str = ""

    def __init__(self, args: BuildArgs):
        self.args = args
        self.recipe = {}
        self.work_dir = Path("does-not-exist")

    def run(self) -> None:
        """Run the build logic"""
        start = time.time()
        try:
            self._render_recipe()
            self._check_recipe()
            wheel = self._build_wheel()
            pkg = self._build_package(wheel)
            if not self.args.no_test:
                self._test_package(pkg)
            self._install_package(pkg)
        finally:
            self._cleanup()
        end = time.time()
        print(f"Elapsed time: {end-start:f} seconds")

    def _render_recipe(self):
        conda_bld = get_conda_bld_path()
        with tempfile.TemporaryDirectory(prefix="whl2conda-build-") as tmpdir:
            tmp_recipe_file = Path(tmpdir) / "meta.yaml"
            cmd = [
                "conda",
                "run",
                "-n",
                "base",
                "python",
                "-c",
                dedent(f"""
                    import conda_build.api as api
                    mds = api.render("{self.args.recipe_path}", bypass_env_check=True)
                    api.output_yaml(mds[0][0], file_path="{tmp_recipe_file}")
                    """),
            ]

            with subprocess.Popen(cmd, encoding="utf8", stdout=subprocess.PIPE) as p:
                lines: List[str] = []
                while p.poll() is None:
                    assert p.stdout is not None
                    line = p.stdout.readline()
                    if line:
                        lines.append(line)
                    print(line, end="")
            # TODO - check process exit status

            work_dirname = ""
            for line in lines:
                if copy_m := re.search(r"Copying .* to (.*)", line):
                    copy_target = Path(copy_m.group(1))
                    relpath = copy_target.relative_to(conda_bld)
                    work_dirname, _ = str(relpath).split(os.path.sep, maxsplit=1)
                    self.work_dir = conda_bld / work_dirname
                    assert self.work_dir.is_dir()
                    break

            if not work_dirname:
                raise AssertionError("Cannot find work directory")

            recipe_dir = self.work_dir / "recipe"
            recipe_dir.mkdir()
            recipe_file = recipe_dir / "meta.yaml"
            shutil.copyfile(tmp_recipe_file, recipe_file)

        recipe_str = recipe_file.read_text("utf8")
        self.recipe = yaml.safe_load(recipe_str)

    def _check_recipe(self) -> str:
        build_section = self.recipe.get("build", {})
        script = build_section.get("script", "")
        dist_dir = self.work_dir / "dist"
        dist_dir.mkdir()
        new_script, changed = re.subn(
            r"pip install \.(?=\s|$)",
            f"pip wheel . -w {dist_dir}",
            script,
            count=1,
        )
        if not changed:
            raise ValueError("Recipe does not use 'pip install .'")
        self.build_script = new_script
        return new_script

    def _build_wheel(self) -> Path:
        subprocess.check_call(
            self.build_script,
            shell=True,
        )
        dist_dir = self.work_dir / "dist"
        wheel = next(dist_dir.glob("*.whl"))
        return wheel

    def _build_package(self, wheel: Path) -> Path:
        converter = Wheel2CondaConverter(wheel, self.work_dir)
        return converter.convert()

    def _test_package(self, pkg: Path) -> None:
        test_section = self.recipe.get("test", {})
        if not test_section:
            return
        test_prefix = self.work_dir / "test-env"
        try:
            install_cmd = [
                str(pkg),
                "--create",
                "-p",
                str(test_prefix),
                "--yes",
                "--extra",
            ]
            if channels := self.args.channels:
                for channel in channels:
                    install_cmd.extend(["-c", channel])
            if test_dependencies := test_section.get("requires", []):
                install_cmd.extend(test_dependencies)

            install_main(install_cmd)

            # TODO - use test.source_files

            if import_names := test_section.get("imports", []):
                for import_name in import_names:
                    subprocess.check_call([
                        "conda",
                        "run",
                        "-p",
                        str(test_prefix),
                        "python",
                        "-c",
                        f"import {import_name}",
                    ])

            if commands := test_section.get("commands", []):
                for command in commands:
                    subprocess.check_call(
                        f"conda run -p {str(test_prefix)} {command}", shell=True
                    )
        finally:
            shutil.rmtree(test_prefix, ignore_errors=True)

    def _install_package(self, pkg: Path) -> None:
        install_main(["--conda-bld", str(pkg)])

    def _cleanup(self) -> None:
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir)
