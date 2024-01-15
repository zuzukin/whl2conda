#  Copyright 2023-2024 Christopher Barber
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
#
"""
CLI utility functions
"""

from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, Optional, Sequence

__all__ = [
    "add_markdown_help",
    "Subcommands",
    "dedent",
    "existing_path",
    "existing_dir",
    "maybe_existing_dir",
]


class MarkdownHelpFormatter(argparse.RawTextHelpFormatter):
    """
    Format help in markdown format for use in docs
    """

    def __init__(self, prog: str):
        super().__init__(prog, max_help_position=12, width=80)

    def add_usage(self, usage, actions, groups, prefix=None):
        self.add_text(f"# {self._prog}")
        self.start_section("Usage")
        super().add_usage(usage, actions, groups, prefix)
        self.end_section()

    def start_section(self, heading):
        self._indent()
        section = self._Section(self, self._current_section, argparse.SUPPRESS)

        def add_heading() -> str:
            return f"### {heading}\n```text" if section.items else ''

        self._add_item(add_heading, [])
        self._add_item(section.format_help, [])
        self._current_section = section

    def end_section(self) -> None:
        show = bool(self._current_section.items)
        super().end_section()
        if show:
            self.add_text("```")


def dedent(text: str) -> str:
    """Deindent help string"""
    return textwrap.dedent(text).strip()


class MarkdownHelp(argparse.Action):
    """Print out help in markdown format and exit"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.nargs = 0
        self.default = argparse.SUPPRESS
        self.dest = argparse.SUPPRESS

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: Optional[str] = None,
    ):
        parser.formatter_class = MarkdownHelpFormatter
        parser.print_help()
        sys.exit(0)


def add_markdown_help(parser: argparse._ActionsContainer) -> None:
    """Adds --markdown-help option"""
    parser.add_argument(
        "--markdown-help",
        action=MarkdownHelp,
        help=argparse.SUPPRESS,  # For internal use, do not show help
    )


def existing_path(val: str) -> Path:
    """
    Parses argument as existing file path.

    For use as type of argparse argument.
    Args:
        val: input string

    Returns:
        Path after validating it exists.
    """
    path = Path(val).expanduser()
    if not path.exists():
        raise argparse.ArgumentTypeError(f"path '{val}' does not exist")
    return path


def maybe_existing_dir(val: str) -> Path:
    """
    Parses argument as a possibly not yet existing directory path.

    For use as type of argparse argument
    """
    path = Path(val).expanduser()
    if path.is_file():
        raise argparse.ArgumentTypeError(f"'{val}' is not a directory")
    return path


def existing_dir(val: str) -> Path:
    """
    Parses argument as existing directory path.

    For use as type of argparse argument.
    Args:
        val: input string

    Returns:
        Directory Path after validating it is a directory.
    """
    path = existing_path(val).expanduser()
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f"'{val}' is not a directory")
    return path


class _SubcommandParser(argparse.ArgumentParser):
    """Parser for subcommands"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.main = lambda args, prog=None: 0  # pragma: no cover

    def parse_known_args(self, args=None, namespace=None):
        """Puts all arguments into args attribute, and copies main to main attribute."""
        if namespace is None:  # pragma: no branch
            namespace = argparse.Namespace()
        setattr(namespace, 'args', args)
        setattr(namespace, 'main', self.main)
        return namespace, []


class Subcommands:
    """
    Add subcommands
    """

    _parser: argparse.ArgumentParser
    _subparsers: argparse._SubParsersAction
    _subcommands: list[str]

    def __init__(self, parser: argparse.ArgumentParser):
        self._parser = parser
        self._subcommands = []
        self._subparsers = parser.add_subparsers(
            title="Commands",
            dest="subcmd",
            metavar="<command>",
            required=True,
            parser_class=_SubcommandParser,
        )

    @property
    def subcommands(self) -> Sequence[str]:
        """List of subcommand words"""
        return tuple(self._subcommands)

    def add_subcommand(
        self,
        cmd: str,
        main_func: str,
        help: str,
        *,
        aliases: Sequence[str] = (),
    ) -> argparse.ArgumentParser:
        """
        Add a subcommand.

        Args:
            cmd: the command word
            main_func: fully qualified name of main function
                e.g. "whl2conda.cli.convert.convert_main"
            help: help string
            aliases: optional aliases for subcommand
        """
        self._subcommands.append(cmd)
        subparser = self._subparsers.add_parser(
            cmd, help=help, add_help=False, aliases=aliases
        )
        modulename, func = main_func.rsplit(".", maxsplit=1)

        def _main(args: Sequence[str], prog: str):
            module = importlib.import_module(modulename)
            real_main = getattr(module, func)
            real_main(args, prog)

        subparser.main = _main
        return subparser

    def run(self, parsed: argparse.Namespace) -> None:
        """
        Runs chosen subcommand

        Args:
            parsed: parsed arguments
        """
        parsed.main(parsed.args, prog=f'{self._parser.prog} {parsed.subcmd}')


def get_conda_bld_path() -> Path:
    """Lookup conda-bld directory path from conda config"""
    config = json.loads(
        subprocess.check_output(
            ["conda", "config", "--show", "--json"],
            encoding="utf8",
        )
    )
    conda_bld = config.get("bld_path") or config.get("croot")
    if not conda_bld:  # pragma: no cover
        # this is extremely unlikely to ever occur
        raise LookupError("Cannot find conda-bld location")
    return Path(conda_bld)
