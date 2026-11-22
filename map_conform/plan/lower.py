"""Lower ``case`` steps to ``pyarrow.compute.case_when`` (detailed design §7, WBS 8.6).

A ``case`` is vectorised when every branch chain is, and every ``when`` lowers to an Arrow
mask. The whens are evaluated as masks over the whole column, each branch runs on the
whole column, and the first branch whose mask holds supplies the value, as ``case_when``
does. Like every vector op, a lowered ``when`` claims only rows where it agrees with Python:

- ``is_null(value)``; ``is_blank(value)`` (ASCII text);
- ``value == x``, ``value != x``, ``value in [...]``, ``value not in [...]`` with string or
  number literals of the column's kind; ordered comparisons (``<``, ``>=``, ...) leave null
  rows to the scalar path, where Python raises;
- ``matches(pattern, value)`` on text without line breaks, when the pattern compiles as RE2;
- ``not``, ``and``, ``or`` of those.

A when that reads another column, or uses anything else, keeps the whole case row-wise.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pyarrow.compute as _compute

from map_conform.expr.compiler import parse_expression
from map_conform.plan.ops import CaseOp, CastArgs, CompiledStep
from map_conform.transforms.vector import CASTS, TRANSFORMS, Vector, everything, unsafe_text

if TYPE_CHECKING:
    from map_conform.plan.ops import Op
    from map_conform.types.canonical import CType

# The pyarrow stubs cannot follow array-in, array-out kernels; tests/parity checks this module.
_pa: Any = pa
pc: Any = _compute

Mask = Callable[[pa.Array], tuple[pa.Array, pa.Array]]
"""``column -> (mask, todo)``; the mask is non-null."""

_NO = pa.scalar(False)  # noqa: FBT003 -- a fill value
_YES = pa.scalar(True)  # noqa: FBT003 -- a fill value

_COMPARE = {
    ast.Eq: "equal",
    ast.NotEq: "not_equal",
    ast.Lt: "less",
    ast.LtE: "less_equal",
    ast.Gt: "greater",
    ast.GtE: "greater_equal",
}


def _false(column: pa.Array) -> pa.Array:
    return _pa.repeat(_pa.scalar(value=False), len(column))


def _is_text(column: pa.Array) -> bool:
    return pa.types.is_string(column.type) or pa.types.is_large_string(column.type)


def _is_number(column: pa.Array) -> bool:
    kind = column.type
    return pa.types.is_integer(kind) or pa.types.is_floating(kind) or pa.types.is_decimal(kind)


def _literal(node: ast.expr) -> object:
    value = ast.literal_eval(node)
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise TypeError(value)
    return value


def _fits(column: pa.Array, value: object) -> bool:
    if isinstance(value, str):
        return _is_text(column)
    return _is_number(column)


def _is_value(node: ast.expr) -> bool:
    return isinstance(node, ast.Name) and node.id in {"value", "self"}


def _compare(node: ast.Compare) -> Mask | None:  # noqa: C901, PLR0911 -- one branch per form
    if len(node.ops) != 1 or not _is_value(node.left):
        return None
    op, right = node.ops[0], node.comparators[0]
    if isinstance(op, (ast.In, ast.NotIn)):
        if not isinstance(right, (ast.List, ast.Tuple, ast.Set)):
            return None
        try:
            values = [_literal(e) for e in right.elts]
        except (TypeError, ValueError):
            return None

        def member(column: pa.Array) -> tuple[pa.Array, pa.Array]:
            if not values or not all(_fits(column, v) for v in values):
                return _false(column), everything(column)
            hit = pc.fill_null(pc.is_in(column, value_set=_pa.array(values)), _NO)
            return (pc.invert(hit) if isinstance(op, ast.NotIn) else hit), _false(column)

        return member
    name = _COMPARE.get(type(op))
    if name is None:
        return None
    try:
        literal = _literal(right)
    except (TypeError, ValueError):
        return None

    def compare(column: pa.Array) -> tuple[pa.Array, pa.Array]:
        if not _fits(column, literal):
            return _false(column), everything(column)
        result = getattr(pc, name)(column, literal)
        if name == "not_equal":  # None != x is True in Python
            return pc.fill_null(result, _YES), _false(column)
        if name == "equal":
            return pc.fill_null(result, _NO), _false(column)
        return pc.fill_null(result, _NO), pc.is_null(column)  # Python raises on None

    return compare


def _call(node: ast.Call) -> Mask | None:  # noqa: C901, PLR0911 -- one branch per function
    if not isinstance(node.func, ast.Name) or node.keywords:
        return None
    name, args = node.func.id, node.args
    if name in {"is_null", "is_blank"} and len(args) == 1 and _is_value(args[0]):
        if name == "is_null":
            return lambda column: (pc.is_null(column), _false(column))

        def blank(column: pa.Array) -> tuple[pa.Array, pa.Array]:
            if not _is_text(column):
                return pc.is_null(column), _false(column)
            empty = pc.fill_null(pc.equal(pc.utf8_trim_whitespace(column), ""), _YES)
            return empty, unsafe_text(column)

        return blank
    if name == "matches" and len(args) == 2 and _is_value(args[1]):  # noqa: PLR2004
        try:
            pattern = _literal(args[0])
        except (TypeError, ValueError):
            return None
        if not isinstance(pattern, str):
            return None
        try:
            pc.match_substring_regex(_pa.array([""]), pattern)
        except pa.ArrowInvalid:
            return None  # not RE2: keep Python's semantics

        def match(column: pa.Array) -> tuple[pa.Array, pa.Array]:
            if not _is_text(column):
                return _false(column), everything(column)
            found = pc.fill_null(pc.match_substring_regex(column, pattern), _NO)
            breaks = pc.fill_null(pc.match_substring_regex(column, r"[\r\n]"), _NO)
            return found, pc.or_(unsafe_text(column), breaks)

        return match
    return None


def lower_expression(node: ast.expr) -> Mask | None:  # noqa: PLR0911 -- one per node type
    """A mask for a when expression's AST, or None when it does not lower."""
    if isinstance(node, ast.Compare):
        return _compare(node)
    if isinstance(node, ast.Call):
        return _call(node)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        inner = lower_expression(node.operand)
        if inner is None:
            return None
        return lambda column: _not(inner, column)
    if isinstance(node, ast.BoolOp):
        lowered = [lower_expression(v) for v in node.values]
        parts = [p for p in lowered if p is not None]
        if len(parts) != len(lowered):
            return None
        combine = pc.and_ if isinstance(node.op, ast.And) else pc.or_
        return lambda column: _combine(combine, parts, column)
    return None


def _not(inner: Mask, column: pa.Array) -> tuple[pa.Array, pa.Array]:
    mask, todo = inner(column)
    return pc.invert(mask), todo


def _combine(
    combine: Callable[[pa.Array, pa.Array], pa.Array], parts: list[Mask], column: pa.Array
) -> tuple[pa.Array, pa.Array]:
    mask, todo = parts[0](column)
    for part in parts[1:]:
        more, more_todo = part(column)
        mask, todo = combine(mask, more), pc.or_(todo, more_todo)
    return mask, todo


def lower_when(text: str) -> Mask | None:
    """A mask for a ``when`` expression, or None when it does not lower."""
    try:
        tree = parse_expression(text)
    except (SyntaxError, ValueError):
        return None
    return lower_expression(tree.body)


def chain_vector(steps: tuple[Op, ...], column_type: CType) -> Vector | None:
    """The ops of a chain as one vector op, or None when any op is not vectorisable."""
    parts: list[tuple[Vector, Any, CType]] = []
    for op in steps:
        if isinstance(op, CaseOp):
            lowered = case_vector(op, column_type)
            if lowered is None:
                return None
            parts.append((lowered, None, column_type))
            continue
        if not isinstance(op, CompiledStep):
            return None
        if isinstance(op.kwargs, CastArgs):
            fn, ctype = CASTS.get(op.kwargs.target.kind), op.kwargs.target
        else:
            fn, ctype = TRANSFORMS.get(op.transform.name), column_type
        if fn is None:
            return None
        parts.append((fn, op.kwargs, ctype))

    def run(column: pa.Array, _k: Any, _t: CType) -> tuple[pa.Array, pa.Array]:  # noqa: ANN401
        todo = _false(column)
        values = column
        for fn, kwargs, ctype in parts:
            values, more = fn(values, kwargs, ctype)
            todo = pc.or_(todo, pc.fill_null(more, _NO))
        return values, todo

    return run


def case_vector(op: CaseOp, column_type: CType) -> Vector | None:
    """A ``case`` (or a column's ``when``) as one vector op, or None when it does not lower."""
    if op.reads:
        return None
    whens: list[tuple[Mask, Vector]] = []
    for when, chain in op.branches:
        mask = lower_when(when.text)
        branch = chain_vector(chain.steps, column_type)
        if mask is None or branch is None:
            return None
        whens.append((mask, branch))
    otherwise: Vector | None = None
    if op.otherwise is not None:
        otherwise = chain_vector(op.otherwise.steps, column_type)
        if otherwise is None:
            return None

    def run(column: pa.Array, _k: Any, _t: CType) -> tuple[pa.Array, pa.Array]:  # noqa: ANN401
        if otherwise is None:
            result, result_todo = column, _false(column)
        else:
            result, result_todo = otherwise(column, None, column_type)
        when_todo = _false(column)
        for mask_fn, branch in reversed(whens):
            mask, more = mask_fn(column)
            values, values_todo = branch(column, None, column_type)
            if values.type != result.type:
                values = pc.cast(values, result.type)
            result = pc.if_else(mask, values, result)
            result_todo = pc.if_else(mask, values_todo, result_todo)
            when_todo = pc.or_(when_todo, more)
        return result, pc.or_(result_todo, when_todo)

    return run
