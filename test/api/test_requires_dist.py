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
Unit tests for Requires-Dist parsing and dependency rename rules
"""

from __future__ import annotations

# standard
from pathlib import Path

# third party
import pytest

# this package
from whl2conda.api.converter import (
    DependencyRename,
    RequiresDistEntry,
    normalize_pypi_name,
)

this_dir = Path(__file__).parent.absolute()
root_dir = this_dir.parent.parent
test_projects = root_dir / "test-projects"


#
# RequiresdistEntry test cases
#


def check_dist_entry(entry: RequiresDistEntry) -> None:
    """Check invariants on RequiresDistEntr"""
    if not entry.marker:
        assert entry.generic
    if entry.extra_marker_name:
        assert 'extra' in entry.marker
        assert entry.extra_marker_name in entry.marker
    else:
        # technically, there COULD be an extra in another environment
        # expression, but it wouldn't make much sense
        assert 'extra' not in entry.marker
        if entry.marker:
            assert not entry.generic

    raw = str(entry)
    entry2 = RequiresDistEntry.parse(raw)
    assert entry == entry2

    if not entry.extra_marker_name:
        entry_with_extra = entry.with_extra('original')
        assert entry_with_extra != entry
        assert entry_with_extra.extra_marker_name == 'original'
        assert entry_with_extra.generic == entry.generic
        assert entry_with_extra.name == entry.name
        assert entry_with_extra.version == entry.version
        assert entry.marker in entry_with_extra.marker


def test_requires_dist_entry() -> None:
    """Test RequiresDistEntry data structure"""
    entry = RequiresDistEntry.parse("foo")
    assert entry.name == "foo"
    assert not entry.extras
    assert not entry.version
    assert not entry.marker
    check_dist_entry(entry)

    entry2 = RequiresDistEntry.parse("foo >=1.2")
    assert entry != entry2
    assert entry2.name == "foo"
    assert entry2.version == ">=1.2"
    assert not entry2.extras
    assert not entry2.marker
    check_dist_entry(entry2)

    entry3 = RequiresDistEntry.parse("foo-bar [baz,blah]")
    assert entry3.name == "foo-bar"
    assert entry3.extras == ("baz", "blah")
    assert not entry3.version
    assert not entry3.marker
    check_dist_entry(entry3)

    entry4 = RequiresDistEntry.parse("frodo ; extra=='LOTR'")
    assert entry4.name == "frodo"
    assert entry4.extra_marker_name == "LOTR"
    assert entry4.marker == "extra=='LOTR'"
    assert not entry4.version
    assert not entry4.extras
    check_dist_entry(entry4)

    entry5 = RequiresDistEntry.parse("sam ; python_version >= '3.10'  ")
    assert entry5.name == "sam"
    assert entry5.marker == "python_version >= '3.10'"
    assert not entry5.extra_marker_name
    assert not entry5.version
    assert not entry5.extras
    assert not entry5.generic
    check_dist_entry(entry5)

    entry6 = RequiresDistEntry.parse(
        "bilbo ~=23.2 ; sys_platform=='win32' and extra=='dev'  "
    )
    assert entry6.name == "bilbo"
    assert entry6.version == "~=23.2"
    assert not entry6.extras
    assert entry6.marker == "sys_platform=='win32' and extra=='dev'"
    assert entry6.extra_marker_name == "dev"
    assert not entry6.generic
    check_dist_entry(entry6)

    with pytest.raises(SyntaxError):
        RequiresDistEntry.parse("=123 : bad")

    # Original name spelling is preserved at parse time; normalization
    # only happens when matching rename rules (#134)
    entry_underscore = RequiresDistEntry.parse("Foo_Bar >=1.0")
    assert entry_underscore.name == "Foo_Bar"

    entry_dot = RequiresDistEntry.parse("foo.bar.baz >=2.0")
    assert entry_dot.name == "foo.bar.baz"

    entry_upper = RequiresDistEntry.parse("MyPackage")
    assert entry_upper.name == "MyPackage"


def test_normalize_pypi_name() -> None:
    """Test PEP 503 normalization of PyPI package names"""
    assert normalize_pypi_name("foo") == "foo"
    assert normalize_pypi_name("Foo-Bar") == "foo-bar"
    assert normalize_pypi_name("foo_bar") == "foo-bar"
    assert normalize_pypi_name("foo.bar") == "foo-bar"
    assert normalize_pypi_name("Foo_.Bar") == "foo-bar"
    assert normalize_pypi_name("FOO---BAR") == "foo-bar"
    assert normalize_pypi_name("typing_extensions") == "typing-extensions"


#
# DependencyRename test cases
#


def test_dependency_rename() -> None:
    """Unit tests for DependencyRename class"""
    r = DependencyRename.from_strings("foot", "bar")
    assert r.rename("foo") == ("foo", False)
    assert r.rename("foot") == ("bar", True)

    r = DependencyRename.from_strings("foot", "foot")
    assert r.rename("foot") == ("foot", True)

    r = DependencyRename.from_strings("acme-(.*)", r"acme.\1")
    assert r.rename("acme-stuff") == ("acme.stuff", True)

    r = DependencyRename.from_strings("acme-(?P<name>.*)", r"acme.\g<name>")
    assert r.rename("acme-widgets") == ("acme.widgets", True)

    r = DependencyRename.from_strings("(acme-)?(.*)", r"acme.$2")
    assert r.rename("acme-stuff") == ("acme.stuff", True)
    assert r.rename("stuff") == ("acme.stuff", True)

    r = DependencyRename.from_strings("(?P<name>.*)", r"${name}-foo")
    assert r.rename("stuff") == ("stuff-foo", True)

    # Normalized-form patterns match any PEP 503 spelling (#134)
    r = DependencyRename.from_strings("foo-bar", "conda-foo-bar")
    assert r.rename("foo_bar") == ("conda-foo-bar", True)
    assert r.rename("Foo.Bar") == ("conda-foo-bar", True)
    assert r.rename("foo-bar") == ("conda-foo-bar", True)

    # Patterns are also matched against the name as written
    r = DependencyRename.from_strings("foo_bar", "conda-foo-bar")
    assert r.rename("foo_bar") == ("conda-foo-bar", True)
    assert r.rename("foo-bar") == ("foo-bar", False)

    # Unmatched names pass through with original spelling
    r = DependencyRename.from_strings("other", "something-else")
    assert r.rename("Foo_Bar") == ("Foo_Bar", False)

    # error cases

    with pytest.raises(ValueError, match="Bad dependency rename pattern"):
        DependencyRename.from_strings("[foo", "bar")
    with pytest.raises(ValueError, match="Bad dependency replacement"):
        DependencyRename.from_strings("foo", r"\1")
    with pytest.raises(ValueError, match="Bad dependency replacement"):
        DependencyRename.from_strings("foo(.*)", r"$2")
    with pytest.raises(ValueError, match="Bad dependency replacement"):
        DependencyRename.from_strings("foo(.*)", r"${name}")
    # replacements may only contain valid package name characters
    for bad in ("foo bar", "foo!", "foo[bar]", "foo$1/baz"):
        with pytest.raises(ValueError, match="invalid package name"):
            DependencyRename.from_strings("foo(.*)", bad)
    # group references and valid punctuation are fine
    DependencyRename.from_strings("acme-(.*)", "acme.$1")
    DependencyRename.from_strings("foo-(?P<part>.*)", "foo_${part}")
    DependencyRename.from_strings("foo", "")
