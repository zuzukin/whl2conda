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
"""
Unit tests for pip to conda dependency translation, including extras
"""

from __future__ import annotations

# standard
import logging
from pathlib import Path
from typing import Any

# third party
import pytest

# this package
from whl2conda.api.converter import (
    CondaTargetInfo,
    DependencyRename,
    RequiresDistEntry,
    Wheel2CondaConverter,
)

this_dir = Path(__file__).parent.absolute()
root_dir = this_dir.parent.parent
test_projects = root_dir / "test-projects"


def test_compute_conda_deps_with_marker_env() -> None:
    """Test _compute_conda_dependencies with marker_env for binary conversion."""
    converter = Wheel2CondaConverter(Path("fake.whl"), Path("."))
    converter.logger = logging.getLogger(__name__)

    linux_env = CondaTargetInfo(
        subdir="linux-64",
        arch="x86_64",
        platform="linux",
        build_string="py312_0",
        is_noarch=False,
        site_packages_prefix="lib/python3.12/site-packages",
        python_version="3.12",
    ).marker_environment()

    deps = [
        RequiresDistEntry.parse("numpy >=1.20"),
        RequiresDistEntry.parse('pyobjc; sys_platform == "darwin"'),
        RequiresDistEntry.parse('pywin32; os_name == "nt"'),
        RequiresDistEntry.parse('readline; sys_platform == "linux"'),
    ]

    result = converter._compute_conda_dependencies(deps, marker_env=linux_env)
    dep_names = [d.split()[0] for d in result]
    assert "numpy" in dep_names
    assert "readline" in dep_names
    # Platform-specific deps should be filtered out
    assert "pyobjc" not in dep_names
    assert "pywin32" not in dep_names


def test_compute_conda_deps_name_normalization() -> None:
    """Names are normalized for rename matching but not for output (#134)."""
    converter = Wheel2CondaConverter(Path("fake.whl"), Path("."))
    converter.logger = logging.getLogger(__name__)
    converter.std_renames = {"foo-bar": "foo-bar-conda"}

    # std rename lookup uses the normalized name
    result = converter._compute_conda_dependencies([
        RequiresDistEntry.parse("Foo_Bar >=1.0")
    ])
    assert result == ["foo-bar-conda >=1.0"]

    # names matching no rename rule pass through with original spelling
    result = converter._compute_conda_dependencies([
        RequiresDistEntry.parse("Acme.Internal_Pkg >=2.0")
    ])
    assert result == ["Acme.Internal_Pkg >=2.0"]

    # explicit rename rules match the normalized form
    converter.dependency_rename = [
        DependencyRename.from_strings("acme-internal-pkg", "acme_internal")
    ]
    result = converter._compute_conda_dependencies([
        RequiresDistEntry.parse("Acme.Internal_Pkg >=2.0")
    ])
    assert result == ["acme_internal >=2.0"]


def test_compute_dependencies_extras(caplog: pytest.LogCaptureFixture) -> None:
    """Dependencies with extras warn unless handled by a rename rule (#217)"""
    converter = Wheel2CondaConverter(Path("fake.whl"), Path("."))
    converter.logger = logging.getLogger(__name__)

    # extras are dropped with a warning by default
    with caplog.at_level(logging.WARNING):
        result = converter._compute_conda_dependencies([
            RequiresDistEntry.parse("somepkg[fancy] >=1.0")
        ])
    assert result == ["somepkg >=1.0"]
    assert "Dropping extras [fancy]" in caplog.text
    assert "somepkg[fancy]" in caplog.text

    # for known extras, the warning suggests the conda package instead
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        result = converter._compute_conda_dependencies([
            RequiresDistEntry.parse("uvicorn[standard] >=0.20")
        ])
    assert result == ["uvicorn >=0.20"]
    assert "Dropping extras [standard]" in caplog.text
    assert "'uvicorn-standard'" in caplog.text
    assert "--known-extras" in caplog.text

    # a rule matching the bracketed form maps the dependency
    # and suppresses the warning
    caplog.clear()
    converter.dependency_rename = [
        DependencyRename.from_strings(r"dask\[complete\]", "dask")
    ]
    with caplog.at_level(logging.WARNING):
        result = converter._compute_conda_dependencies([
            RequiresDistEntry.parse("dask[complete] >=2024.1")
        ])
    assert result == ["dask >=2024.1"]
    assert "Dropping extras" not in caplog.text

    # multiple extras are matched in the order written
    caplog.clear()
    converter.dependency_rename = [
        DependencyRename.from_strings(r"foo\[bar,baz\]", "foo-full")
    ]
    with caplog.at_level(logging.WARNING):
        result = converter._compute_conda_dependencies([
            RequiresDistEntry.parse("foo[bar, baz] >=1")
        ])
    assert result == ["foo-full >=1"]
    assert "Dropping extras" not in caplog.text

    # a bare-name rule still renames the base package but warns
    caplog.clear()
    converter.dependency_rename = [
        DependencyRename.from_strings("uvicorn", "uvicorn-base")
    ]
    with caplog.at_level(logging.WARNING):
        result = converter._compute_conda_dependencies([
            RequiresDistEntry.parse("uvicorn[standard] >=0.20")
        ])
    assert result == ["uvicorn-base >=0.20"]
    assert "Dropping extras [standard]" in caplog.text

    # explicitly dropping the bracketed form is silent
    caplog.clear()
    converter.dependency_rename = [
        DependencyRename.from_strings(r"uvicorn\[standard\]", "")
    ]
    with caplog.at_level(logging.WARNING):
        result = converter._compute_conda_dependencies([
            RequiresDistEntry.parse("uvicorn[standard] >=0.20")
        ])
    assert result == []
    assert "Dropping extras" not in caplog.text


def test_compute_dependencies_known_extras(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """use_known_extras replaces known extras with conda packages (#217)"""
    converter = Wheel2CondaConverter(Path("fake.whl"), Path("."))
    converter.logger = logging.getLogger(__name__)
    converter.use_known_extras = True

    # known extra replaced by the corresponding conda package
    with caplog.at_level(logging.WARNING):
        result = converter._compute_conda_dependencies([
            RequiresDistEntry.parse("uvicorn[standard] >=0.20")
        ])
    assert result == ["uvicorn-standard >=0.20"]
    assert "Dropping extras" not in caplog.text

    # multiple extras mapping to the same package are deduplicated
    result = converter._compute_conda_dependencies([
        RequiresDistEntry.parse("psycopg[binary,c] >=3.1")
    ])
    assert result == ["psycopg >=3.1"]

    # each extra contributes its own package
    result = converter._compute_conda_dependencies([
        RequiresDistEntry.parse("ray[default, serve] >=2.9")
    ])
    assert result == ["ray-default >=2.9", "ray-serve >=2.9"]

    # unknown extras keep the base package and still warn
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        result = converter._compute_conda_dependencies([
            RequiresDistEntry.parse("ray[default,nosuchextra] >=2.9")
        ])
    # (the base package still goes through the standard renames)
    assert result == ["ray-default >=2.9", "ray-core >=2.9"]
    assert "Dropping extras [nosuchextra]" in caplog.text

    # explicit rename rules take precedence over the known table
    caplog.clear()
    converter.dependency_rename = [
        DependencyRename.from_strings(r"uvicorn\[standard\]", "my-uvicorn")
    ]
    with caplog.at_level(logging.WARNING):
        result = converter._compute_conda_dependencies([
            RequiresDistEntry.parse("uvicorn[standard] >=0.20")
        ])
    assert result == ["my-uvicorn >=0.20"]
    assert "Dropping extras" not in caplog.text


FAKE_PYPI_METADATA: dict[tuple[str, str], dict[str, Any]] = {
    ("uvicorn", ""): {
        "info": {
            "version": "0.30.0",
            "provides_extra": ["standard"],
            "requires_dist": [
                "click >=7.0",
                "httptools >=0.6.0 ; extra == 'standard'",
                "watchfiles >=0.13 ; extra == 'standard'",
                "uvloop >=0.14.0 ; sys_platform != 'win32' and extra == 'standard'",
            ],
        },
        "releases": {"0.29.0": [], "0.30.0": []},
    },
    ("uvicorn", "0.29.0"): {
        "info": {
            "version": "0.29.0",
            "provides_extra": ["standard"],
            "requires_dist": [
                "click >=7.0",
                "httptools >=0.5.0 ; extra == 'standard'",
            ],
        },
    },
    ("loopy", ""): {
        "info": {
            "version": "1.0",
            "provides_extra": ["x"],
            "requires_dist": [
                "loopdep >=1 ; extra == 'x'",
                "loopy[x] >=1 ; extra == 'x'",
                "???",
            ],
        },
        "releases": {"1.0": [], "not-a-version": []},
    },
    ("multi", ""): {
        "info": {
            "version": "2.0",
            "provides_extra": ["e1", "e2"],
            "requires_dist": [
                "dep-one >=1 ; extra == 'e1'",
                "dep-two >=2 ; extra == 'e2'",
            ],
        },
        "releases": {"2.0": []},
    },
    ("fastapi", ""): {
        "info": {
            "version": "0.110.0",
            "provides_extra": ["all"],
            "requires_dist": [
                "starlette >=0.36",
                "uvicorn[standard] >=0.20 ; extra == 'all'",
                "orjson >=3.2 ; extra == 'all'",
            ],
        },
        "releases": {"0.110.0": []},
    },
}


def test_compute_dependencies_resolve_extras(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resolve_extras expands extras from pypi metadata (#36)"""
    fetches: list[tuple[str, str]] = []

    def fake_fetch(package: str, version: str = "") -> dict[str, Any]:
        fetches.append((package, version))
        return FAKE_PYPI_METADATA[(package, version)]

    monkeypatch.setattr("whl2conda.api.converter.fetch_pypi_metadata", fake_fetch)

    converter = Wheel2CondaConverter(Path("fake.whl"), Path("."))
    converter.logger = logging.getLogger(__name__)
    converter.resolve_extras = True

    # extras expand into the extra's dependencies plus the base package
    with caplog.at_level(logging.WARNING):
        result = converter._compute_conda_dependencies([
            RequiresDistEntry.parse("uvicorn[standard] >=0.30")
        ])
    assert result == ["uvicorn >=0.30", "httptools >=0.6.0", "watchfiles >=0.13"]
    assert "Dropping extras" not in caplog.text
    # the platform-marker dependency is skipped as usual for noarch
    assert "Skipping dependency with environment marker" in caplog.text
    assert fetches == [("uvicorn", "")]

    # the newest release satisfying the version spec is used
    caplog.clear()
    fetches.clear()
    converter._pypi_metadata_cache.clear()
    result = converter._compute_conda_dependencies([
        RequiresDistEntry.parse("uvicorn[standard] <0.30")
    ])
    assert result == ["uvicorn <0.30", "httptools >=0.5.0"]
    assert fetches == [("uvicorn", ""), ("uvicorn", "0.29.0")]

    # nested extras are expanded recursively
    caplog.clear()
    converter._pypi_metadata_cache.clear()
    with caplog.at_level(logging.WARNING):
        result = converter._compute_conda_dependencies([
            RequiresDistEntry.parse("fastapi[all] >=0.100")
        ])
    assert "fastapi >=0.100" in result
    assert "uvicorn >=0.20" in result
    assert "httptools >=0.6.0" in result
    assert "orjson >=3.2" in result
    assert "Dropping extras" not in caplog.text

    # unknown extras fall back to the dropped-extras warning
    caplog.clear()
    converter._pypi_metadata_cache.clear()
    with caplog.at_level(logging.WARNING):
        result = converter._compute_conda_dependencies([
            RequiresDistEntry.parse("uvicorn[nosuchextra] >=0.30")
        ])
    assert result == ["uvicorn >=0.30"]
    assert "does not provide extra 'nosuchextra'" in caplog.text
    assert "Dropping extras [nosuchextra]" in caplog.text

    # fetch failures fall back to the dropped-extras warning
    caplog.clear()

    def failing_fetch(package: str, version: str = "") -> dict[str, Any]:
        raise OSError("no network")

    monkeypatch.setattr("whl2conda.api.converter.fetch_pypi_metadata", failing_fetch)
    converter._pypi_metadata_cache.clear()
    with caplog.at_level(logging.WARNING):
        result = converter._compute_conda_dependencies([
            RequiresDistEntry.parse("somepkg[fancy] >=1.0")
        ])
    assert result == ["somepkg >=1.0"]
    assert "Cannot fetch pypi metadata for 'somepkg'" in caplog.text
    assert "Dropping extras [fancy]" in caplog.text

    # self-referential extras terminate; unparseable entries are skipped
    caplog.clear()
    monkeypatch.setattr("whl2conda.api.converter.fetch_pypi_metadata", fake_fetch)
    converter._pypi_metadata_cache.clear()
    with caplog.at_level(logging.WARNING):
        result = converter._compute_conda_dependencies([
            RequiresDistEntry.parse("loopy[x] >=1")
        ])
    assert result == ["loopy >=1", "loopdep >=1", "loopy >=1"]
    assert "Dropping extras" not in caplog.text

    # metadata for multiple extras of one package is fetched only once,
    # and unparseable release versions are skipped in version selection
    fetches.clear()
    converter._pypi_metadata_cache.clear()
    result = converter._compute_conda_dependencies([
        RequiresDistEntry.parse("multi[e1,e2] >=1")
    ])
    assert result == ["multi >=1", "dep-one >=1", "dep-two >=2"]
    assert fetches == [("multi", "")]

    # a dependency without a version spec uses the latest metadata
    fetches.clear()
    converter._pypi_metadata_cache.clear()
    result = converter._compute_conda_dependencies([
        RequiresDistEntry.parse("multi[e2]")
    ])
    assert result == ["multi ", "dep-two >=2"]
    assert fetches == [("multi", "")]

    # when no release satisfies the spec, the latest metadata is used
    fetches.clear()
    converter._pypi_metadata_cache.clear()
    result = converter._compute_conda_dependencies([
        RequiresDistEntry.parse("multi[e1] >=99")
    ])
    assert result == ["multi >=99", "dep-one >=1"]
    assert fetches == [("multi", "")]

    # known extras take precedence over pypi resolution when enabled
    fetches.clear()
    monkeypatch.setattr("whl2conda.api.converter.fetch_pypi_metadata", fake_fetch)
    converter.use_known_extras = True
    converter._pypi_metadata_cache.clear()
    result = converter._compute_conda_dependencies([
        RequiresDistEntry.parse("uvicorn[standard] >=0.30")
    ])
    assert result == ["uvicorn-standard >=0.30"]
    assert not fetches


def test_compute_deps_python_added() -> None:
    """python_version is added when no python dependency is present"""
    converter = Wheel2CondaConverter(Path("fake.whl"), Path("."))
    converter.logger = logging.getLogger(__name__)
    converter.python_version = ">=3.10"
    assert converter._compute_conda_dependencies([]) == ["python >=3.10"]
