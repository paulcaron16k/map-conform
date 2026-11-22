"""Compile a stream's plan at SCHEMA time (detailed design §9).

A :class:`StreamPlan` holds everything the executors need, already validated: the output
stream name, ordered :class:`ColumnPlan` objects (output name, CType, sources, compiled
chain, nullability, on_error, default, enum), the renamed key and bookmark properties, and
the output JSON Schema and Arrow schema. Problems are collected, each with its spec path, and
raised together as a :class:`~map_conform.spec.errors.SpecError`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pyarrow as pa

from map_conform.errors import OnError
from map_conform.naming.conform import NameConformer, NamingError
from map_conform.naming.nested import MemberNames, conform_ctype
from map_conform.naming.streams import stream_name
from map_conform.plan.chain import ChainCompiler, CompiledChain, StepError
from map_conform.spec._struct import Issues, child, thaw
from map_conform.spec.check import Finding, OutputColumn, output_columns
from map_conform.spec.errors import SpecError
from map_conform.spec.load import ResolvedStream
from map_conform.transforms.registry import Context
from map_conform.types.canonical import CType, CTypeError, parse_ctype
from map_conform.types.from_jsonschema import from_jsonschema
from map_conform.types.to_arrow import to_arrow
from map_conform.types.to_jsonschema import to_jsonschema
from map_conform.types.wire import to_wire

if TYPE_CHECKING:
    from map_conform.spec.model import ColumnSpec, Spec
    from map_conform.transforms.registry import Registry

_NEEDS_EXPR = "needs the expression language, which is not built yet (WBS 6.x)"
_KEEP_KINDS = frozenset({"string", "json"})


@dataclass(frozen=True)
class ColumnPlan:
    """How one output column is produced."""

    name: str
    ctype: CType
    sources: tuple[str, ...]
    """Source properties; the first non-null one is used."""
    chain: CompiledChain
    nullable: bool
    on_error: OnError
    default: Any = None
    """The typed default for a missing or null result."""
    enum: frozenset[Any] | None = None
    """Allowed wire values, when the column restricts them."""
    member_names: MemberNames | None = None
    """Renames nested struct members in values."""
    declared: bool = True
    key: str = ""
    """The spec's ``columns`` key, or the source name of an undeclared column."""
    doc: str | None = None
    sql_type: str | None = None

    @property
    def steps(self) -> tuple[str, ...]:
        """The chain's step rules, for explain output."""
        return tuple(step.rule for step in self.chain.steps)


@dataclass(frozen=True)
class StreamPlan:
    """A compiled stream: output name, columns and schemas."""

    tap_stream: str
    name: str
    columns: tuple[ColumnPlan, ...]
    key_properties: tuple[str, ...]
    bookmark_properties: tuple[str, ...]
    schema: dict[str, Any]
    arrow_schema: pa.Schema
    notes: tuple[str, ...] = field(default=())
    """Lossy renames and type warnings, logged once per stream."""


def compile_stream(  # noqa: PLR0913 -- the SCHEMA message's parts, plus the spec context
    spec: Spec,
    resolved: ResolvedStream,
    tap_schema: Mapping[str, Any],
    registry: Registry,
    *,
    key_properties: tuple[str, ...] = (),
    bookmark_properties: tuple[str, ...] = (),
    strict: bool = False,
) -> StreamPlan:
    """Compile the plan for one output stream from its tap SCHEMA.

    Raises:
        SpecError: listing every problem, each with its spec path.
    """
    if strict and resolved.settings.undeclared != "error":
        settings = dataclasses.replace(resolved.settings, undeclared="error")
        resolved = dataclasses.replace(resolved, settings=settings)
    path = child("streams", resolved.key or resolved.tap_stream)
    issues = Issues()
    notes: list[str] = []
    if resolved.spec.filter is not None:
        issues.add(child(path, "filter"), f"filter {_NEEDS_EXPR}")
    try:
        named = stream_name(resolved)
    except NamingError as exc:
        issues.add(path, exc.reason)
        named = None
    notes.extend(f"stream name: {n}" for n in (named.notes if named else ()))
    properties: Mapping[str, Any] = tap_schema.get("properties") or {}
    findings: list[Finding] = []
    columns = output_columns(resolved, properties, findings, path)
    for finding in findings:
        if finding.severity == "error":
            issues.add(finding.path, finding.message)
    compiler = ChainCompiler(registry, resolved.settings, spec.macros, issues)
    builder = _ColumnBuilder(resolved, properties, compiler, issues, notes, path)
    plans = [plan for column in columns if (plan := builder.build(column)) is not None]
    renamed = _renamer(columns)
    keys = _keys(resolved, key_properties, renamed, issues, path)
    bookmarks = tuple(renamed.get(b, b) for b in bookmark_properties)
    if issues or named is None:
        raise SpecError(issues.items, f"the plan for stream {resolved.tap_stream!r}")
    return StreamPlan(
        tap_stream=resolved.tap_stream,
        name=named.name,
        columns=tuple(plans),
        key_properties=keys,
        bookmark_properties=bookmarks,
        schema=_output_schema(plans),
        arrow_schema=pa.schema(
            [pa.field(p.name, to_arrow(p.ctype), nullable=p.nullable) for p in plans]
        ),
        notes=tuple(notes),
    )


@dataclass
class _ColumnBuilder:
    resolved: ResolvedStream
    properties: Mapping[str, Any]
    compiler: ChainCompiler
    issues: Issues
    notes: list[str]
    path: str

    def build(self, column: OutputColumn) -> ColumnPlan | None:
        spec = column.spec
        col_path = child(child(self.path, "columns"), column.key)
        before = len(self.issues.items)
        notes = [f"column {column.key!r} -> {column.name!r}: {n}" for n in column.notes]
        self._refuse_unbuilt(spec, col_path)
        ctype, tap_nullable = self._ctype(column, col_path, notes)
        if ctype is None or len(self.issues.items) != before:
            return None
        naming = NameConformer(self.resolved.settings.naming)
        try:
            ctype, member_names = conform_ctype(ctype, naming)
        except NamingError as exc:
            self.issues.add(col_path, f"nested member: {exc}")
            return None
        chain = self.compiler.compile(spec.transform if spec else None, spec, ctype, col_path)
        if chain is None:
            return None
        nullable = self._nullable(spec, chain, tap_nullable=tap_nullable, col_path=col_path)
        on_error = self._on_error(spec, ctype, col_path)
        default = self._typed(spec.default, chain, col_path, "default") if spec else None
        enum = self._enum(spec, chain, col_path)
        if len(self.issues.items) != before:
            return None
        self.notes.extend(notes)
        return ColumnPlan(
            name=column.name,
            ctype=ctype,
            sources=column.sources,
            chain=chain,
            nullable=nullable,
            on_error=on_error,
            default=default,
            enum=enum,
            member_names=member_names,
            declared=spec is not None,
            key=column.key,
            doc=spec.doc if spec else None,
            sql_type=spec.sql_type if spec else None,
        )

    def _refuse_unbuilt(self, spec: ColumnSpec | None, col_path: str) -> None:
        if spec is None:
            return
        if spec.expr is not None:
            self.issues.add(child(col_path, "expr"), f"expr {_NEEDS_EXPR}")
        if spec.when is not None:
            self.issues.add(child(col_path, "when"), f"when {_NEEDS_EXPR}")
        if spec.fields is not None:
            self.issues.add(
                child(col_path, "fields"),
                "nested field transforms are not built yet (WBS 12.x)",
            )

    def _ctype(
        self, column: OutputColumn, col_path: str, notes: list[str]
    ) -> tuple[CType | None, bool]:
        spec = column.spec
        if spec is not None and spec.type is not None:
            try:
                return parse_ctype(spec.type), True
            except CTypeError as exc:  # already reported by the spec parser; be safe
                self.issues.add(child(col_path, "type"), str(exc))
                return None, True
        if column.tap_schema is None:
            self.issues.add(
                col_path, "declare its type: the tap SCHEMA has no single source property for it"
            )
            return None, True
        nested = self.resolved.settings.nested
        inferred = from_jsonschema(column.tap_schema, "keep" if nested == "keep" else "json")
        notes.extend(f"column {column.key!r}: {w}" for w in inferred.warnings)
        return inferred.ctype, inferred.nullable

    def _nullable(
        self, spec: ColumnSpec | None, chain: CompiledChain, *, tap_nullable: bool, col_path: str
    ) -> bool:
        forced = any(step.transform.forces_nullable for step in chain.steps)
        if spec is None:
            return tap_nullable or forced
        if forced and not spec.nullable:
            self.issues.add(child(col_path, "nullable"), "set_null makes the column nullable")
        return spec.nullable or forced

    def _on_error(self, spec: ColumnSpec | None, ctype: CType, col_path: str) -> OnError:
        policy = spec.on_error if spec and spec.on_error else self.resolved.settings.on_error
        if policy == "keep" and ctype.kind not in _KEEP_KINDS:
            self.issues.add(
                child(col_path, "on_error"),
                f"keep would put raw text in a {ctype} column; use it only for string or json",
            )
        return policy

    def _typed(self, value: object, chain: CompiledChain, col_path: str, what: str) -> object:
        if value is None:
            return None
        ctx = Context(self.resolved.tap_stream, col_path, self.resolved.settings, chain.target)
        try:
            return chain.run(thaw(value), ctx)
        except StepError as exc:
            self.issues.add(
                child(col_path, what),
                f"{value!r} does not pass the column's chain: {exc.cell.rule}: {exc.cell.reason}",
            )
            return None

    def _enum(
        self, spec: ColumnSpec | None, chain: CompiledChain, col_path: str
    ) -> frozenset[Any] | None:
        if spec is None or spec.enum is None:
            return None
        allowed = {
            to_wire(self._typed(v, chain, col_path, "enum"), chain.target) for v in spec.enum
        }
        return frozenset(_hashable(v) for v in allowed)


def _hashable(value: object) -> object:
    return value if isinstance(value, (str, int, float, bool, type(None))) else repr(value)


def _renamer(columns: list[OutputColumn]) -> dict[str, str]:
    """Source property (and output name) -> output name."""
    out: dict[str, str] = {}
    for column in columns:
        out[column.name] = column.name
        for source in column.sources:
            out.setdefault(source, column.name)
    return out


def _keys(
    resolved: ResolvedStream,
    tap_keys: tuple[str, ...],
    renamed: Mapping[str, str],
    issues: Issues,
    path: str,
) -> tuple[str, ...]:
    keys = resolved.spec.key_properties if resolved.spec.key_properties is not None else tap_keys
    out: list[str] = []
    for key in keys:
        if key in renamed:
            out.append(renamed[key])
        else:
            issues.add(child(path, "key_properties"), f"key property {key!r} is not in the output")
    return tuple(out)


def _output_schema(plans: list[ColumnPlan]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for plan in plans:
        prop = to_jsonschema(plan.ctype, nullable=plan.nullable)
        if plan.doc:
            prop["description"] = plan.doc
        if plan.sql_type:
            prop["x-sql-datatype"] = plan.sql_type
        properties[plan.name] = prop
    return {"type": "object", "properties": properties}


def plan_report(plan: StreamPlan) -> dict[str, Any]:
    """A plain-data account of a compiled plan, for ``spec explain``."""
    return {
        "name": plan.name,
        "key_properties": list(plan.key_properties),
        "bookmark_properties": list(plan.bookmark_properties),
        "columns": [
            {
                "name": c.name,
                "sources": list(c.sources),
                "type": str(c.ctype),
                "nullable": c.nullable,
                "on_error": c.on_error,
                "steps": list(c.steps),
                **({"default": to_wire(c.default, c.ctype)} if c.default is not None else {}),
                **({"enum": sorted(map(str, c.enum))} if c.enum is not None else {}),
            }
            for c in plan.columns
        ],
        "notes": list(plan.notes),
    }
