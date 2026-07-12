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
Unit tests for whl2conda.cli.testenv
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from whl2conda.cli.testenv import (
    PackageTestError,
    PackageTestSpec,
    run_package_tests,
)

#
# PackageTestSpec parsing
#


def test_spec_bool() -> None:
    """Spec is falsy when there is nothing to run"""
    assert not PackageTestSpec()
    assert not PackageTestSpec(requires=("pytest",), source_files=("test",))
    assert PackageTestSpec(imports=("foo",))
    assert PackageTestSpec(commands=("pytest",))
    assert PackageTestSpec(pip_check=True)


def test_spec_from_meta_yaml() -> None:
    """Spec from rendered meta.yaml test section"""
    spec = PackageTestSpec.from_meta_yaml({
        "requires": ["pytest >=7"],
        "imports": ["foo", "foo.bar"],
        "commands": ["pytest test"],
        "source_files": ["test"],
    })
    assert spec.requires == ("pytest >=7",)
    assert spec.imports == ("foo", "foo.bar")
    assert spec.commands == ("pytest test",)
    assert spec.source_files == ("test",)
    assert not spec.pip_check

    empty = PackageTestSpec.from_meta_yaml({})
    assert not empty
    assert not empty.requires

    # None values (e.g. empty yaml keys) are tolerated
    assert not PackageTestSpec.from_meta_yaml({"imports": None, "commands": None})


def test_spec_from_v1_tests(caplog: pytest.LogCaptureFixture) -> None:
    """Spec from v1 recipe tests list"""
    spec = PackageTestSpec.from_v1_tests([
        {"python": {"imports": ["foo"], "pip_check": False}},
        {
            "script": ["pytest test", {"content": "foo --version"}],
            "requirements": {"run": ["pytest >=7"]},
            "files": {"source": ["test/"]},
        },
    ])
    assert spec.imports == ("foo",)
    assert not spec.pip_check
    assert spec.commands == ("pytest test", "foo --version")
    assert spec.requires == ("pytest >=7",)
    assert spec.source_files == ("test/",)

    # pip_check defaults to true in the v1 format and implies pip
    spec = PackageTestSpec.from_v1_tests([{"python": {"imports": ["foo"]}}])
    assert spec.pip_check
    assert spec.requires == ("pip",)

    # single-string script and bare files list
    spec = PackageTestSpec.from_v1_tests([
        {"script": "pytest", "files": ["conftest.py"]}
    ])
    assert spec.commands == ("pytest",)
    assert spec.source_files == ("conftest.py",)

    # unsupported elements are warned about and skipped
    with caplog.at_level("WARNING"):
        spec = PackageTestSpec.from_v1_tests([
            {"package_contents": {"site_packages": ["foo"]}},
            {"downstream": "bar"},
            {"script": []},
        ])
    assert not spec
    assert "package_contents" in caplog.text
    assert "downstream" in caplog.text
    assert "script" in caplog.text


#
# test_package runner
#


class FakeRunner:
    """Captures install_main and subprocess calls."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.install_args: list[list[str]] = []
        self.calls: list[tuple[Any, dict[str, Any]]] = []
        self.fail_on: str = ""
        monkeypatch.setattr(
            "whl2conda.cli.testenv.install_main",
            lambda args: self.install_args.append(list(args)),
        )
        monkeypatch.setattr(
            "whl2conda.cli.testenv.subprocess.check_call", self._fake_check_call
        )

    def _fake_check_call(self, cmd, **kwargs) -> None:
        self.calls.append((cmd, kwargs))
        cmd_str = cmd if isinstance(cmd, str) else " ".join(cmd)
        if self.fail_on and self.fail_on in cmd_str:
            raise subprocess.CalledProcessError(1, cmd)


@pytest.fixture
def fake_runner(monkeypatch: pytest.MonkeyPatch) -> FakeRunner:
    return FakeRunner(monkeypatch)


def test_run_package_tests(fake_runner: FakeRunner, tmp_path: Path) -> None:
    """Whitebox test of test_package runner"""
    pkg = tmp_path / "foo-1.0-py_0.conda"
    prefix = tmp_path / "test-env"
    prefix.mkdir()
    work_dir = tmp_path / "test_tmp"
    source_root = tmp_path / "src"
    (source_root / "test").mkdir(parents=True)
    (source_root / "test" / "test_foo.py").write_text("def test(): pass\n")
    (source_root / "conftest.py").write_text("")

    spec = PackageTestSpec(
        requires=("pytest >=7",),
        imports=("foo", "foo.bar"),
        commands=("pytest test",),
        source_files=("test", "conftest.py"),
        pip_check=True,
    )
    run_package_tests(
        pkg,
        spec,
        env_prefix=prefix,
        work_dir=work_dir,
        source_root=source_root,
        channels=["my-channel"],
    )

    # environment created through whl2conda install with channels and requires
    assert fake_runner.install_args == [
        [
            str(pkg),
            "--create",
            "-p",
            str(prefix),
            "--yes",
            "--extra",
            "pytest >=7",
            "-c",
            "my-channel",
        ]
    ]

    # source files were copied into the working directory
    assert (work_dir / "test" / "test_foo.py").is_file()
    assert (work_dir / "conftest.py").is_file()

    # imports, pip check, and commands all run in the working directory
    commands = [cmd for cmd, _kwargs in fake_runner.calls]
    assert commands[0][-1] == "import foo"
    assert commands[1][-1] == "import foo.bar"
    assert commands[2][-3:] == ["-m", "pip", "check"]
    assert commands[3] == f"conda run -p {prefix!s} pytest test"
    for _cmd, kwargs in fake_runner.calls:
        assert kwargs["cwd"] == work_dir
    assert fake_runner.calls[3][1]["shell"] is True

    # test environment was removed
    assert not prefix.exists()


def test_test_package_keep_env(fake_runner: FakeRunner, tmp_path: Path) -> None:
    """keep_env leaves the test environment in place"""
    prefix = tmp_path / "env"
    prefix.mkdir()
    run_package_tests(
        tmp_path / "foo.conda",
        PackageTestSpec(imports=("foo",)),
        env_prefix=prefix,
        work_dir=tmp_path / "work",
        keep_env=True,
    )
    assert prefix.is_dir()


def test_test_package_mamba(fake_runner: FakeRunner, tmp_path: Path) -> None:
    """use_mamba uses mamba for both env creation and test commands"""
    prefix = tmp_path / "env"
    prefix.mkdir()
    run_package_tests(
        tmp_path / "foo.conda",
        PackageTestSpec(imports=("foo",), commands=("foo --version",), pip_check=True),
        env_prefix=prefix,
        work_dir=tmp_path / "work",
        use_mamba=True,
    )
    install_args = fake_runner.install_args[0]
    assert "--mamba" in install_args
    # --mamba precedes the pass-through args introduced by --extra
    assert install_args.index("--mamba") < install_args.index("--extra")
    commands = [cmd for cmd, _kwargs in fake_runner.calls]
    assert commands[0][0] == "mamba"
    assert commands[1][0] == "mamba"
    assert commands[2].startswith("mamba run ")


def test_test_package_failures(fake_runner: FakeRunner, tmp_path: Path) -> None:
    """Test failures are wrapped in PackageTestError"""
    prefix = tmp_path / "env"
    prefix.mkdir()

    fake_runner.fail_on = "import foo"
    with pytest.raises(PackageTestError, match="import of 'foo'"):
        run_package_tests(
            tmp_path / "foo.conda",
            PackageTestSpec(imports=("foo",)),
            env_prefix=prefix,
            work_dir=tmp_path / "work",
        )
    # environment is removed even on failure
    assert not prefix.exists()

    # missing source file pattern
    prefix.mkdir()
    with pytest.raises(PackageTestError, match="no-such-file"):
        run_package_tests(
            tmp_path / "foo.conda",
            PackageTestSpec(imports=("foo",), source_files=("no-such-file*",)),
            env_prefix=prefix,
            work_dir=tmp_path / "work",
            source_root=tmp_path,
        )


def test_build_test_adapter(
    fake_runner: FakeRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """CondaBuild._run_package_tests delegates to the shared runner"""
    from whl2conda.cli.build import BuildArgs, CondaBuild
    from whl2conda.impl.recipe import RecipeFormat, RenderedRecipe

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "whl2conda.cli.build.run_package_tests",
        lambda pkg, spec, **kwargs: calls.append({"pkg": pkg, "spec": spec, **kwargs}),
    )

    def make_args(**overrides: Any) -> BuildArgs:
        values: dict[str, Any] = {
            "recipe_path": [tmp_path],
            "build_only": False,
            "channels": ["chan"],
            "check": False,
            "croot": None,
            "debug": False,
            "extra_deps": [],
            "keep_test_env": True,
            "no_test": False,
            "output": False,
            "output_folder": None,
            "package_format": None,
            "python": "",
            "quiet": 0,
            "skip_existing": False,
            "test_only": False,
            "use_mamba": True,
        }
        values.update(overrides)
        return BuildArgs(**values)

    def make_rendered(raw: dict[str, Any]) -> RenderedRecipe:
        return RenderedRecipe(
            format=RecipeFormat.META_YAML,
            recipe_dir=tmp_path,
            name="foo",
            version="1.0",
            raw=raw,
        )

    builder = CondaBuild(make_args())
    builder.work_dir = tmp_path / "build-work"
    pkg = tmp_path / "foo-1.0-py_0.conda"
    rendered = make_rendered({"test": {"imports": ["foo"], "source_files": ["test"]}})

    builder._run_package_tests(pkg, rendered)
    assert len(calls) == 1
    call = calls[0]
    assert call["pkg"] == pkg
    assert call["spec"].imports == ("foo",)
    assert call["channels"] == ["chan"]
    assert call["keep_env"] is True
    assert call["use_mamba"] is True
    # no conda-build work dir: source files resolve from the recipe dir
    assert call["source_root"] == tmp_path
    assert call["env_prefix"] == builder.work_dir / "test-env"

    # conda-build work dir is preferred when present
    work_src = builder.work_dir / "croot" / "foo_123" / "work"
    work_src.mkdir(parents=True)
    builder._run_package_tests(pkg, rendered)
    assert calls[1]["source_root"] == work_src

    # empty test section: runner is not invoked
    builder._run_package_tests(pkg, make_rendered({}))
    assert len(calls) == 2
