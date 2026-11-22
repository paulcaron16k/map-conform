"""The ``map-conform`` command.

Meltano runs the mapper as ``map-conform --config ... [--about]``; those arguments go to the
Singer SDK's CLI unchanged. Tool subcommands (``map-conform spec ...``) are handled here.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from typing import TYPE_CHECKING, Any

import click

from map_conform.expr.functions import FUNCTIONS
from map_conform.mapper import MapConformMapper
from map_conform.plan.compile import compile_stream, plan_report
from map_conform.spec.check import CatalogStream, check_spec, explain, read_catalog
from map_conform.spec.errors import SpecError
from map_conform.spec.jsonschema import render
from map_conform.spec.load import load_spec, output_streams
from map_conform.transforms.builtins import builtin_registry

if TYPE_CHECKING:
    from map_conform.spec.model import Spec
    from map_conform.transforms.registry import Transform

TOOL_COMMANDS = frozenset({"spec", "functions"})


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


_SPEC_ARG = click.argument("spec_path", metavar="SPEC", type=click.Path(dir_okay=False))
_CATALOG = click.option(
    "--catalog",
    type=click.Path(exists=True, dir_okay=False),
    help="A Singer catalog to check the spec against.",
)
_VARS = click.option(
    "--var",
    "variables",
    multiple=True,
    metavar="NAME=VALUE",
    help="A spec variable for ${NAME}; repeatable.",
)


def _load(
    spec_path: str, variables: tuple[str, ...], catalog_path: str | None
) -> tuple[Spec, list[CatalogStream] | None]:
    """Load the spec (and catalog), or print every problem and exit 1."""
    spec_vars: dict[str, Any] = {}
    for item in variables:
        name, sep, value = item.partition("=")
        if not sep or not name:
            raise click.BadParameter(f"{item!r} is not NAME=VALUE", param_hint="--var")
        spec_vars[name] = value
    try:
        spec = load_spec(spec_path, spec_vars=spec_vars)
        catalog = read_catalog(catalog_path) if catalog_path else None
    except SpecError as exc:
        click.echo(f"{exc.source}: {len(exc.issues)} problem(s)", err=True)
        for issue in exc.issues:
            click.echo(f"  {issue}", err=True)
        sys.exit(1)
    return spec, catalog


@spec.command(name="validate")
@_SPEC_ARG
@_CATALOG
@_VARS
@click.option("--strict", is_flag=True, help="Treat warnings as errors.")
def spec_validate(
    spec_path: str, catalog: str | None, variables: tuple[str, ...], *, strict: bool
) -> None:
    """Parse SPEC strictly and report every problem with its path.

    With --catalog, also check it against the catalog's streams: output names, column
    references, explicit names, collisions, key properties and undeclared columns.
    """
    loaded, streams = _load(spec_path, variables, catalog)
    findings = check_spec(loaded, streams)
    for finding in findings:
        click.echo(str(finding), err=True)
    errors = [f for f in findings if f.severity == "error" or strict]
    if errors:
        click.echo(f"{spec_path}: {len(errors)} problem(s)", err=True)
        sys.exit(1)
    checked = f", checked against {len(streams)} catalog stream(s)" if streams else ""
    click.echo(f"{spec_path}: valid ({len(loaded.streams)} stream rule(s){checked})")


@spec.command(name="explain")
@_SPEC_ARG
@click.option("--stream", "tap_stream", required=True, help="The tap stream to explain.")
@_CATALOG
@_VARS
@click.option("--json", "as_json", is_flag=True, help="Print the report as JSON.")
def spec_explain(
    spec_path: str,
    tap_stream: str,
    catalog: str | None,
    variables: tuple[str, ...],
    *,
    as_json: bool,
) -> None:
    """Show what SPEC does to one tap stream: rules matched, output names, columns."""
    loaded, streams = _load(spec_path, variables, catalog)
    report = explain(loaded, tap_stream, streams)
    entry = next((s for s in streams or [] if s.name == tap_stream), None)
    if entry is not None:
        _add_plans(loaded, entry, report)
    if as_json:
        click.echo(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        click.echo(_render_explain(report))
    if report["findings"]:
        sys.exit(1)


def _add_plans(loaded: Spec, entry: CatalogStream, report: dict[str, Any]) -> None:
    """Compile each output stream against the catalog schema and add the plan."""
    schema = {"type": "object", "properties": dict(entry.properties)}
    for output, resolved in zip(report["outputs"], output_streams(loaded, entry.name), strict=True):
        try:
            plan = compile_stream(
                loaded, resolved, schema, builtin_registry(), key_properties=entry.key_properties
            )
        except SpecError as exc:
            report["findings"].extend(str(i) for i in exc.issues)
            continue
        output["plan"] = plan_report(plan)


def _render_plan(plan: dict[str, Any]) -> list[str]:
    lines = ["  plan:"]
    for column in plan["columns"]:
        flags = "" if column["nullable"] else " not null"
        lines.append(
            f"    {column['name']}: {column['type']}{flags}, on_error {column['on_error']}"
        )
        lines.append(f"      steps: {' -> '.join(column['steps'])}")
        if "default" in column:
            lines.append(f"      default: {column['default']}")
        if "enum" in column:
            lines.append(f"      enum: {', '.join(column['enum'])}")
    return lines


def _render_column(column: dict[str, Any]) -> list[str]:
    source = ", ".join(column["source"] or ["(derived)"])
    kind = column["type"] or (f"tap {column['tap_type']}" if column["tap_type"] else "?")
    extra = "" if column["declared"] else "  [undeclared]"
    lines = [f"    {source} -> {column['name']}  {kind}{extra}"]
    if "expr" in column:
        lines.append(f"      expr: {column['expr']}")
    if "transform" in column:
        lines.append(f"      transform: {json.dumps(column['transform'], ensure_ascii=False)}")
    lines.extend(f"      note: {note}" for note in column.get("notes", []))
    return lines


def _render_explain(report: dict[str, Any]) -> str:
    lines = [f"tap stream: {report['tap_stream']}"]
    if report["in_catalog"] is False:
        lines.append("  (not in the catalog: only the spec's columns are known)")
    lines.append(f"rules matched: {', '.join(report['matched']) or '(none: defaults)'}")
    if report.get("dropped"):
        lines.append("dropped: no output stream")
    for output in report["outputs"]:
        lines.append("")
        origin = f" (from streams key {output['key']!r})" if output["key"] else ""
        lines.append(f"output stream: {output['name']}{origin}")
        if output["key_properties"]:
            lines.append(f"  key properties: {', '.join(output['key_properties'])}")
        if output["filter"]:
            lines.append(f"  filter: {output['filter']}")
        if output["settings"]:
            lines.append(f"  overrides: {json.dumps(output['settings'], ensure_ascii=False)}")
        lines.append("  columns:")
        for column in output["columns"]:
            lines.extend(_render_column(column))
        if "plan" in output:
            lines.extend(_render_plan(output["plan"]))
    if report["findings"]:
        lines.append("")
        lines.extend(f"problem: {f}" for f in report["findings"])
    return "\n".join(lines)


@tools.command(name="functions")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def functions(*, as_json: bool) -> None:
    """List the builtin steps and the functions expressions can call."""
    report = functions_report()
    if as_json:
        click.echo(json.dumps(report, indent=2))
        return
    lines = ["Builtin steps:"]
    for step in report["steps"]:
        flags = " [vectorised]" if step["vectorised"] else ""
        lines.append(f"  {step['name']}({step['signature']}){flags}")
        if step["doc"]:
            lines.append(f"      {step['doc']}")
    lines.append(f"  cast: one of {', '.join(report['casts'])}")
    group = None
    for fn in report["functions"]:
        if fn["group"] != group:
            group = fn["group"]
            lines.extend(["", f"Expression functions: {group}"])
        lines.append(f"  {fn['signature']}")
        lines.append(f"      {fn['doc']}")
    click.echo("\n".join(lines))


def functions_report() -> dict[str, Any]:
    """Builtin steps, cast targets and expression functions, as plain data."""
    registry = builtin_registry()
    groups = ("predicates", "coercion", "temporal", "text", "numeric", "misc", "python", "modules")
    ordered = sorted(FUNCTIONS.values(), key=lambda f: (groups.index(f.group), f.name))
    return {
        "steps": [_step_report(t) for _, t in sorted(registry.names().items())],
        "casts": sorted(registry.casts),
        "functions": [
            {"name": f.name, "group": f.group, "signature": f.signature, "doc": f.doc}
            for f in ordered
        ],
    }


def _step_report(transform: Transform) -> dict[str, Any]:
    params = [
        f"{f.name}={f.default!r}" if _shown_default(f.default) else f.name
        for f in dataclasses.fields(transform.kwargs)
    ]
    return {
        "name": transform.name,
        "signature": ", ".join(params),
        "positional": transform.positional,
        "accepts": sorted(transform.accepts),
        "vectorised": transform.vectorised,
        "doc": transform.doc,
    }


def _shown_default(default: object) -> bool:
    """Whether a kwarg's default is a real value (not missing, not an internal sentinel)."""
    return default is not dataclasses.MISSING and isinstance(
        default, (str, int, float, bool, tuple, type(None))
    )


def main(argv: list[str] | None = None) -> None:
    """Dispatch to a tool subcommand, or run the mapper."""
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] in TOOL_COMMANDS:
        tools.main(args=args, prog_name="map-conform")
    else:
        MapConformMapper.cli.main(args=args, prog_name="map-conform")
