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
Unit tests for `whl2conda test` subcommand
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest

from whl2conda.cli import main
from whl2conda.cli.testenv import PackageTestError
from whl2conda.impl.recipe import RecipeFormat, RenderedRecipe

PYPROJECT_WITH_TESTS = dedent("""
    [project]
    name = "simple"

    [[tool.whl2conda.tests]]
    python = { imports = ["simple"], pip_check = false }

    [[tool.whl2conda.tests]]
    script = ["pytest test"]
    requirements = { run = ["pytest"] }
    """)


class FakeTest:
    """Fakes the external actions of the test pipeline."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.test_calls: list[dict[str, Any]] = []
        self.fail = False
        self.rendered_raw: dict[str, Any] = {}
        self.render_calls: list[Path] = []

        fake = self

        def fake_run_tests(pkg: Path, spec, **kwargs) -> None:
            fake.test_calls.append({"pkg": pkg, "spec": spec, **kwargs})
            if fake.fail:
                raise PackageTestError("test failed")

        def fake_render(recipe_dir: Path, **_kwargs) -> RenderedRecipe:
            fake.render_calls.append(recipe_dir)
            fmt = (
                RecipeFormat.V1
                if (recipe_dir / "recipe.yaml").is_file()
                else RecipeFormat.META_YAML
            )
            return RenderedRecipe(
                format=fmt,
                recipe_dir=recipe_dir,
                name="simple",
                version="1.0",
                raw=fake.rendered_raw,
            )

        monkeypatch.setattr("whl2conda.cli.test.run_package_tests", fake_run_tests)
        monkeypatch.setattr("whl2conda.cli.test.render_recipe", fake_render)

        self.package = tmp_path / "simple-1.0-py_0.conda"
        self.package.write_bytes(b"")
        self.project = tmp_path / "project"
        self.project.mkdir()


@pytest.fixture
def fake_test(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeTest:
    return FakeTest(monkeypatch, tmp_path)


def test_test_pyproject(fake_test: FakeTest) -> None:
    """Tests from pyproject [tool.whl2conda.tests] section"""
    (fake_test.project / "pyproject.toml").write_text(PYPROJECT_WITH_TESTS)

    main([
        "test",
        str(fake_test.package),
        str(fake_test.project),
        "-c",
        "my-channel",
        "--keep-test-env",
        "--mamba",
    ])
    assert len(fake_test.test_calls) == 1
    call = fake_test.test_calls[0]
    assert call["pkg"] == fake_test.package
    assert call["spec"].imports == ("simple",)
    assert call["spec"].commands == ("pytest test",)
    assert call["channels"] == ["my-channel"]
    assert call["keep_env"] is True
    assert call["use_mamba"] is True
    assert call["python_version"] == ""
    assert call["source_root"] == fake_test.project
    # recipe rendering never invoked
    assert not fake_test.render_calls


def test_test_python_matrix(fake_test: FakeTest) -> None:
    """One test environment per python version"""
    (fake_test.project / "pyproject.toml").write_text(
        PYPROJECT_WITH_TESTS + '\n[tool.whl2conda]\ntest-python = ["3.10", "3.14"]\n'
    )

    # versions from pyproject
    main(["test", str(fake_test.package), str(fake_test.project)])
    versions = [call["python_version"] for call in fake_test.test_calls]
    assert versions == ["3.10", "3.14"]
    prefixes = {str(call["env_prefix"]) for call in fake_test.test_calls}
    assert len(prefixes) == 2

    # --python overrides pyproject
    fake_test.test_calls.clear()
    main([
        "test",
        str(fake_test.package),
        str(fake_test.project),
        "--python",
        "3.12",
    ])
    versions = [call["python_version"] for call in fake_test.test_calls]
    assert versions == ["3.12"]


def test_test_from_recipe(fake_test: FakeTest) -> None:
    """Tests from a rendered recipe test section"""
    recipe_dir = fake_test.project
    (recipe_dir / "meta.yaml").write_text("unrendered")
    fake_test.rendered_raw = {"test": {"imports": ["simple"]}}

    main(["test", str(fake_test.package), str(recipe_dir)])
    assert fake_test.render_calls == [recipe_dir]
    assert fake_test.test_calls[0]["spec"].imports == ("simple",)

    # v1 recipe tests list
    (recipe_dir / "meta.yaml").unlink()
    (recipe_dir / "recipe.yaml").write_text("unrendered")
    fake_test.rendered_raw = {"tests": [{"python": {"imports": ["simple"]}}]}
    fake_test.test_calls.clear()
    main(["test", str(fake_test.package), str(recipe_dir)])
    spec = fake_test.test_calls[0]["spec"]
    assert spec.imports == ("simple",)
    assert spec.pip_check


def test_test_file_option(fake_test: FakeTest) -> None:
    """--test-file overrides project test specification"""
    (fake_test.project / "pyproject.toml").write_text(PYPROJECT_WITH_TESTS)
    test_file = fake_test.tmp_path / "mytests.yaml"
    test_file.write_text("- python:\n    imports: [other]\n")

    main([
        "test",
        str(fake_test.package),
        str(fake_test.project),
        "--test-file",
        str(test_file),
    ])
    call = fake_test.test_calls[0]
    assert call["spec"].imports == ("other",)
    assert call["source_root"] == fake_test.tmp_path


def test_test_errors_and_modes(
    fake_test: FakeTest,
    capsys: pytest.CaptureFixture,
) -> None:
    """Error handling, --prefix, --dry-run and exit status"""
    # no tests found
    with pytest.raises(SystemExit):
        main(["test", str(fake_test.package), str(fake_test.project)])
    assert "No tests found" in capsys.readouterr().err

    (fake_test.project / "pyproject.toml").write_text(PYPROJECT_WITH_TESTS)

    # --prefix with multiple python versions is rejected
    with pytest.raises(SystemExit):
        main([
            "test",
            str(fake_test.package),
            str(fake_test.project),
            "--python",
            "3.10",
            "--python",
            "3.11",
            "-p",
            str(fake_test.tmp_path / "env"),
        ])
    assert "not allowed with multiple" in capsys.readouterr().err

    # --prefix is passed through
    main([
        "test",
        str(fake_test.package),
        str(fake_test.project),
        "-p",
        str(fake_test.tmp_path / "env"),
    ])
    assert fake_test.test_calls[0]["env_prefix"] == fake_test.tmp_path / "env"

    # --dry-run shows the spec without running tests
    fake_test.test_calls.clear()
    main([
        "test",
        str(fake_test.package),
        str(fake_test.project),
        "--dry-run",
        "--python",
        "3.12",
    ])
    assert not fake_test.test_calls
    out = capsys.readouterr().out
    assert "3.12" in out
    assert "pytest test" in out
    assert "simple" in out

    # test failures exit with nonzero status
    fake_test.fail = True
    with pytest.raises(SystemExit) as exc_info:
        main(["test", str(fake_test.package), str(fake_test.project)])
    assert exc_info.value.code == 1
    assert "test failed" in capsys.readouterr().err
