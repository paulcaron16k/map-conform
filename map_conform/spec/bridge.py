"""Draft a spec from a catalog, and export canonical types to Zamboni (WBS 9.1, 9.2).

``spec import --catalog`` writes a starting spec: one stream rule per catalog stream, its
key properties, and each property as a column with an explicit canonical type (from the
catalog, or from a Zamboni table-config's ``columns``) and its description as ``doc``.
Names are left to the conformer; the draft validates against the catalog it came from.

``spec export --zamboni`` compiles each catalog stream exactly as the mapper would and
writes the output columns' types into the table-config (:mod:`map_conform.spec.zamboni`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from map_conform.metadata import INTEGER_COLUMNS, TIMESTAMP_COLUMNS
from map_conform.naming.streams import stream_name
from map_conform.plan.compile import compile_stream
from map_conform.spec.check import Finding, output_columns
from map_conform.spec.load import ResolvedStream, output_streams, resolve_stream
from map_conform.spec.model import parse_spec
from map_conform.spec.zamboni import set_table_columns, table_columns
from map_conform.types.canonical import CTypeError, parse_ctype
from map_conform.types.from_jsonschema import from_jsonschema

if TYPE_CHECKING:
    from map_conform.spec.check import CatalogStream
    from map_conform.spec.model import Spec
    from map_conform.transforms.registry import Registry

_DEFAULT = parse_spec({"version": 1}, "the default spec")


def draft_from_catalog(
    catalog: list[CatalogStream],
    zamboni: dict[str, Any] | None = None,
    namespace: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """A spec for the catalog's streams, and notes for the user."""
    notes: list[str] = []
    streams: dict[str, Any] = {}
    for entry in catalog:
        resolved = _default_rules(entry.name)
        findings: list[Finding] = []
        named = output_columns(resolved, entry.properties, findings, entry.name)
        table = stream_name(resolved).name
        declared = table_columns(zamboni, namespace, table) if zamboni and namespace else {}
        columns: dict[str, Any] = {}
        for column in named:
            if not column.sources:
                continue
            source = column.sources[0]
            schema = entry.properties.get(source) or {}
            inferred = from_jsonschema(schema, "json")
            notes.extend(f"{entry.name}.{source}: {w}" for w in inferred.warnings)
            type_ = str(inferred.ctype)
            if column.name in declared:
                try:
                    type_ = str(parse_ctype(declared[column.name]))
                except CTypeError:
                    notes.append(
                        f"{entry.name}.{source}: Zamboni type {declared[column.name]!r} is not "
                        f"a canonical type; kept {type_} from the catalog"
                    )
            rule: dict[str, Any] = {"type": type_}
            if isinstance(schema.get("description"), str):
                rule["doc"] = schema["description"]
            columns[source] = rule
        stream: dict[str, Any] = {}
        if entry.key_properties:
            stream["key_properties"] = list(entry.key_properties)
        stream["columns"] = columns
        streams[entry.name] = stream
    return {"version": 1, "streams": streams}, notes


def _default_rules(tap_stream: str) -> ResolvedStream:
    resolved = resolve_stream(_DEFAULT, tap_stream)
    if resolved is None:  # pragma: no cover -- the default spec keeps every stream
        msg = f"the default spec dropped {tap_stream!r}"
        raise AssertionError(msg)
    return resolved


def export_columns(  # noqa: PLR0913 -- the spec, the catalog and the file to fill
    spec: Spec,
    catalog: list[CatalogStream],
    document: dict[str, Any],
    namespace: str,
    *,
    registry: Registry,
    config: dict[str, Any] | None = None,
) -> list[str]:
    """Write each output stream's column types into the table-config; the tables written."""
    written: list[str] = []
    for entry in catalog:
        schema = {"type": "object", "properties": dict(entry.properties)}
        for resolved in output_streams(spec, entry.name):
            plan = compile_stream(
                spec, resolved, schema, registry, key_properties=entry.key_properties,
                config=config,
            )  # fmt: skip
            columns = {c.name: str(c.ctype) for c in plan.columns}
            if resolved.settings.add_record_metadata:
                columns.update(dict.fromkeys(TIMESTAMP_COLUMNS, "timestamptz"))
                columns.update(dict.fromkeys(INTEGER_COLUMNS, "int64"))
            set_table_columns(document, namespace, plan.name, columns)
            written.append(f"{namespace}.{plan.name}")
    return written
