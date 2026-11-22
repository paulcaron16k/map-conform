"""Compile a stream's plan at SCHEMA time (detailed design §9).

A :class:`StreamPlan` holds everything the executors need, already validated: the output
stream name, ordered :class:`ColumnPlan` objects (output name, CType, sources, compiled
chain, nullability, on_error, default, enum), the order in which columns are computed (a
column whose expressions read other columns comes after them), the compiled ``filter``, the
renamed key and bookmark properties, and the output JSON Schema and Arrow schema. Problems are
collected, each with its spec path, and raised together as a
:class:`~map_conform.spec.errors.SpecError`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

import pyarrow as pa

from map_conform.errors import OnError
from map_conform.expr.compiler import ExprError, Expression, Names, compile_expr
from map_conform.naming.conform import NameConformer, NamingError
from map_conform.naming.flatten import Flattener, FlattenError
from map_conform.naming.nested import MemberNames, conform_ctype
from map_conform.naming.shape import Shape
from map_conform.naming.streams import stream_name
from map_conform.plan.chain import ChainCompiler
from map_conform.plan.ops import CompiledChain, StepError
from map_conform.spec._struct import Issues, child, freeze, freeze_mapping, thaw, thaw_mapping
from map_conform.spec.check import Finding, OutputColumn, output_columns
from map_conform.spec.errors import SpecError
from map_conform.spec.load import ResolvedStream
from map_conform.spec.model import ColumnSpec
from map_conform.spec.stream_maps import sdk_type
from map_conform.transforms.fake import FakeData
from map_conform.transforms.registry import Context
from map_conform.types.canonical import CType, CTypeError, parse_ctype
from map_conform.types.from_jsonschema import from_jsonschema
from map_conform.types.to_arrow import to_arrow
from map_conform.types.to_jsonschema import to_jsonschema
from map_conform.types.wire import to_wire

if TYPE_CHECKING:
    from map_conform.spec.model import Spec
    from map_conform.transforms.registry import Registry

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

    @property
    def reads(self) -> frozenset[str]:
        """Columns the chain's expressions read, by output name."""
        return self.chain.reads


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
    order: tuple[int, ...] = field(default=())
    """Indexes into ``columns`` in the order they are computed: dependencies first."""
    filter: Expression | None = None
    """Rows where this is falsy are dropped; it sees every column by output name."""
    fake: FakeData | None = None
    """The stream's fake-data generator (created on first use)."""
    flattener: Flattener | None = None
    """For ``nested: flatten``: flattens each record as the SCHEMA was."""
    flat_properties: Mapping[str, Any] = field(default_factory=dict)
    """The flattened tap SCHEMA properties the records are flattened against."""
    shaped: tuple[ShapedFlattening, ...] = ()
    """Columns flattened from their declared shapes."""


def compile_stream(  # noqa: PLR0913 -- the SCHEMA message's parts, plus the spec context
    spec: Spec,
    resolved: ResolvedStream,
    tap_schema: Mapping[str, Any],
    registry: Registry,
    *,
    key_properties: tuple[str, ...] = (),
    bookmark_properties: tuple[str, ...] = (),
    strict: bool = False,
    config: Mapping[str, Any] | None = None,
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
    try:
        named = stream_name(resolved)
    except NamingError as exc:
        issues.add(path, exc.reason)
        named = None
    notes.extend(f"stream name: {n}" for n in (named.notes if named else ()))
    properties: Mapping[str, Any] = tap_schema.get("properties") or {}
    resolved, properties, shaped = _flatten_shapes(resolved, properties, issues, path)
    flattener = _flattener(resolved) if resolved.settings.nested == "flatten" else None
    if flattener is not None:
        try:
            properties = flattener.properties(properties)
        except FlattenError as exc:
            issues.add(child(path, "nested"), str(exc))
    findings: list[Finding] = []
    columns = output_columns(resolved, properties, findings, path, key_properties)
    for finding in findings:
        if finding.severity == "error":
            issues.add(finding.path, finding.message)
    fake = FakeData.from_settings(resolved.settings.faker)
    scope = Names(
        columns=frozenset(c.name for c in columns),
        constants={
            "config": freeze_mapping(dict(config or {})),
            "stream": named.name if named else resolved.tap_stream,
            "source_stream": resolved.tap_stream,
            "fake": fake,
        },
    )
    compiler = ChainCompiler(
        registry, resolved.settings, spec.macros, issues, scope, resolved.tap_stream
    )
    builder = _ColumnBuilder(resolved, properties, compiler, issues, notes, path)
    plans = [plan for column in columns if (plan := builder.build(column)) is not None]
    order = _order(plans, issues, path)
    row_filter = _filter(resolved.spec.filter, scope, issues, path)
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
        order=order,
        filter=row_filter,
        fake=fake,
        flattener=flattener,
        flat_properties=dict(properties) if flattener is not None else {},
        shaped=tuple(shaped),
    )


@dataclass(frozen=True)
class ShapedFlattening:
    """A column flattened from its declared shape: the executor conforms and flattens it."""

    key: str
    """The spec's column key, for counts and logs."""
    source: str
    shape: Shape
    flattener: Flattener
    leaves: Mapping[str, Any]


def _flatten_shapes(
    resolved: ResolvedStream, properties: Mapping[str, Any], issues: Issues, path: str
) -> tuple[ResolvedStream, Mapping[str, Any], list[ShapedFlattening]]:
    """Replace each flattened shaped column by its leaf columns, typed from the shape."""
    settings = resolved.settings
    columns: dict[str, ColumnSpec] = {}
    props = dict(properties)
    shaped: list[ShapedFlattening] = []
    declared = resolved.spec.columns
    for key, spec in declared.items():
        flatten = spec.flatten if spec.flatten is not None else settings.nested == "flatten"
        if spec.shape is None or not flatten or spec.drop:
            columns.setdefault(key, spec)
            continue
        col_path = child(child(path, "columns"), key)
        if spec.source is not None and not isinstance(spec.source, str):
            issues.add(child(col_path, "source"), "a flattened shape reads one source")
            continue
        source = spec.source or key
        options = settings.flatten
        flattener = Flattener(options.separator, options.max_depth, options.max_key_length,
                              frozenset(), typed_leaves=True)  # fmt: skip
        schema = thaw_mapping(spec.shape)
        try:
            leaves = flattener.properties({source: schema})
        except FlattenError as exc:
            issues.add(child(col_path, "shape"), str(exc))
            continue
        for leaf, leaf_schema in leaves.items():
            columns[leaf] = _leaf_spec(declared.get(leaf), leaf_schema)
        props = _replace(props, source, leaves)
        shaped.append(ShapedFlattening(key, source, Shape.of(schema), flattener, leaves))
    if not shaped:
        return resolved, properties, []
    stream = dataclasses.replace(resolved.spec, columns=MappingProxyType(columns))
    return dataclasses.replace(resolved, spec=stream), props, shaped


def _leaf_spec(own: ColumnSpec | None, schema: Mapping[str, Any]) -> ColumnSpec:
    """A leaf column: the type and default from the shape, the rest from a spec of its own."""
    inferred = from_jsonschema(schema, "keep")
    base = own or ColumnSpec()
    changes: dict[str, Any] = {}
    if base.type is None:  # nullable stays: a member may be missing from any record
        changes["type"] = str(inferred.ctype)
    if base.default is None and "default" in schema:
        changes["default"] = freeze(schema["default"])
    return dataclasses.replace(base, **changes)


def _replace(properties: dict[str, Any], name: str, leaves: Mapping[str, Any]) -> dict[str, Any]:
    """Properties with ``name`` replaced, in place, by the leaf properties."""
    out: dict[str, Any] = {}
    for key, value in properties.items():
        if key == name:
            out.update(leaves)
        elif key not in leaves:
            out[key] = value
    for key, value in leaves.items():
        out.setdefault(key, value)
    return out


def _flattener(resolved: ResolvedStream) -> Flattener:
    """SDK flattening for the properties the spec does not name itself."""
    named = set(resolved.spec.columns)
    for spec in resolved.spec.columns.values():
        if isinstance(spec.source, str):
            named.add(spec.source)
        elif spec.source is not None:
            named.update(spec.source)
    options = resolved.settings.flatten
    return Flattener(options.separator, options.max_depth, options.max_key_length, frozenset(named))


def _filter(text: str | None, scope: Names, issues: Issues, path: str) -> Expression | None:
    if text is None:
        return None
    try:
        return compile_expr(text, dataclasses.replace(scope, value=False))
    except ExprError as exc:
        issues.add(child(path, "filter"), str(exc))
        return None


def _order(plans: list[ColumnPlan], issues: Issues, path: str) -> tuple[int, ...]:
    """Column indexes with every column after the columns it reads; cycles are errors."""
    index = {plan.name: i for i, plan in enumerate(plans)}
    done: list[int] = []
    state: dict[int, str] = {}

    def visit(i: int, trail: tuple[int, ...]) -> bool:
        if state.get(i) == "done":
            return True
        if state.get(i) == "visiting":
            cycle = [plans[j].name for j in trail[trail.index(i) :]] + [plans[i].name]
            issues.add(
                child(child(path, "columns"), plans[i].key),
                f"dependency cycle: {' -> '.join(cycle)}",
            )
            return False
        state[i] = "visiting"
        deps = sorted(index[name] for name in plans[i].reads if name in index)
        ok = all(visit(j, (*trail, i)) for j in deps)
        state[i] = "done"
        if ok:
            done.append(i)
        return ok

    for i in range(len(plans)):
        if not visit(i, ()):
            return tuple(range(len(plans)))
    return tuple(done)


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
        ctype, tap_nullable = self._ctype(column, col_path, notes)
        if ctype is None or len(self.issues.items) != before:
            return None
        naming = NameConformer(self.resolved.settings.naming)
        try:
            ctype, member_names = conform_ctype(ctype, naming)
        except NamingError as exc:
            self.issues.add(col_path, f"nested member: {exc}")
            return None
        chain = self.compiler.compile_column(spec, ctype, col_path, own=column.name)
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
        if spec is not None and spec.infer_type == "sdk" and spec.expr is not None:
            return self._sdk_type(column, spec.expr, notes)
        if spec is not None and spec.shape is not None:  # the declared shape, never the tap's
            return from_jsonschema(thaw_mapping(spec.shape), "keep").ctype, True
        if column.tap_schema is None:
            self.issues.add(
                col_path, "declare its type: the tap SCHEMA has no single source property for it"
            )
            return None, True
        nested = self.resolved.settings.nested
        inferred = from_jsonschema(column.tap_schema, _shape(nested))
        notes.extend(f"column {column.key!r}: {w}" for w in inferred.warnings)
        return inferred.ctype, inferred.nullable

    def _sdk_type(
        self, column: OutputColumn, expr: str, notes: list[str]
    ) -> tuple[CType | None, bool]:
        """The SDK mapper's prefix inference (WBS 12.2), with a note suggesting a type."""
        dropped = self.resolved.settings.undeclared == "drop"
        ctype, schema = sdk_type(expr, column.key, self.properties, undeclared_dropped=dropped)
        nullable = True
        if ctype is None and schema is not None:
            nested = self.resolved.settings.nested
            inferred = from_jsonschema(schema, _shape(nested))
            ctype, nullable = inferred.ctype, inferred.nullable
        notes.append(
            f"column {column.key!r}: type {ctype} inferred from its expression as the SDK "
            "does; declare type to make it explicit"
        )
        return ctype, nullable

    def _nullable(
        self, spec: ColumnSpec | None, chain: CompiledChain, *, tap_nullable: bool, col_path: str
    ) -> bool:
        forced = chain.forces_nullable
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


def _shape(nested: str) -> Literal["keep", "json"]:
    """How an object property is typed.

    Flattening has already turned objects below its depth into JSON text, so the objects left
    (at depth 0) keep their shape, as in the SDK.
    """
    return "json" if nested == "json" else "keep"


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
                **({"reads": sorted(c.reads)} if c.reads else {}),
            }
            for c in plan.columns
        ],
        **({"filter": plan.filter.text} if plan.filter is not None else {}),
        "notes": list(plan.notes),
    }
