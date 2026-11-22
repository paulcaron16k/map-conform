"""The ``map-conform`` command.

Meltano runs the mapper as ``map-conform --config ... [--about]``; those arguments go to the
Singer SDK's CLI unchanged. Tool subcommands (``map-conform spec ...``) are handled here.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click
import yaml

from map_conform.doctor import check_project
from map_conform.expr.functions import FUNCTIONS
from map_conform.mapper import MapConformMapper
from map_conform.plan.compile import compile_stream, plan_report
from map_conform.spec.bridge import draft_from_catalog, export_columns
from map_conform.spec.check import CatalogStream, check_spec, explain, read_catalog
from map_conform.spec.errors import SpecError
from map_conform.spec.importer import import_stream_maps
from map_conform.spec.jsonschema import render
from map_conform.spec.load import load_spec, output_streams
from map_conform.spec.zamboni import namespace_of, read_table_config, write_table_config
from map_conform.transforms.builtins import builtin_registry
from map_conform.udfs import load_udfs, registry_with

if TYPE_CHECKING:
    from map_conform.spec.model import Spec
    from map_conform.transforms.registry import Registry, Transform

TOOL_COMMANDS = frozenset({"spec", "functions", "doctor"})


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
_ZAMBONI = click.option(
    "--zamboni",
    type=click.Path(exists=True, dir_okay=False),
    help="A Zamboni table-config (version 2) whose columns give the types.",
)
_NAMESPACE = click.option(
    "--namespace", help="The Zamboni namespace, when the table-config has several."
)
_VARS = click.option(
    "--var",
    "variables",
    multiple=True,
    metavar="NAME=VALUE",
    help="A spec variable for ${NAME}; repeatable.",
)


def _spec_vars(variables: tuple[str, ...]) -> dict[str, Any]:
    spec_vars: dict[str, Any] = {}
    for item in variables:
        name, sep, value = item.partition("=")
        if not sep or not name:
            raise click.BadParameter(f"{item!r} is not NAME=VALUE", param_hint="--var")
        spec_vars[name] = value
    return spec_vars


def _load(
    spec_path: str, variables: tuple[str, ...], catalog_path: str | None
) -> tuple[Spec, list[CatalogStream] | None]:
    """Load the spec (and catalog), or print every problem and exit 1."""
    spec_vars = _spec_vars(variables)
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


@spec.command(name="import")
@click.option(
    "--stream-maps",
    "config_path",
    type=click.Path(exists=True, dir_okay=False),
    help="A plugin config (JSON) with SDK stream_maps and flattening settings.",
)
@_CATALOG
@_ZAMBONI
@_NAMESPACE
@click.option(
    "-o", "--output", type=click.Path(dir_okay=False), help="Write the spec here, not stdout."
)
def spec_import(
    config_path: str | None,
    catalog: str | None,
    zamboni: str | None,
    namespace: str | None,
    output: str | None,
) -> None:
    """Draft a spec from a catalog (and Zamboni columns), or convert SDK stream_maps.

    With --stream-maps, the SDK settings become a native spec, and --catalog makes the types
    the SDK takes from tap properties explicit. Without it, --catalog drafts a spec with an
    explicit canonical type for every property, taken from --zamboni's columns where given.
    """
    if config_path is None and catalog is None:
        raise click.UsageError("give --catalog CATALOG.json, --stream-maps CONFIG.json, or both")
    if zamboni is not None and (config_path is not None or catalog is None):
        raise click.UsageError(
            "--zamboni drafts from a --catalog; it does not apply to stream maps"
        )
    try:
        streams = read_catalog(catalog) if catalog else None
        if config_path is not None:
            config = json.loads(Path(config_path).read_text(encoding="utf-8"))
            native, notes = import_stream_maps(config, streams)
        else:
            assert streams is not None  # noqa: S101 -- checked above
            document = read_table_config(zamboni) if zamboni else None
            space = namespace_of(document, namespace, zamboni) if document and zamboni else None
            native, notes = draft_from_catalog(streams, document, space)
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"cannot read {config_path}: {exc}") from exc
    except SpecError as exc:
        click.echo(f"{exc.source}: {len(exc.issues)} problem(s)", err=True)
        for issue in exc.issues:
            click.echo(f"  {issue}", err=True)
        sys.exit(1)
    text = yaml.safe_dump(native, sort_keys=False, allow_unicode=True, width=100)
    if output:
        Path(output).write_text(text, encoding="utf-8")
    else:
        click.echo(text, nl=False)
    for note in notes:
        click.echo(f"note: {note}", err=True)


@spec.command(name="export")
@_SPEC_ARG
@click.option(
    "--zamboni",
    "zamboni",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="The Zamboni table-config (version 2) whose columns to fill.",
)
@click.option(
    "--catalog",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="The Singer catalog to compile each stream against.",
)
@_NAMESPACE
@_VARS
@click.option(
    "-o", "--output", type=click.Path(dir_okay=False), help="Write here instead of in place."
)
def spec_export(  # noqa: PLR0913 -- one parameter per option
    spec_path: str,
    *,
    zamboni: str,
    catalog: str,
    namespace: str | None,
    variables: tuple[str, ...],
    output: str | None,
) -> None:
    """Write each output stream's canonical column types into Zamboni table-config columns."""
    loaded, streams = _load(spec_path, variables, catalog)
    assert streams is not None  # noqa: S101 -- --catalog is required
    try:
        document = read_table_config(zamboni)
        space = namespace_of(document, namespace, zamboni)
        registry = _registry(loaded, allow_python_udfs=False)
        written = export_columns(
            loaded, streams, document, space, registry=registry, config=_spec_vars(variables)
        )
    except SpecError as exc:
        click.echo(f"{exc.source}: {len(exc.issues)} problem(s)", err=True)
        for issue in exc.issues:
            click.echo(f"  {issue}", err=True)
        sys.exit(1)
    write_table_config(document, output or zamboni)
    click.echo(f"{output or zamboni}: columns written for {', '.join(written) or 'no table'}")


@spec.command(name="explain")
@_SPEC_ARG
@click.option("--stream", "tap_stream", required=True, help="The tap stream to explain.")
@_CATALOG
@_VARS
@click.option("--json", "as_json", is_flag=True, help="Print the report as JSON.")
@click.option(
    "--allow-python-udfs",
    is_flag=True,
    help="Import the spec's module-path UDFs, as the allow_python_udfs setting does.",
)
def spec_explain(  # noqa: PLR0913 -- one parameter per option
    spec_path: str,
    tap_stream: str,
    catalog: str | None,
    variables: tuple[str, ...],
    *,
    as_json: bool,
    allow_python_udfs: bool,
) -> None:
    """Show what SPEC does to one tap stream: rules matched, output names, columns."""
    loaded, streams = _load(spec_path, variables, catalog)
    report = explain(loaded, tap_stream, streams)
    entry = next((s for s in streams or [] if s.name == tap_stream), None)
    if entry is not None:
        try:
            registry = _registry(loaded, allow_python_udfs=allow_python_udfs)
        except SpecError as exc:
            report["findings"].extend(str(i) for i in exc.issues)
        else:
            _add_plans(loaded, entry, report, _spec_vars(variables), registry)
    if as_json:
        click.echo(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        click.echo(_render_explain(report))
    if report["findings"]:
        sys.exit(1)


def _registry(loaded: Spec | None, *, allow_python_udfs: bool) -> Registry:
    """The builtins plus installed UDFs (and the spec's, when allowed)."""
    spec_udfs = loaded.udfs if loaded is not None else {}
    udfs = load_udfs(spec_udfs, allow_python_udfs=allow_python_udfs)
    return registry_with(builtin_registry(), udfs)


def _add_plans(
    loaded: Spec,
    entry: CatalogStream,
    report: dict[str, Any],
    config: dict[str, Any],
    registry: Registry,
) -> None:
    """Compile each output stream against the catalog schema and add the plan."""
    schema = {"type": "object", "properties": dict(entry.properties)}
    for output, resolved in zip(report["outputs"], output_streams(loaded, entry.name), strict=True):
        try:
            plan = compile_stream(
                loaded,
                resolved,
                schema,
                registry,
                key_properties=entry.key_properties,
                config=config,
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
        if "reads" in column:
            lines.append(f"      reads: {', '.join(column['reads'])}")
    if "filter" in plan:
        lines.append(f"    filter: {plan['filter']}")
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


@tools.command(name="doctor")
@click.option(
    "--meltano-yml",
    "meltano_yml",
    default="meltano.yml",
    show_default=True,
    type=click.Path(dir_okay=False),
    help="The Meltano project file.",
)
@click.option("--strict", is_flag=True, help="Treat warnings as errors.")
def doctor(meltano_yml: str, *, strict: bool) -> None:
    """Check a Meltano project's use of map-conform: settings, spec, UDFs, targets' metadata."""
    findings = check_project(meltano_yml)
    for finding in findings:
        click.echo(str(finding), err=finding.severity != "note")
    failing = [f for f in findings if f.severity == "error" or (strict and f.severity == "warning")]
    if failing:
        click.echo(f"{meltano_yml}: {len(failing)} problem(s)", err=True)
        sys.exit(1)
    click.echo(f"{meltano_yml}: no problems found")


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
        flags = (" [vectorised]" if step["vectorised"] else "") + (" [udf]" if step["udf"] else "")
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
    """Builtin steps (and installed UDFs), cast targets and expression functions."""
    registry = _registry(None, allow_python_udfs=False)
    groups = ("predicates", "coercion", "temporal", "text", "numeric", "misc", "python", "modules")
    ordered = sorted(FUNCTIONS.values(), key=lambda f: (groups.index(f.group), f.name))
    builtins = builtin_registry().names()
    return {
        "steps": [
            {**_step_report(t), "udf": name not in builtins}
            for name, t in sorted(registry.names().items())
        ],
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
