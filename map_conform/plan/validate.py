"""Compile a spec's plans for ``spec validate``, so a typo fails validation, not the run.

The strict parser checks a spec's structure; step options, ``parse`` options, macro calls,
expressions and type flow are checked only when a plan compiles. ``spec validate`` compiles
every plan it can:

- with a catalog, each catalog stream's output streams against its schema, exactly as the
  mapper will;
- without one, each stream rule against the tap columns it implies: those it declares, and
  any name its expressions read or its ``key_properties`` list. Steps start from the raw
  value either way, so only a column's *type* depends on the tap: a column without
  ``type`` (or ``shape``) is assumed to be a string, and its problems are warnings that
  ``--catalog`` confirms or clears.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Any

from map_conform.expr.compiler import parse_expression
from map_conform.plan.compile import compile_stream
from map_conform.spec._struct import child
from map_conform.spec.check import Finding, column_sources, output_columns
from map_conform.spec.errors import SpecError
from map_conform.spec.load import output_streams
from map_conform.spec.steps import CaseStep, ExprStep

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from map_conform.spec.check import CatalogStream
    from map_conform.spec.load import ResolvedStream
    from map_conform.spec.model import ColumnSpec, Spec
    from map_conform.spec.steps import Chain
    from map_conform.transforms.registry import Registry

_UNTYPED = " (the column has no declared type, so a string was assumed; check with --catalog)"


def check_plans(
    spec: Spec,
    catalog: list[CatalogStream] | None,
    registry: Registry,
    config: Mapping[str, Any] | None = None,
) -> list[Finding]:
    """Every problem found by compiling the spec's plans, each once, in order."""
    findings = (
        _against_catalog(spec, catalog, registry, config)
        if catalog is not None
        else _against_rules(spec, registry, config)
    )
    return list(dict.fromkeys(findings))


def _against_catalog(
    spec: Spec, catalog: list[CatalogStream], registry: Registry, config: Mapping[str, Any] | None
) -> Iterable[Finding]:
    for entry in catalog:
        schema = {"type": "object", "properties": dict(entry.properties)}
        for resolved in output_streams(spec, entry.name):
            for path, message in _compile(spec, resolved, schema, registry, config=config,
                                          key_properties=entry.key_properties):  # fmt: skip
                yield Finding("error", path, message)


def _against_rules(
    spec: Spec, registry: Registry, config: Mapping[str, Any] | None
) -> Iterable[Finding]:
    for key, rules in spec.streams.items():
        tap = rules.spec.source or key
        for resolved in output_streams(spec, tap):
            own = resolved.key is None and key in resolved.matched
            if not (own if rules.spec.source is None else resolved.key == key):
                continue
            stream_path = child("streams", key)
            schema = {"type": "object", "properties": _assumed_properties(resolved, stream_path)}
            untyped = {
                child(child(stream_path, "columns"), name)
                for name, column in resolved.spec.columns.items()
                if column.type is None and column.shape is None and _reads_tap(column)
            }
            for path, message in _compile(spec, resolved, schema, registry, config=config):
                if any(path == p or path.startswith((f"{p}.", f"{p}[")) for p in untyped):
                    yield Finding("warning", path, message + _UNTYPED)
                else:
                    yield Finding("error", path, message)


def _reads_tap(column: ColumnSpec) -> bool:
    """Whether a column's value comes from the tap (a derived one has only its ``expr``)."""
    return column.expr is None or column.source is not None


def _assumed_properties(resolved: ResolvedStream, path: str) -> dict[str, Any]:
    """The tap columns a rule implies: those it declares, and those it refers to.

    A name an expression reads, or a key property, that no declared column provides is
    taken to be a tap column, as it would be with ``undeclared: conform``.
    """
    columns = resolved.spec.columns
    properties: dict[str, Any] = {}
    for name, column in columns.items():
        if not _reads_tap(column):
            continue
        kind = "object" if column.shape is not None else "string"
        for source in column_sources(name, column):
            properties[source] = {"type": [kind, "null"]}
    known = set(properties) | set(columns)
    known |= {c.name for c in output_columns(resolved, properties, [], path)}
    referred = _expression_names(resolved) | set(resolved.spec.key_properties or ())
    for name in sorted(referred - known):
        properties[name] = {"type": ["string", "null"]}
    return properties


def _expression_names(resolved: ResolvedStream) -> set[str]:
    """Every bare name read (not called) by the rule's expressions."""
    texts: list[str] = [t for t in (resolved.spec.filter,) if t]
    for column in resolved.spec.columns.values():
        texts.extend(t for t in (column.expr, column.when) if t)
        texts.extend(_chain_texts(column.transform))
        for member in (column.fields or {}).values():
            texts.extend(t for t in (member.when,) if t)
            texts.extend(_chain_texts(member.transform))
    names: set[str] = set()
    for text in texts:
        try:
            tree = parse_expression(text)
        except SyntaxError:
            continue  # reported when the expression compiles
        called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        names.update(
            n.id
            for n in ast.walk(tree)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and id(n) not in called
        )
    return names


def _chain_texts(chain: Chain | None) -> list[str]:
    """The expression texts in a chain's steps, ``case`` branches included."""
    texts: list[str] = []
    for step in chain.steps if chain is not None else ():
        if step.when:
            texts.append(step.when)
        if isinstance(step, ExprStep):
            texts.append(step.expr)
        elif isinstance(step, CaseStep):
            for branch in step.branches:
                texts.append(branch.when)
                texts.extend(_chain_texts(branch.then))
            texts.extend(_chain_texts(step.otherwise))
    return texts


def _compile(  # noqa: PLR0913 -- the stream and what compiling it needs
    spec: Spec,
    resolved: ResolvedStream,
    schema: Mapping[str, Any],
    registry: Registry,
    *,
    config: Mapping[str, Any] | None,
    key_properties: tuple[str, ...] = (),
) -> list[tuple[str, str]]:
    try:
        compile_stream(spec, resolved, schema, registry, key_properties=key_properties,
                       config=config)  # fmt: skip
    except SpecError as exc:
        return [(issue.path, issue.message) for issue in exc.issues]
    return []
