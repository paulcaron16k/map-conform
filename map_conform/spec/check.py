"""Check a spec against a Singer catalog, and explain what it does to a stream.

``map-conform spec validate --catalog`` and ``spec explain`` are built on this module. The
column naming here (:func:`output_columns`) is the one the plan compiler uses, so what
``explain`` shows is what the mapper emits.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from map_conform.naming.conform import NameConformer, NamingError
from map_conform.naming.streams import stream_name
from map_conform.spec._struct import Issue, child, dump, thaw
from map_conform.spec.errors import SpecError
from map_conform.spec.load import ResolvedStream, matching_keys, output_streams
from map_conform.spec.model import ColumnSpec, Defaults, Spec

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class Finding:
    """A problem found when checking a spec against a catalog."""

    severity: Severity
    path: str
    message: str

    @override
    def __str__(self) -> str:
        """``warning: path: message`` or ``path: message``."""
        prefix = "warning: " if self.severity == "warning" else ""
        return f"{prefix}{self.path or '<root>'}: {self.message}"


@dataclass(frozen=True)
class CatalogStream:
    """The parts of a catalog entry the spec is checked against."""

    name: str
    properties: Mapping[str, Any]
    key_properties: tuple[str, ...]


def read_catalog(path: str | Path) -> list[CatalogStream]:
    """Read a Singer catalog (``{"streams": [...]}``).

    Raises:
        SpecError: if the file is unreadable or not a catalog.
    """
    source = str(path)
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise SpecError([Issue("", f"cannot read the catalog: {exc.strerror}")], source) from exc
    except json.JSONDecodeError as exc:
        where = f"line {exc.lineno}, column {exc.colno}"
        raise SpecError([Issue("", f"invalid JSON at {where}: {exc.msg}")], source) from exc
    streams = document.get("streams") if isinstance(document, dict) else None
    if not isinstance(streams, list):
        raise SpecError([Issue("", "a Singer catalog needs a 'streams' list")], source)
    out: list[CatalogStream] = []
    for entry in streams:
        name = entry.get("tap_stream_id") or entry.get("stream")
        schema = entry.get("schema") or {}
        keys = entry.get("key_properties")
        if keys is None:
            top: dict[str, Any] = next(
                (m for m in entry.get("metadata", []) if m.get("breadcrumb") == []), {}
            )
            keys = top.get("metadata", {}).get("table-key-properties", [])
        out.append(CatalogStream(name, schema.get("properties") or {}, tuple(keys)))
    return out


# --- Columns -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class OutputColumn:
    """One column of an output stream, as the plan will emit it."""

    key: str
    """The ``columns`` key, or the source property name for an undeclared column."""
    name: str
    """The output name."""
    spec: ColumnSpec | None
    """The column's rules, or None for an undeclared column."""
    sources: tuple[str, ...]
    """Source properties read (empty for a derived column)."""
    tap_schema: Mapping[str, Any] | None
    """The source property's JSON Schema, when there is exactly one source in the catalog."""
    notes: tuple[str, ...] = field(default=())


def output_columns(
    resolved: ResolvedStream,
    properties: Mapping[str, Any] | None,
    findings: list[Finding],
    path: str,
) -> list[OutputColumn]:
    """The output columns of a resolved stream, named and de-duplicated.

    With ``properties`` (from a catalog or tap SCHEMA), undeclared columns follow
    ``undeclared`` and references are checked. Without them, only the spec's columns are
    known. Problems are appended to ``findings``.
    """
    if properties is not None and resolved.settings.metadata == "sdc":
        # The tap's own _sdc_* columns feed the metadata columns, not ordinary ones.
        properties = {k: v for k, v in properties.items() if not k.startswith("_sdc_")}
    conformer = NameConformer(resolved.settings.naming)
    entries = _column_entries(resolved, properties, findings, path)
    explicit: dict[str, str] = {}
    for key, spec, _ in entries:
        if spec is not None and spec.name is not None:
            fixed = conformer.conform(spec.name).name
            if fixed != spec.name:
                findings.append(
                    Finding(
                        "error",
                        child(child(path, "columns"), key),
                        f"name {spec.name!r} is not a legal name here; it "
                        f"would conform to {fixed!r}",
                    )
                )
            explicit[key] = spec.name
    to_conform = [key for key, _, _ in entries if key not in explicit]
    try:
        conformed = {c.source: c for c in conformer.conform_all(to_conform)}
    except NamingError as exc:
        findings.append(Finding("error", child(path, "columns"), str(exc)))
        conformed = {k: conformer.conform(k) for k in to_conform}
    out: list[OutputColumn] = []
    seen: dict[str, str] = {}
    for key, spec, sources in entries:
        name = explicit.get(key) or conformed[key].name
        notes = () if key in explicit else conformed[key].notes
        clash = seen.get(name.casefold())
        if clash is not None:
            findings.append(
                Finding(
                    "error",
                    child(child(path, "columns"), key),
                    f"output name {name!r} is also used by {clash!r}",
                )
            )
        seen[name.casefold()] = key
        tap = properties.get(sources[0]) if properties and len(sources) == 1 else None
        out.append(OutputColumn(key, name, spec, sources, tap, notes))
    _check_key_properties(resolved, out, findings, path)
    return out


def _column_entries(
    resolved: ResolvedStream,
    properties: Mapping[str, Any] | None,
    findings: list[Finding],
    path: str,
) -> list[tuple[str, ColumnSpec | None, tuple[str, ...]]]:
    """(key, spec, sources) for each output column, in output order, drops removed."""
    settings, columns = resolved.settings, resolved.spec.columns
    entries: list[tuple[str, ColumnSpec | None, tuple[str, ...]]] = []
    known = properties if properties is not None else {}
    for key, spec in columns.items():
        col_path = child(child(path, "columns"), key)
        sources = _sources(key, spec)
        if properties is not None:
            missing = [s for s in sources if s not in known]
            if missing and spec.expr is None:
                what = "source column" if spec.source is not None else "column"
                findings.append(
                    Finding(
                        "error",
                        col_path,
                        f"{what} {', '.join(map(repr, missing))} is not in the "
                        "catalog stream; a new column needs expr",
                    )
                )
        if spec.drop:
            continue
        derived = spec.expr is not None and spec.source is None and key not in known
        entries.append((key, spec, () if derived else sources))
    if properties is None:
        return entries
    claimed = {s for _, _, sources in entries for s in sources} | {
        k for k, s in columns.items() if s.drop
    }
    undeclared = [p for p in properties if p not in claimed and p not in columns]
    if settings.undeclared == "error":
        findings.extend(
            Finding("error", child(path, "columns"), f"undeclared column {p!r} (undeclared: error)")
            for p in undeclared
        )
    elif settings.undeclared == "conform":
        entries.extend((p, None, (p,)) for p in undeclared)
    if resolved.spec.order == "source":
        position = {name: i for i, name in enumerate(properties)}
        entries.sort(key=lambda e: position.get(e[2][0] if e[2] else "", len(position)))
    return entries


def _sources(key: str, spec: ColumnSpec) -> tuple[str, ...]:
    if spec.source is None:
        return (key,)
    return (spec.source,) if isinstance(spec.source, str) else spec.source


def _check_key_properties(
    resolved: ResolvedStream, columns: list[OutputColumn], findings: list[Finding], path: str
) -> None:
    """An overriding key_properties names source or output columns that exist."""
    if resolved.spec.key_properties is None:
        return
    names = {c.name for c in columns} | {s for c in columns for s in c.sources}
    findings.extend(
        Finding(
            "error",
            child(path, "key_properties"),
            f"{key!r} is neither a source nor an output column",
        )
        for key in resolved.spec.key_properties
        if key not in names
    )


# --- Whole-spec check ----------------------------------------------------------------------------


def check_spec(spec: Spec, catalog: list[CatalogStream] | None) -> list[Finding]:
    """Everything wrong with ``spec``, checked against ``catalog`` when one is given."""
    findings: list[Finding] = []
    if catalog is None:
        return findings
    by_name = {s.name: s for s in catalog}
    matched: set[str] = set()
    outputs: dict[str, str] = {}
    for stream in catalog:
        matched.update(matching_keys(spec, stream.name))
        for resolved in output_streams(spec, stream.name):
            key = resolved.key or stream.name
            path = child("streams", key)
            try:
                name = stream_name(resolved).name
            except NamingError as exc:
                findings.append(Finding("error", path, exc.reason))
                continue
            if (other := outputs.get(name.casefold())) is not None:
                findings.append(
                    Finding("error", path, f"output stream {name!r} is also produced by {other!r}")
                )
            outputs[name.casefold()] = key
            _check_stream_keys(resolved, stream, findings, path)
            output_columns(resolved, stream.properties, findings, path)
    for key, rules in spec.streams.items():
        if rules.spec.source is not None:
            matched.add(key)
            if rules.spec.source not in by_name:
                findings.append(
                    Finding(
                        "error",
                        child(child("streams", key), "source"),
                        f"tap stream {rules.spec.source!r} is not in the catalog",
                    )
                )
        elif key not in matched:
            findings.append(
                Finding("warning", child("streams", key), "matches no stream in the catalog")
            )
    return findings


def _check_stream_keys(
    resolved: ResolvedStream, stream: CatalogStream, findings: list[Finding], path: str
) -> None:
    for key in stream.key_properties:
        column = resolved.spec.columns.get(key)
        if column is not None and column.drop:
            findings.append(
                Finding(
                    "error", child(child(path, "columns"), key), "a key property cannot be dropped"
                )
            )


# --- Explain ---------------------------------------------------------------------------------


def explain(spec: Spec, tap_stream: str, catalog: list[CatalogStream] | None) -> dict[str, Any]:
    """A plain-data account of what the spec does to one tap stream."""
    entry = next((s for s in catalog or [] if s.name == tap_stream), None)
    properties = entry.properties if entry is not None else None
    report: dict[str, Any] = {
        "tap_stream": tap_stream,
        "in_catalog": entry is not None if catalog is not None else None,
        "matched": matching_keys(spec, tap_stream),
        "outputs": [],
        "findings": [],
    }
    findings: list[Finding] = []
    outputs = output_streams(spec, tap_stream)
    if not outputs:
        report["dropped"] = True
    for resolved in outputs:
        path = child("streams", resolved.key or tap_stream)
        try:
            name: str | None = stream_name(resolved).name
        except NamingError as exc:
            findings.append(Finding("error", path, exc.reason))
            name = None
        columns = output_columns(resolved, properties, findings, path)
        report["outputs"].append(
            {
                "name": name,
                "key": resolved.key,
                "settings": thaw(_changed(resolved.settings, spec.defaults)),
                "key_properties": list(
                    resolved.spec.key_properties or (entry.key_properties if entry else ())
                ),
                "filter": resolved.spec.filter,
                "columns": [_column_report(c) for c in columns],
            }
        )
    report["findings"] = [str(f) for f in findings]
    return report


def _changed(settings: Defaults, defaults: Defaults) -> object:
    """The settings this stream overrides, relative to the spec's defaults."""
    mine, base = thaw(dump(settings, full=True)), thaw(dump(defaults, full=True))
    return _diff(mine, base)


def _diff(mine: object, base: object) -> object:
    if isinstance(mine, dict) and isinstance(base, dict):
        return {k: _diff(v, base.get(k)) for k, v in mine.items() if v != base.get(k)}
    return mine


def _column_report(column: OutputColumn) -> dict[str, Any]:
    spec = column.spec
    declared = spec.type if spec is not None else None
    tap_type = column.tap_schema.get("type") if column.tap_schema else None
    report: dict[str, Any] = {
        "source": list(column.sources) or None,
        "name": column.name,
        "type": declared,
        "tap_type": tap_type,
        "declared": spec is not None,
    }
    if spec is not None:
        if spec.expr is not None:
            report["expr"] = spec.expr
        if spec.transform is not None:
            report["transform"] = thaw(dump(spec.transform))
    if column.notes:
        report["notes"] = list(column.notes)
    return report
