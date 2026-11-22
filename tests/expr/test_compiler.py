"""The expression compiler: syntax, names and scope, evaluation (WBS 6.1)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest

from map_conform.errors import StepFailed
from map_conform.expr import ExprError, Names, Row, compile_expr

RECORD = {"Order ID": "A-1", "qty": 3, "price": "2.50", "tags": ["x", "y"], "meta": {"k": 1}}
CONSTANTS = {"config": {"rate": 2}, "stream": "orders", "source_stream": "Orders Export"}


def evaluate(text: str, current: object = None, **names: Any) -> object:
    """Compile with the test names and evaluate on RECORD, with ``current`` as value."""
    columns = names.pop("columns", {"order_id": "A-1", "qty": 3, "price": Decimal("2.50")})
    scope = Names(columns=frozenset(columns), constants=CONSTANTS, **names)
    row = Row.of(RECORD, number=7)
    row.values.update(columns)
    return compile_expr(text, scope).evaluate(row, current)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1 + 2 * 3", 7),
        ("qty * price", Decimal("7.50")),
        ("7 // 2, 7 % 2, -qty, +qty, ~0, 2 ** 10", (3, 1, -3, 3, -1, 1024)),
        ("1 < qty <= 3", True),
        ("1 < qty < 3", False),
        ("qty in [1, 3] and order_id not in {'B'}", True),
        ("NULL is None and qty is not None", True),
        ("'big' if qty > 2 else 'small'", "big"),
        ("0 or '' or 'x'", "x"),
        ("1 and 0 and 2", 0),
        ("record['Order ID']", "A-1"),
        ("_['tags'][-1]", "y"),
        ("source('Order ID')", "A-1"),
        ("record['tags'][::-1]", ["y", "x"]),
        ("{**record['meta'], 'j': 2}", {"k": 1, "j": 2}),
        ("[*record['tags'], 'z']", ["x", "y", "z"]),
        ("[t.upper() for t in record['tags'] if t != 'x']", ["Y"]),
        ("{t: i for i, t in enumerate(record['tags'])}", {"x": 0, "y": 1}),
        ("sorted({len(t) for t in record['tags']})", [1]),
        ("sum(x * y for x in [1, 2] for y in [10, 100])", 330),
        ("f'{order_id}-{qty:03d}-{price!s}'", "A-1-003-2.50"),
        ("config['rate'] * qty", 6),
        ("stream + '/' + source_stream", "orders/Orders Export"),
        ("__stream_name__ == stream and __original_stream_name__ == source_stream", True),
        ("row_number", 7),
        ("max(qty, 10)", 10),
        ("datetime.date(2026, 3, 14).isoformat()", "2026-03-14"),
        ("decimal.Decimal('1.10') + 1", Decimal("2.10")),
        ("math.floor(2.7) + math.pi // 1", 5.0),
        ("re.sub('[^0-9]', '', '(555) 123')", "555123"),
        ("json.dumps({'a': 1})", '{"a": 1}'),
    ],
)
def test_evaluation(text: str, expected: object) -> None:
    """Operators, literals, displays, comprehensions, f-strings and modules behave as Python."""
    assert evaluate(text) == expected


def test_value_and_self_are_the_current_value() -> None:
    """In a column chain, value and self are the value the step works on."""
    assert evaluate("value.strip() + self.strip()", " a ") == "aa"


def test_value_is_a_column_where_there_is_no_current_value() -> None:
    """A filter has no current value, so value is an ordinary column name there."""
    assert evaluate("value * 2", columns={"value": 4}, value=False) == 8  # noqa: PLR2004


def test_reads_lists_the_column_dependencies() -> None:
    """Columns read by an expression are its dependencies; record and value are not."""
    names = Names(columns=frozenset({"a", "b", "c"}))
    expression = compile_expr("a + b if record['x'] else value", names)
    assert expression.reads == {"a", "b"}
    assert expression.uses_value


def test_comprehension_variables_shadow_columns() -> None:
    """A comprehension variable named like a column is the variable, and is not a dependency."""
    names = Names(columns=frozenset({"qty"}))
    expression = compile_expr("[qty for qty in [1, 2]]", names)
    assert expression.reads == frozenset()
    assert expression.evaluate(Row.of({})) == [1, 2]


def test_functions_win_in_call_position() -> None:
    """A column named max does not hide max(); the bare name is the column."""
    assert evaluate("max(1, 2) + max", columns={"max": 10}) == 12  # noqa: PLR2004


def test_record_is_read_only() -> None:
    """The source record cannot be changed through an expression."""
    with pytest.raises(StepFailed, match=r"has no attribute 'update'"):
        evaluate("record.update({'qty': 0})")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("qty +", "syntax error"),
        ("x = 1", "syntax error"),
        ("nope + 1", "unknown name 'nope'; use record\\['nope'\\]"),
        ("value", "unknown name 'value' \\(no value here\\)"),
        ("total * 2", "'total' is the column being computed; use value"),
        ("lambda: 1", "a lambda is not allowed"),
        ("(y := 1)", "assignment \\(:=\\) is not allowed"),
        ("qty @ qty", "operator MatMult is not allowed"),
        ("value.__class__", "attribute '__class__' is not allowed"),
        ("(lambda: md5)()('x')", "only named functions and methods can be called"),
        ("[md5][0]('x')", "only named functions and methods can be called"),
        ("[x for x.y in [1]]", "a comprehension target must be a name"),
        ("source('a', 'b')", "source takes one source property name"),
    ],
)
def test_compile_errors(text: str, message: str) -> None:
    """Problems are found when the expression is compiled, with a reason."""
    names = Names(
        columns=frozenset({"qty", "total"}),
        own="total",
        value="value" not in text or "__class__" in text,
    )
    with pytest.raises(ExprError, match=message):
        compile_expr(text, names)


def test_compile_error_names_the_column_offset() -> None:
    """Errors say where in the expression the problem is."""
    with pytest.raises(ExprError, match="at column 5"):
        compile_expr("1 + nope")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("qty / 0", "ZeroDivisionError"),
        ("record['missing']", "KeyError: 'missing'"),
        ("int('x')", "ValueError"),
        ("record['tags'] + 1", "TypeError"),
    ],
)
def test_runtime_errors_become_step_failures(text: str, message: str) -> None:
    """A failing evaluation is a StepFailed for the column's on_error, never a crash."""
    with pytest.raises(StepFailed, match=message):
        evaluate(text)


def test_temporal_values_support_their_methods() -> None:
    """Typed values from conformed columns keep their methods."""
    moment = dt.datetime(2026, 3, 14, 9, 26, tzinfo=dt.UTC)
    assert evaluate("ts.date().year + ts.hour", columns={"ts": moment}) == 2035  # noqa: PLR2004


def test_regex_escapes_in_plain_strings_need_no_raw_prefix() -> None:
    r"""YAML authors write matches("^\d+$", x); the backslash stays, without a warning."""
    assert evaluate(r'matches("^\d+$", "12") and not matches("^\d+$", "1a")') is True
