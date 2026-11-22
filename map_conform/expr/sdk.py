"""SDK stream-map expressions in map-conform's scope (detailed design §15).

An SDK stream-map expression sees the *source* record's properties as bare names. In
map-conform a bare name is a conformed column, so an SDK expression is rewritten once, when
its stream map is translated: every free name that the SDK would have resolved from the
record becomes ``record['name']``. ``self``, ``_``, ``record``, ``config``,
``__stream_name__``, ``__original_stream_name__``, ``fake`` and the SDK functions keep their
meaning, so the rewritten text evaluates exactly as the SDK would.
"""

from __future__ import annotations

import ast
import sys

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

_Comprehension = ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp

_SDK_NAMES = frozenset(
    {
        "self",
        "_",
        "record",
        "config",
        "__stream_name__",
        "__original_stream_name__",
        "fake",
        # simpleeval's DEFAULT_FUNCTIONS, its compound types, and the SDK's additions
        "list",
        "tuple",
        "dict",
        "set",
        "rand",
        "randint",
        "int",
        "float",
        "str",
        "md5",
        "sha256",
        "datetime",
        "bool",
        "json",
        # literals simpleeval also names
        "True",
        "False",
        "None",
    }
)


class _RecordNames(ast.NodeTransformer):
    """Rewrites free names to ``record[...]``, leaving comprehension variables alone."""

    def __init__(self) -> None:
        self.bound: list[set[str]] = []
        self.changed = False

    @override
    def visit_Name(self, node: ast.Name) -> ast.expr:
        if (
            not isinstance(node.ctx, ast.Load)
            or node.id in _SDK_NAMES
            or any(node.id in scope for scope in self.bound)
        ):
            return node
        self.changed = True
        record = ast.Name(id="record", ctx=ast.Load())
        return ast.copy_location(
            ast.Subscript(value=record, slice=ast.Constant(node.id), ctx=ast.Load()), node
        )

    def _comprehension(self, node: _Comprehension) -> ast.expr:
        pushed = 0
        for gen in node.generators:
            gen.iter = self.visit(gen.iter)
            self.bound.append({n.id for n in ast.walk(gen.target) if isinstance(n, ast.Name)})
            pushed += 1
            gen.ifs = [self.visit(cond) for cond in gen.ifs]
        if isinstance(node, ast.DictComp):
            node.key = self.visit(node.key)
            node.value = self.visit(_present(node.value))
        else:
            node.elt = self.visit(node.elt)
        del self.bound[len(self.bound) - pushed :]
        return node

    visit_ListComp = visit_SetComp = visit_GeneratorExp = visit_DictComp = _comprehension  # noqa: N815


def _present(node: ast.expr | None) -> ast.expr:
    """A child node the grammar requires (typeshed marks some optional on newer Pythons)."""
    if node is None:
        msg = "incomplete expression"
        raise SyntaxError(msg)
    return node


def rewrite_sdk_expression(text: str) -> str:
    """The expression with the record's properties read through ``record[...]``.

    Text that does not parse, or needs no change, is returned as written; compiling text
    that does not parse reports the error.
    """
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return text
    transformer = _RecordNames()
    rewritten = transformer.visit(tree)
    if not transformer.changed:
        return text
    return ast.unparse(ast.fix_missing_locations(rewritten))
