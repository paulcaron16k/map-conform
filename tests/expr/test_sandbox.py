"""Escape and exhaustion attempts are refused (WBS 6.1 acceptance)."""

from __future__ import annotations

import pytest

from map_conform.errors import StepFailed
from map_conform.expr import ExprError, Names, Row, compile_expr

ESCAPES_AT_COMPILE = [
    "__import__('os').system('true')",
    "open('/etc/passwd').read()",
    "eval('1')",
    "exec('x = 1')",
    "getattr(value, '__class__')",
    "globals()",
    "vars()",
    "type(value)",
    "compile('1', 'x', 'eval')",
    "breakpoint()",
    "value.__class__.__mro__[1].__subclasses__()",
    "value.__init__.__globals__",
    "md5.__globals__",
    "md5.__name__",
    "().__class__.__bases__[0]",
    "lambda: 0",
    "(x := 1)",
    "[x for x in ()].__len__()",
]

ESCAPES_AT_RUN = [
    # format() and format_map() reach attributes through the format string.
    "'{0.__class__.__mro__}'.format(value)",
    "'{a.__class__}'.format_map({'a': value})",
    # Generators carry frames (gi_frame.f_builtins): generator expressions are lists here.
    "(x for x in [1]).gi_frame",
    "(x for x in [1]).gi_code",
    # Modules expose only their listed names.
    "decimal.setcontext",
    "decimal.getcontext()",
    "datetime.sys",
    "re.sre_compile",
    "math.factorial(100000)",
    "json.codecs",
    # Library functions and classes are not receivers.
    "to_int.x",
    "str.mro()",
    # Mutating shared values.
    "record['tags'].append(1)",
    "record['meta'].update({})",
    "record['meta'].pop('k')",
    "record['tags'].sort()",
]

EXHAUSTION = [
    "'x' * 10 ** 8",
    "[0] * 10 ** 8",
    "10 ** 10 ** 6",
    "1 << 10 ** 8",
    "'x'.ljust(10 ** 9)",
    "'x'.zfill(10 ** 9)",
    "f'{1:>999999999}'",
    "'%999999999s' % 'x'",
    "list(range(10 ** 9))",
    "[1 for a in range(1000) for b in range(1000)]",
    "pad_left('x', 10 ** 9)",
]


def run(text: str) -> object:
    """Compile and evaluate on a small row."""
    row = Row.of({"tags": ["a"], "meta": {"k": 1}})
    return compile_expr(text, Names()).evaluate(row, "v")


@pytest.mark.parametrize("text", ESCAPES_AT_COMPILE)
def test_escapes_are_refused_at_compile(text: str) -> None:
    """Private attributes, missing builtins and forbidden syntax never compile."""
    with pytest.raises(ExprError):
        compile_expr(text, Names())


@pytest.mark.parametrize("text", ESCAPES_AT_RUN)
def test_escapes_are_refused_at_run(text: str) -> None:
    """What an expression reaches at run time is bounded by the sandbox."""
    with pytest.raises(StepFailed):
        run(text)


@pytest.mark.parametrize("text", EXHAUSTION)
def test_exhaustion_is_refused(text: str) -> None:
    """One short expression cannot exhaust memory or time."""
    with pytest.raises(StepFailed, match="not allowed"):
        run(text)


def test_record_values_are_not_changed_by_other_columns() -> None:
    """A copy can be built and changed; the shared record stays as it was."""
    row = Row.of({"tags": ["a"]})
    assert compile_expr("record['tags'] + ['b']").evaluate(row) == ["a", "b"]
    assert row.record["tags"] == ["a"]
