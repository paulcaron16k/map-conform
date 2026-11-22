"""The ``map-conform`` command.

Meltano runs the mapper as ``map-conform --config ... [--about]``; those arguments go to the
Singer SDK's CLI unchanged. Tool subcommands (``map-conform spec ...``) are handled here.
"""

from __future__ import annotations

import sys

import click

from map_conform.mapper import MapConformMapper
from map_conform.spec.jsonschema import render

TOOL_COMMANDS = frozenset({"spec"})


@click.group(name="map-conform")
def tools() -> None:
    """map-conform tools. Run without a subcommand, map-conform is the Singer mapper."""


@tools.group()
def spec() -> None:
    """Work with conform spec files."""


@spec.command(name="schema")
def spec_schema() -> None:
    """Print the conform spec's JSON Schema."""
    click.echo(render(), nl=False)


def main(argv: list[str] | None = None) -> None:
    """Dispatch to a tool subcommand, or run the mapper."""
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] in TOOL_COMMANDS:
        tools.main(args=args, prog_name="map-conform")
    else:
        MapConformMapper.cli.main(args=args, prog_name="map-conform")
