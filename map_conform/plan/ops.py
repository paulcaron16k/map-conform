"""The run-time form of a compiled chain (detailed design §3.4, §10.1).

A :class:`CompiledChain` is a tuple of ops. Each op has a ``rule`` (how errors name it), says
whether it must see nulls, whether it can produce a null whatever its input, and which
columns it reads; ``apply`` runs it on one value.

- :class:`CompiledStep`: a builtin or a cast, with its kwargs already validated;
- :class:`ExprOp`: an ``expr`` step;
- :class:`GuardedOp`: steps that run only where a ``when`` is truthy;
- :class:`CaseOp`: the first branch whose ``when`` is truthy, else the ``else`` chain;
- :class:`FieldsOp`: chains applied to nested members of a struct or json value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from map_conform.errors import CellError, StepFailed
from map_conform.expr.compiler import Expression, Row
from map_conform.transforms.registry import Transform
from map_conform.types.canonical import CType

if TYPE_CHECKING:
    from map_conform.transforms.registry import Context

_EMPTY_ROW = Row.of({})


@dataclass(frozen=True)
class CastArgs:
    """A cast step's arguments: its target type and its validated options."""

    target: CType
    options: Any


class StepError(Exception):
    """A step failed on a value; ``cell`` says which and why."""

    def __init__(self, cell: CellError) -> None:
        """Keep the failure."""
        self.cell = cell
        super().__init__(f"{cell.rule}: {cell.reason}")


@dataclass(frozen=True)
class CompiledStep:
    """One resolved builtin or cast, with validated kwargs."""

    transform: Transform
    kwargs: Any
    rule: str
    """How errors name the step, e.g. ``strip_chars`` or ``cast: decimal(10,2)``."""

    @property
    def null_safe(self) -> bool:
        """Whether the step must see nulls."""
        return self.transform.null_safe

    @property
    def forces_nullable(self) -> bool:
        """Whether the step can produce null whatever its input (set_null)."""
        return self.transform.forces_nullable

    @property
    def reads(self) -> frozenset[str]:
        """Builtins read no other column."""
        return frozenset()

    def apply(self, value: object, ctx: Context, _row: Row) -> object:
        """Run the builtin."""
        return self.transform.scalar(value, self.kwargs, ctx)


@dataclass(frozen=True)
class ExprOp:
    """An ``expr`` step: its result replaces the value."""

    expression: Expression
    null_safe = True
    forces_nullable = False

    @property
    def rule(self) -> str:
        """``expr: <text>``."""
        return f"expr: {self.expression.text}"

    @property
    def reads(self) -> frozenset[str]:
        """The columns the expression reads."""
        return self.expression.reads

    def apply(self, value: object, _ctx: Context, row: Row) -> object:
        """Evaluate the expression with the value as ``value``."""
        return self.expression.evaluate(row, value)


def _truthy(when: Expression, row: Row, value: object) -> bool:
    try:
        return bool(when.evaluate(row, value))
    except StepFailed as exc:
        raise StepFailed(f"when {when.text!r}: {exc.reason}") from None


Op = Any
"""CompiledStep | ExprOp | GuardedOp | CaseOp | FieldsOp."""


def _run(ops: tuple[Op, ...], value: object, ctx: Context, row: Row) -> object:
    for op in ops:
        if value is None and not op.null_safe:
            continue
        try:
            value = op.apply(value, ctx, row)
        except StepFailed as exc:
            raise StepError(CellError(op.rule, exc.reason)) from exc
    return value


@dataclass(frozen=True)
class GuardedOp:
    """Steps that run only where ``when`` is truthy; elsewhere the value passes unchanged."""

    when: Expression
    ops: tuple[Op, ...]
    null_safe = True

    @property
    def rule(self) -> str:
        """The guarded steps and their condition."""
        return f"{', '.join(op.rule for op in self.ops)} (when {self.when.text})"

    @property
    def forces_nullable(self) -> bool:
        """When a guarded step can produce null."""
        return any(op.forces_nullable for op in self.ops)

    @property
    def reads(self) -> frozenset[str]:
        """The condition's columns and the steps'."""
        return self.when.reads.union(*(op.reads for op in self.ops))

    def apply(self, value: object, ctx: Context, row: Row) -> object:
        """Run the steps where the condition holds."""
        if not _truthy(self.when, row, value):
            return value
        return _run(self.ops, value, ctx, row)


@dataclass(frozen=True)
class CompiledChain:
    """A column's ops, ending as its declared type."""

    steps: tuple[Op, ...]
    target: CType

    @property
    def reads(self) -> frozenset[str]:
        """Every column the chain's expressions read: its dependencies."""
        return frozenset().union(*(op.reads for op in self.steps))

    @property
    def forces_nullable(self) -> bool:
        """Whether a step can produce null whatever the input."""
        return any(op.forces_nullable for op in self.steps)

    def run(self, value: object, ctx: Context, row: Row | None = None) -> object:
        """Apply the ops to one value. Nulls skip ops that are not null-safe.

        Raises:
            StepError: naming the failed step and the reason.
        """
        return _run(self.steps, value, ctx, row or _EMPTY_ROW)


@dataclass(frozen=True)
class CaseOp:
    """The first branch whose condition holds runs; otherwise the else chain, if any."""

    branches: tuple[tuple[Expression, CompiledChain], ...]
    otherwise: CompiledChain | None
    label: str = "case"
    null_safe = True

    @property
    def rule(self) -> str:
        """``case: when <a> -> [steps]; else -> [steps]``."""
        parts = [
            f"when {when.text} -> [{', '.join(op.rule for op in chain.steps)}]"
            for when, chain in self.branches
        ]
        if self.otherwise is not None:
            parts.append(f"else -> [{', '.join(op.rule for op in self.otherwise.steps)}]")
        return f"{self.label}: {'; '.join(parts)}"

    @property
    def forces_nullable(self) -> bool:
        """When any branch can produce null."""
        chains = [chain for _, chain in self.branches]
        if self.otherwise is not None:
            chains.append(self.otherwise)
        return any(chain.forces_nullable for chain in chains)

    @property
    def reads(self) -> frozenset[str]:
        """The conditions' columns and the branches'."""
        out: set[str] = set()
        for when, chain in self.branches:
            out |= when.reads | chain.reads
        if self.otherwise is not None:
            out |= self.otherwise.reads
        return frozenset(out)

    def apply(self, value: object, ctx: Context, row: Row) -> object:
        """Run the first matching branch."""
        for when, chain in self.branches:
            if _truthy(when, row, value):
                return chain.run(value, ctx, row)
        if self.otherwise is None:
            return value
        return self.otherwise.run(value, ctx, row)


# --- nested fields --------------------------------------------------------------------------

_SEGMENT = re.compile(r"\[\*\]|[^.\[\]]+")
DROP = object()
"""Returned by a field op to remove the member."""


def path_segments(path: str) -> tuple[str, ...] | None:
    """``address.zip`` -> (address, zip); ``items[*].sku`` -> (items, [*], sku); None if bad."""
    segments = tuple(_SEGMENT.findall(path))
    rebuilt = "".join(s if s == "[*]" else f".{s}" for s in segments).lstrip(".")
    return segments if segments and rebuilt == path else None


@dataclass(frozen=True)
class FieldOp:
    """A chain, a condition, or a drop, for the members at one path."""

    path: str
    segments: tuple[str, ...]
    chain: CompiledChain | None
    when: Expression | None
    drop: bool

    @property
    def reads(self) -> frozenset[str]:
        """The condition's and the chain's columns."""
        out = self.when.reads if self.when is not None else frozenset()
        return out | (self.chain.reads if self.chain is not None else frozenset())

    def member(self, value: object, ctx: Context, row: Row) -> object:
        """The new member value, or DROP."""
        if self.when is not None and not _truthy(self.when, row, value):
            return value
        if self.drop:
            return DROP
        if self.chain is None:
            return value
        try:
            return self.chain.run(value, ctx, row)
        except StepError as exc:
            raise StepFailed(f"{self.path}: {exc.cell.rule}: {exc.cell.reason}") from None


def _update(container: object, segments: tuple[str, ...], fn: FieldOp, *args: Any) -> object:
    """A copy of the container with fn applied at the path; missing members are left alone."""
    head, rest = segments[0], segments[1:]
    if head == "[*]":
        if not isinstance(container, list):
            return container
        items = [_update_item(item, rest, fn, *args) for item in container]
        return [item for item in items if item is not DROP]
    if not isinstance(container, dict) or head not in container:
        return container
    copy = dict(container)
    new = _update_item(copy[head], rest, fn, *args)
    if new is DROP:
        del copy[head]
    else:
        copy[head] = new
    return copy


def _update_item(item: object, rest: tuple[str, ...], fn: FieldOp, *args: Any) -> object:
    return fn.member(item, *args) if not rest else _update(item, rest, fn, *args)


@dataclass(frozen=True)
class FieldsOp:
    """Transforms on nested members, after the cast (pipelinewise ``field_paths``)."""

    fields: tuple[FieldOp, ...]
    null_safe = False
    forces_nullable = False

    @property
    def rule(self) -> str:
        """``fields: a.b, c[*].d``."""
        return f"fields: {', '.join(f.path for f in self.fields)}"

    @property
    def reads(self) -> frozenset[str]:
        """Every field's columns."""
        return frozenset().union(*(f.reads for f in self.fields))

    def apply(self, value: object, ctx: Context, row: Row) -> object:
        """Apply each field op in turn; containers on the path are copied, never changed."""
        for op in self.fields:
            value = _update(value, op.segments, op, ctx, row)
        return value
