"""Compile expressions to Python closures (detailed design §7).

An expression is parsed once with ``ast.parse(mode="eval")``. A whitelist visitor turns each
node into a closure, so evaluation never walks the tree again, and every name is resolved at
compile time: an unknown name is an error at the spec path, not a crash on the first row.

**Names**, in the order they are looked up:

1. comprehension variables;
2. ``value`` (alias ``self``): the value the step works on, in a column chain;
3. ``record`` (alias ``_``): the source record, read-only; ``row_number``; ``NULL``;
4. the compile-time constants: ``config``, ``stream``, ``source_stream`` (and the SDK names
   ``__stream_name__``, ``__original_stream_name__``), plus any functions the caller adds;
5. the stream's columns, by conformed name: their conformed values (the column being
   computed is not one of them: use ``value``, or ``record[...]`` for its source);
6. the function library and the read-only modules.

In call position (``name(...)``) functions are looked up before columns, so a column named
``max`` does not hide ``max()``. ``source(name)`` reads the source record by raw name.

Anything outside the whitelist (assignment, lambdas, ``await``, the walrus operator, private
attributes, calls through anything but a name or an attribute) is a compile error. What an
evaluation may reach at run time is bounded by :mod:`map_conform.expr.sandbox`.
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from map_conform.errors import StepFailed
from map_conform.expr.functions import FUNCTIONS
from map_conform.expr.sandbox import (
    MAX_ITEMS,
    SandboxError,
    check_format_spec,
    get_attribute,
    left_shift,
    multiply,
    power,
)

Closure = Callable[["Frame"], Any]

_VALUE_NAMES = frozenset({"value", "self"})
_RECORD_NAMES = frozenset({"record", "_"})
_STREAM_ALIASES = MappingProxyType(
    {"__stream_name__": "stream", "__original_stream_name__": "source_stream"}
)


class ExprError(Exception):
    """An expression that cannot be compiled; the message says where and why."""


@dataclass(slots=True)
class Row:
    """What expressions can see of the row being conformed."""

    record: Mapping[str, Any]
    """The source record, read-only."""
    values: dict[str, Any] = field(default_factory=dict)
    """Conformed values of the columns computed so far, by output name."""
    number: int = 0
    """The row's ordinal within its tap stream."""

    @classmethod
    def of(cls, record: Mapping[str, Any], number: int = 0) -> Row:
        """A row over a source record, which expressions cannot change."""
        return cls(MappingProxyType(dict(record)), {}, number)


@dataclass(slots=True)
class Frame:
    """One evaluation: the row, the current value and any comprehension variables."""

    row: Row
    value: Any
    local: dict[str, Any]


@dataclass(frozen=True)
class Names:
    """What an expression may refer to, fixed when it is compiled."""

    columns: frozenset[str] = frozenset()
    """Conformed column names in scope."""
    own: str | None = None
    """The column this expression computes, which it cannot read by name."""
    value: bool = True
    """Whether ``value``/``self`` are in scope (true in column chains)."""
    constants: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    """``config``, ``stream``, ``source_stream`` and any extra functions."""


@dataclass(frozen=True)
class Expression:
    """A compiled expression."""

    text: str
    reads: frozenset[str]
    """The columns it reads, by conformed name; its dependencies."""
    uses_value: bool
    _fn: Closure = field(repr=False, compare=False)

    def evaluate(self, row: Row, value: object = None) -> Any:  # noqa: ANN401 -- any value
        """Evaluate on a row.

        Raises:
            StepFailed: naming the error, for the caller's ``on_error``.
        """
        try:
            result = self._fn(Frame(row, value, {}))
        except StepFailed:
            raise
        except SandboxError as exc:
            raise StepFailed(str(exc)) from None
        except Exception as exc:  # noqa: BLE001 -- any failure becomes a cell error with context
            raise StepFailed(f"{type(exc).__name__}: {exc}") from None
        # The read-only record view leaves the sandbox as a plain dict (``_data: record``).
        return dict(result) if isinstance(result, MappingProxyType) else result


def compile_expr(text: str, names: Names | None = None) -> Expression:
    """Compile an expression.

    Raises:
        ExprError: for a syntax error, a construct outside the whitelist, or an unknown name.
    """
    names = names or Names()
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except SyntaxError as exc:
        raise ExprError(f"syntax error: {exc.msg} (at column {exc.offset or 0})") from None
    except (ValueError, RecursionError, MemoryError) as exc:
        raise ExprError(f"cannot parse: {type(exc).__name__}") from None
    compiler = _Compiler(names)
    fn = compiler.node(tree.body)
    return Expression(text, frozenset(compiler.reads), compiler.uses_value, fn)


_BINARY: Mapping[type[ast.operator], Callable[[Any, Any], Any]] = MappingProxyType(
    {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: multiply,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: lambda a, b: operator.mod(check_format_spec(a) if isinstance(a, str) else a, b),
        ast.Pow: power,
        ast.LShift: left_shift,
        ast.RShift: operator.rshift,
        ast.BitOr: operator.or_,
        ast.BitXor: operator.xor,
        ast.BitAnd: operator.and_,
    }
)
_UNARY: Mapping[type[ast.unaryop], Callable[[Any], Any]] = MappingProxyType(
    {
        ast.Not: operator.not_,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
        ast.Invert: operator.invert,
    }
)
_COMPARE: Mapping[type[ast.cmpop], Callable[[Any, Any], bool]] = MappingProxyType(
    {
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
        ast.Gt: operator.gt,
        ast.GtE: operator.ge,
        ast.Is: operator.is_,
        ast.IsNot: operator.is_not,
        ast.In: lambda a, b: a in b,
        ast.NotIn: lambda a, b: a not in b,
    }
)
_CONVERSIONS: Mapping[int, Callable[[Any], Any]] = MappingProxyType(
    {-1: lambda v: v, ord("s"): str, ord("r"): repr, ord("a"): ascii}
)


class _Compiler:
    """Turns whitelisted AST nodes into closures."""

    def __init__(self, names: Names) -> None:
        self.names = names
        self.reads: set[str] = set()
        self.uses_value = False
        self.scopes: list[frozenset[str]] = []

    def node(self, node: ast.expr) -> Closure:
        method = getattr(self, f"_{type(node).__name__}", None)
        if method is None:
            raise ExprError(f"{_describe(node)} is not allowed in expressions{_at(node)}")
        return method(node)

    # --- leaves -------------------------------------------------------------------------

    def _Constant(self, node: ast.Constant) -> Closure:  # noqa: N802 -- AST node name
        value = node.value
        return lambda _f: value

    def _Name(self, node: ast.Name, *, call: bool = False) -> Closure:  # noqa: N802, C901, PLR0911, PLR0912 -- one branch per scope
        name = node.id
        if any(name in scope for scope in self.scopes):
            return lambda f: f.local[name]
        if name in _VALUE_NAMES and self.names.value:
            self.uses_value = True
            return lambda f: f.value
        if name in _RECORD_NAMES:
            return lambda f: f.row.record
        if name == "row_number":
            return lambda f: f.row.number
        if name == "NULL":
            return lambda _f: None
        constant_name = _STREAM_ALIASES.get(name, name)
        if constant_name in self.names.constants:
            constant = self.names.constants[constant_name]
            return lambda _f: constant
        if call and name in FUNCTIONS:
            fn = FUNCTIONS[name].fn
            return lambda _f: fn
        if name == self.names.own:
            raise ExprError(
                f"{name!r} is the column being computed; use value, or record[{name!r}] "
                f"for its source{_at(node)}"
            )
        if name in self.names.columns:
            self.reads.add(name)
            return lambda f: f.row.values.get(name)
        if name in FUNCTIONS:
            fn = FUNCTIONS[name].fn
            return lambda _f: fn
        if name in _VALUE_NAMES:
            hint = " (no value here)"
        elif name.startswith("_"):
            hint = ""
        else:
            hint = f"; use record[{name!r}] for a source property"
        raise ExprError(f"unknown name {name!r}{hint}{_at(node)}")

    # --- operators ----------------------------------------------------------------------

    def _BinOp(self, node: ast.BinOp) -> Closure:  # noqa: N802
        op = _BINARY.get(type(node.op))
        if op is None:
            raise ExprError(f"operator {type(node.op).__name__} is not allowed{_at(node)}")
        left, right = self.node(node.left), self.node(node.right)
        return lambda f: op(left(f), right(f))

    def _UnaryOp(self, node: ast.UnaryOp) -> Closure:  # noqa: N802
        op = _UNARY[type(node.op)]
        operand = self.node(node.operand)
        return lambda f: op(operand(f))

    def _BoolOp(self, node: ast.BoolOp) -> Closure:  # noqa: N802
        parts = [self.node(v) for v in node.values]
        if isinstance(node.op, ast.And):

            def all_of(f: Frame) -> Any:  # noqa: ANN401
                result: Any = True
                for part in parts:
                    result = part(f)
                    if not result:
                        return result
                return result

            return all_of

        def any_of(f: Frame) -> Any:  # noqa: ANN401
            result: Any = False
            for part in parts:
                result = part(f)
                if result:
                    return result
            return result

        return any_of

    def _Compare(self, node: ast.Compare) -> Closure:  # noqa: N802
        left = self.node(node.left)
        steps = [
            (_COMPARE[type(op)], self.node(right))
            for op, right in zip(node.ops, node.comparators, strict=True)
        ]

        def compare(f: Frame) -> bool:
            current = left(f)
            for op, right in steps:
                following = right(f)
                if not op(current, following):
                    return False
                current = following
            return True

        return compare

    def _IfExp(self, node: ast.IfExp) -> Closure:  # noqa: N802
        test, body, orelse = self.node(node.test), self.node(node.body), self.node(node.orelse)
        return lambda f: body(f) if test(f) else orelse(f)

    # --- access -------------------------------------------------------------------------

    def _Attribute(self, node: ast.Attribute) -> Closure:  # noqa: N802
        if node.attr.startswith("_"):
            raise ExprError(f"attribute {node.attr!r} is not allowed{_at(node)}")
        obj = self.node(node.value)
        attr = node.attr
        return lambda f: get_attribute(obj(f), attr)

    def _Subscript(self, node: ast.Subscript) -> Closure:  # noqa: N802
        obj, key = self.node(node.value), self.node(node.slice)
        return lambda f: obj(f)[key(f)]

    def _Slice(self, node: ast.Slice) -> Closure:  # noqa: N802
        parts = [None if p is None else self.node(p) for p in (node.lower, node.upper, node.step)]
        return lambda f: slice(*(None if p is None else p(f) for p in parts))

    def _Call(self, node: ast.Call) -> Closure:  # noqa: N802
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "source"
            and not self._local("source")
        ):
            return self._source(node)
        if isinstance(node.func, ast.Name):
            func = self._Name(node.func, call=True)
        elif isinstance(node.func, ast.Attribute):
            func = self._Attribute(node.func)
        else:
            raise ExprError(f"only named functions and methods can be called{_at(node)}")
        args = self._items(node.args)
        kwargs = [(k.arg, self.node(k.value)) for k in node.keywords]

        def call(f: Frame) -> Any:  # noqa: ANN401
            named: dict[str, Any] = {}
            for key, value in kwargs:
                if key is None:
                    named.update(value(f))
                else:
                    named[key] = value(f)
            return func(f)(*args(f), **named)

        return call

    def _source(self, node: ast.Call) -> Closure:
        if len(node.args) != 1 or node.keywords:
            raise ExprError(f"source takes one source property name{_at(node)}")
        name = self.node(node.args[0])
        return lambda f: f.row.record.get(name(f))

    def _local(self, name: str) -> bool:
        return any(name in scope for scope in self.scopes)

    # --- displays -----------------------------------------------------------------------

    def _items(self, nodes: list[ast.expr]) -> Callable[[Frame], list[Any]]:
        parts: list[tuple[bool, Closure]] = []
        for item in nodes:
            if isinstance(item, ast.Starred):
                parts.append((True, self.node(item.value)))
            else:
                parts.append((False, self.node(item)))

        def items(f: Frame) -> list[Any]:
            out: list[Any] = []
            for starred, part in parts:
                if starred:
                    out.extend(part(f))
                else:
                    out.append(part(f))
            return out

        return items

    def _List(self, node: ast.List) -> Closure:  # noqa: N802
        return self._items(node.elts)

    def _Tuple(self, node: ast.Tuple) -> Closure:  # noqa: N802
        items = self._items(node.elts)
        return lambda f: tuple(items(f))

    def _Set(self, node: ast.Set) -> Closure:  # noqa: N802
        items = self._items(node.elts)
        return lambda f: set(items(f))

    def _Dict(self, node: ast.Dict) -> Closure:  # noqa: N802
        pairs = [
            (None if k is None else self.node(k), self.node(v))
            for k, v in zip(node.keys, node.values, strict=True)
        ]

        def build(f: Frame) -> dict[Any, Any]:
            out: dict[Any, Any] = {}
            for key, value in pairs:
                if key is None:
                    out.update(value(f))
                else:
                    out[key(f)] = value(f)
            return out

        return build

    def _JoinedStr(self, node: ast.JoinedStr) -> Closure:  # noqa: N802
        parts = [self.node(v) for v in node.values]
        return lambda f: "".join(str(p(f)) for p in parts)

    def _FormattedValue(self, node: ast.FormattedValue) -> Closure:  # noqa: N802
        value = self.node(node.value)
        convert = _CONVERSIONS[node.conversion]
        spec = None if node.format_spec is None else self.node(node.format_spec)
        if spec is None:
            return lambda f: format(convert(value(f)))
        return lambda f: format(convert(value(f)), check_format_spec(spec(f)))

    # --- comprehensions -----------------------------------------------------------------

    def _comprehension(
        self, node: ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp
    ) -> tuple[list[tuple[Callable[[Any, dict[str, Any]], None], Closure, list[Closure]]], Any]:
        loops: list[tuple[Callable[[Any, dict[str, Any]], None], Closure, list[Closure]]] = []
        pushed = 0
        try:
            for gen in node.generators:
                if gen.is_async:
                    raise ExprError(f"async comprehensions are not allowed{_at(node)}")
                iterable = self.node(gen.iter)  # evaluated in the enclosing scope
                bind, bound = _binder(gen.target)
                self.scopes.append(bound)
                pushed += 1
                loops.append((bind, iterable, [self.node(c) for c in gen.ifs]))
            if isinstance(node, ast.DictComp):
                body: Any = (self.node(node.key), self.node(_present(node.value)))
            else:
                body = self.node(node.elt)
        finally:
            del self.scopes[len(self.scopes) - pushed :]
        return loops, body

    def _ListComp(self, node: ast.ListComp) -> Closure:  # noqa: N802
        loops, body = self._comprehension(node)
        return lambda f: [body(inner) for inner in _iterate(loops, f)]

    def _GeneratorExp(self, node: ast.GeneratorExp) -> Closure:  # noqa: N802
        # Evaluated eagerly: a generator object would carry a frame out of the sandbox.
        loops, body = self._comprehension(node)
        return lambda f: [body(inner) for inner in _iterate(loops, f)]

    def _SetComp(self, node: ast.SetComp) -> Closure:  # noqa: N802
        loops, body = self._comprehension(node)
        return lambda f: {body(inner) for inner in _iterate(loops, f)}

    def _DictComp(self, node: ast.DictComp) -> Closure:  # noqa: N802
        loops, (key, value) = self._comprehension(node)
        return lambda f: {key(inner): value(inner) for inner in _iterate(loops, f)}


def _binder(target: ast.expr) -> tuple[Callable[[Any, dict[str, Any]], None], frozenset[str]]:
    """How a comprehension target binds an item, and the names it binds."""
    if isinstance(target, ast.Name):
        name = target.id

        def bind_name(item: object, local: dict[str, Any]) -> None:
            local[name] = item

        return bind_name, frozenset({name})
    if isinstance(target, ast.Tuple) and all(isinstance(e, ast.Name) for e in target.elts):
        names = [e.id for e in target.elts if isinstance(e, ast.Name)]

        def bind_tuple(item: Any, local: dict[str, Any]) -> None:  # noqa: ANN401
            values = tuple(item)
            if len(values) != len(names):
                msg = f"cannot unpack {len(values)} values into {len(names)} names"
                raise ValueError(msg)
            local.update(zip(names, values, strict=True))

        return bind_tuple, frozenset(names)
    raise ExprError(f"a comprehension target must be a name or a tuple of names{_at(target)}")


def _iterate(
    loops: list[tuple[Callable[[Any, dict[str, Any]], None], Closure, list[Closure]]],
    frame: Frame,
) -> Iterator[Frame]:
    """Every combination of the loops' items that passes their conditions, at most MAX_ITEMS."""
    budget = [MAX_ITEMS]

    def level(index: int, current: Frame) -> Iterator[Frame]:
        if index == len(loops):
            yield current
            return
        bind, iterable, conditions = loops[index]
        for item in iterable(current):
            budget[0] -= 1
            if budget[0] < 0:
                msg = f"more than {MAX_ITEMS} steps in one comprehension is not allowed"
                raise SandboxError(msg)
            local = dict(current.local)
            bind(item, local)
            inner = Frame(current.row, current.value, local)
            if all(condition(inner) for condition in conditions):
                yield from level(index + 1, inner)

    return level(0, frame)


def _present(node: ast.expr | None) -> ast.expr:
    """A child node the grammar requires (typeshed marks some optional on newer Pythons)."""
    if node is None:
        raise ExprError("incomplete expression")
    return node


def _describe(node: ast.AST) -> str:
    names = {
        "Lambda": "a lambda",
        "NamedExpr": "assignment (:=)",
        "Await": "await",
        "Yield": "yield",
        "YieldFrom": "yield",
        "Starred": "unpacking here",
    }
    return names.get(type(node).__name__, type(node).__name__)


def _at(node: ast.AST) -> str:
    offset = getattr(node, "col_offset", None)
    return "" if offset is None else f" (at column {offset + 1})"
