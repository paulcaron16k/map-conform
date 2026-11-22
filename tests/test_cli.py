"""The map-conform executable dispatches tool subcommands and runs the mapper otherwise."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

EXECUTABLE = str(Path(sys.executable).with_name("map-conform"))


def run(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the installed console script."""
    return subprocess.run(  # noqa: S603 -- fixed argv: the installed console script
        [EXECUTABLE, *args], capture_output=True, text=True, check=False, timeout=60
    )


def test_spec_subcommand_is_dispatched() -> None:
    """`map-conform spec schema` reaches the tool group."""
    result = run("spec", "schema")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["title"] == "map-conform spec (version 1)"


def test_mapper_flags_reach_the_sdk() -> None:
    """`map-conform --about` is still the Singer SDK's CLI."""
    result = run("--about", "--format", "json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["name"] == "map-conform"


def test_tool_help_lists_spec() -> None:
    """The tool group documents its subcommands."""
    result = run("spec", "--help")
    assert result.returncode == 0
    assert "schema" in result.stdout


def test_functions_lists_steps_and_expression_functions() -> None:
    """`map-conform functions` documents builtins and the expression library (WBS 6.2)."""
    result = run("functions", "--json")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    steps = {step["name"]: step for step in report["steps"]}
    assert steps["hash"]["signature"] == "algo='sha256', salt='', skip_first=0"
    assert all(step["doc"] for step in report["steps"])
    assert "decimal(p,s)" not in report["casts"]
    assert "timestamptz" in report["casts"]
    functions = {fn["name"]: fn for fn in report["functions"]}
    assert functions["coalesce"]["group"] == "misc"
    text = run("functions").stdout
    assert "Expression functions: predicates" in text
    assert '  parse_datetime(value, *formats, tz="UTC")' in text
