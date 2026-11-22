"""Expressions in plans: expr, case, when, derived columns, filter, macros, fields.

WBS 6.3 (case and ternary), 6.4 (macros with params), 6.6 (derived columns and filter) and
12.6 (when on a column or step; fields for nested paths).
"""

from __future__ import annotations

from typing import Any

import pytest

from map_conform.errors import ConformError, RowRejected
from map_conform.plan.compile import StreamPlan, compile_stream
from map_conform.plan.row import RowExecutor
from map_conform.spec.errors import SpecError
from map_conform.spec.load import resolve_stream
from map_conform.spec.model import parse_spec
from map_conform.transforms.builtins import builtin_registry

STRING = {"type": ["null", "string"]}
INTEGER = {"type": ["null", "integer"]}
OBJECT = {"type": ["null", "object"]}


def plan_for(  # noqa: PLR0913 -- the spec's parts
    columns: dict[str, Any],
    properties: dict[str, Any],
    *,
    stream: dict[str, Any] | None = None,
    macros: dict[str, Any] | None = None,
    defaults: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[StreamPlan, RowExecutor]:
    """Compile stream ``s`` with these columns over a tap SCHEMA of ``properties``."""
    spec = parse_spec({
        "version": 1,
        "defaults": {"metadata": "none", **(defaults or {})},
        "macros": macros or {},
        "streams": {"s": {"columns": columns, **(stream or {})}},
    })  # fmt: skip
    resolved = resolve_stream(spec, "s")
    assert resolved is not None
    schema = {"type": "object", "properties": properties}
    plan = compile_stream(spec, resolved, schema, builtin_registry(), config=config)
    return plan, RowExecutor(plan, resolved.settings)


def conform(
    columns: dict[str, Any], properties: dict[str, Any], *records: dict[str, Any], **kw: Any
) -> list[dict[str, Any] | None]:
    """Conform records; None for a filtered row."""
    _, executor = plan_for(columns, properties, **kw)
    return [executor.run(record, {}, i) for i, record in enumerate(records, 1)]


def problems(columns: dict[str, Any], properties: dict[str, Any], **kw: Any) -> list[str]:
    """Compile problems."""
    with pytest.raises(SpecError) as caught:
        plan_for(columns, properties, **kw)
    return [str(i) for i in caught.value.issues]


# --- expr and ternary (6.3) -------------------------------------------------------------------


def test_expr_step_then_implicit_cast() -> None:
    """An expr result is cast to the column's type."""
    out = conform(
        {"code": {"type": "int64", "transform": {"expr": "value.replace('O', '0')"}}},
        {"code": STRING},
        {"code": "1O5"},
    )
    assert out == [{"code": 105}]


def test_ternary() -> None:
    """X if c else y inside an expr."""
    columns = {"qty": {"type": "string", "transform": {"expr": "'many' if value > 9 else 'few'"}}}
    out = conform(columns, {"qty": INTEGER}, {"qty": 10}, {"qty": 1})
    assert out == [{"qty": "many"}, {"qty": "few"}]


def test_expr_after_the_cast_is_cast_again() -> None:
    """An expr after the cast leaves an untyped value, so the implicit cast runs again."""
    columns = {"price": {"type": "decimal(10,2)", "transform": ["cast", {"expr": "value * 2"}]}}
    out = conform(columns, {"price": STRING}, {"price": "1.25"})
    assert out == [{"price": "2.50"}]


def test_expr_sees_nulls() -> None:
    """Expressions are null-safe, so coalesce works."""
    columns = {"n": {"type": "int64", "transform": {"expr": "coalesce(value, 0)"}}}
    assert conform(columns, {"n": INTEGER}, {"n": None}) == [{"n": 0}]


def test_expr_errors_follow_on_error() -> None:
    """A failing expression is a ConformError naming the column, row and expression."""
    _, executor = plan_for({"n": {"type": "int64", "expr": "value // 0"}}, {"n": INTEGER})
    with pytest.raises(ConformError, match=r"column 'n', row 1: expr: value // 0 failed"):
        executor.run({"n": 1}, {}, 1)
    out = conform(
        {"n": {"type": "int64", "expr": "value // 0", "on_error": "null"}}, {"n": INTEGER}, {"n": 1}
    )
    assert out == [{"n": None}]


# --- case (6.3) -------------------------------------------------------------------------------


# The design's example (§7) minus its is_datetime branch: RECORD values are never datetimes
# before the cast (that branch is for typed BATCH input, P4).
DESIGN_CASE = {
    "case": [
        {"when": "is_null(value) or is_blank(value)", "then": "set_null"},
        {
            "when": r"matches('^\d{5}(\.\d+)?$', value)",
            "then": {"cast": "timestamptz", "formats": ["excel_serial"]},
        },
        {
            "else": {
                "cast": "timestamptz",
                "formats": ["iso", "%m/%d/%Y %H:%M"],
                "tz": "America/Chicago",
            }
        },
    ]
}


def test_design_case_example() -> None:
    """The detailed design's case example (§7): blanks, serials and two text formats."""
    columns = {"ts": {"type": "timestamptz", "transform": DESIGN_CASE}}
    rows = [{"ts": "  "}, {"ts": "46095.5"}, {"ts": "03/14/2026 09:30"}, {"ts": "2026-03-14"}]
    out = conform(columns, {"ts": STRING}, *rows)
    assert [r["ts"] if r else r for r in out] == [
        None,
        "2026-03-14T12:00:00.000000Z",
        "2026-03-14T14:30:00.000000Z",
        "2026-03-14T05:00:00.000000Z",  # naive input is in tz America/Chicago
    ]


def test_case_branches_with_different_types_are_each_cast() -> None:
    """Branches ending in different types each get the implicit cast."""
    columns = {
        "n": {
            "type": "int64",
            "transform": {
                "case": [
                    {"when": "value == 'none'", "then": {"expr": "0"}},
                    {"else": {"cast": "int64", "locale": "eu"}},
                ]
            },
        }
    }
    out = conform(columns, {"n": STRING}, {"n": "none"}, {"n": "1.234"})
    assert out == [{"n": 0}, {"n": 1234}]
    (rule,) = plan_for(columns, {"n": STRING})[0].columns[0].steps
    assert rule == "case: when value == 'none' -> [expr: 0, cast: int64]; else -> [cast: int64]"


def test_case_without_else_passes_the_value() -> None:
    """Rows matching no branch keep their value."""
    columns = {
        "s": {
            "type": "string",
            "transform": {"case": [{"when": "value == 'N/A'", "then": {"expr": "'unknown'"}}]},
        }
    }
    assert conform(columns, {"s": STRING}, {"s": "N/A"}, {"s": "ok"}) == [
        {"s": "unknown"},
        {"s": "ok"},
    ]


def test_case_problems_have_paths() -> None:
    """A bad when or branch step is reported at its own path."""
    found = problems(
        {"s": {"transform": {"case": [{"when": "nope", "then": "frobnicate"}, {"else": "trim"}]}}},
        {"s": STRING},
    )
    assert "streams.s.columns.s.transform.case[0].when: unknown name 'nope'" in found[0]
    assert "streams.s.columns.s.transform.case[0].then: unknown step 'frobnicate'" in found[1]


# --- when on steps and columns (12.6) --------------------------------------------------------


def test_step_when_with_a_falsy_literal() -> None:
    """when: qty == 0 matches 0 (pipelinewise's equals: 0 bug is not reproduced)."""
    columns = {
        "qty": {"type": "string"},
        "note": {"type": "string", "transform": {"upper": None, "when": "qty == '0'"}},
    }
    out = conform(columns, {"qty": STRING, "note": STRING},
                  {"qty": "0", "note": "zero"}, {"qty": "1", "note": "one"})  # fmt: skip
    assert out == [{"qty": "0", "note": "ZERO"}, {"qty": "1", "note": "one"}]


def test_step_when_on_typed_columns() -> None:
    """When compares conformed values: an int64 column against the int 0."""
    columns = {
        "qty": {"type": "int64"},
        "email": {"type": "string", "transform": {"hash": {}, "when": "qty == 0"}},
    }
    out = conform(columns, {"qty": STRING, "email": STRING}, {"qty": "0", "email": "a"})
    assert out[0] is not None
    assert out[0]["email"] == "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb"


def test_step_when_must_keep_the_type() -> None:
    """After the cast, a guarded step that changes the type would leave rows mixed."""
    found = problems(
        {"n": {"type": "int64", "transform": ["cast", {"expr": "value * 2", "when": "value > 9"}]}},
        {"n": STRING},
    )
    assert "a step with 'when' must keep the value's type" in found[0]


def test_column_when_keeps_other_rows_cast() -> None:
    """Rows where a column's when is false get only the implicit cast."""
    columns = {
        "country": {"type": "string"},
        "phone": {
            "type": "string",
            "transform": {"mask": {"keep_last": 2}},
            "when": "country == 'DE'",
        },
    }
    rows = [{"country": "DE", "phone": "12345"}, {"country": "US", "phone": " 12345 "}]
    out = conform(columns, {"country": STRING, "phone": STRING}, *rows)
    assert out == [{"country": "DE", "phone": "***45"}, {"country": "US", "phone": "12345"}]


def test_macro_step_with_when() -> None:
    """A macro reference can carry when; its expansion runs only where it holds."""
    out = conform(
        {"s": {"type": "string", "transform": {"shout": {}, "when": "value != 'quiet'"}}},
        {"s": STRING},
        {"s": "hi"},
        {"s": "quiet"},
        macros={"shout": ["upper", {"expr": "value + '!'"}]},
    )
    assert out == [{"s": "HI!"}, {"s": "quiet"}]


# --- derived columns and filter (6.6) --------------------------------------------------------


def test_derived_columns_follow_their_dependencies() -> None:
    """A derived column declared before its inputs is computed after them."""
    columns = {
        "total": {"type": "decimal(12,2)", "expr": "qty * price"},
        "label": {"type": "string", "expr": "f'{qty} x {price}'"},
        "qty": {"type": "int64"},
        "price": {"type": "decimal(10,2)", "transform": {"strip_chars": "$"}},
    }
    plan, executor = plan_for(columns, {"qty": STRING, "price": STRING})
    names = [c.name for c in plan.columns]
    assert [names[i] for i in plan.order] == ["qty", "price", "total", "label"]
    assert next(c for c in plan.columns if c.name == "total").reads == {"qty", "price"}
    assert executor.run({"qty": "3", "price": "$2.50"}, {}, 1) == {
        "total": "7.50",
        "label": "3 x 2.50",
        "qty": 3,
        "price": "2.50",
    }


def test_dependency_cycles_are_errors() -> None:
    """A reads b and b reads a."""
    found = problems(
        {"a": {"type": "int64", "expr": "b + 1"}, "b": {"type": "int64", "expr": "a + 1"}}, {}
    )
    assert found == ["streams.s.columns.a: dependency cycle: a -> b -> a"]


def test_a_column_cannot_read_itself() -> None:
    """The column being computed is not in scope by name."""
    found = problems({"n": {"type": "int64", "expr": "n + 1"}}, {"n": INTEGER})
    assert "streams.s.columns.n.expr: 'n' is the column being computed; use value" in found[0]


def test_derived_column_needs_a_type() -> None:
    """A new column has no tap type to inherit."""
    found = problems({"new": {"expr": "1"}}, {})
    assert "declare its type" in found[0]


def test_record_source_and_config() -> None:
    """record, source() and config reach the raw record and spec_vars."""
    columns = {
        "raw": {"type": "string", "expr": "record['Order ID'] + source('Order ID')"},
        "region": {"type": "string", "expr": "config['region']"},
    }
    out = conform(
        columns, {"Order ID": STRING}, {"Order ID": "7"}, config={"region": "emea"},
        stream={"undeclared": "drop"},
    )  # fmt: skip
    assert out == [{"raw": "77", "region": "emea"}]


def test_filter_sees_conformed_values() -> None:
    """Filter compares typed values and drops falsy rows."""
    _, executor = plan_for(
        {"Qty": {"type": "int64"}}, {"Qty": STRING}, stream={"filter": "qty >= 10"}
    )
    assert executor.run({"Qty": "12"}, {}, 1) == {"qty": 12}
    assert executor.run({"Qty": "9"}, {}, 2) is None
    assert executor.metrics.rows_filtered == 1


@pytest.mark.parametrize(
    ("on_error", "outcome"), [("raise", ConformError), ("reject", RowRejected), ("null", None)]
)
def test_filter_errors_follow_on_error(on_error: str, outcome: type[Exception] | None) -> None:
    """A filter that fails raises, rejects, or (null) drops the row."""
    _, executor = plan_for(
        {"n": {"type": "int64"}},
        {"n": INTEGER},
        stream={"filter": "10 // n", "on_error": on_error},
    )
    if outcome is None:
        assert executor.run({"n": 0}, {}, 1) is None
    else:
        with pytest.raises(outcome, match="filter: 10 // n"):
            executor.run({"n": 0}, {}, 1)


def test_filter_keep_keeps_the_row() -> None:
    """on_error: keep keeps a row whose filter fails."""
    _, executor = plan_for(
        {"n": {"type": "string"}}, {"n": STRING}, stream={"filter": "1 // 0", "on_error": "keep"}
    )
    assert executor.run({"n": "x"}, {}, 1) == {"n": "x"}


# --- macros with params (6.4) ------------------------------------------------------------------

DESIGN_MACROS = {
    "money": {
        "params": {"currency": "$"},
        "steps": [{"strip_chars": "${currency}, "}, {"cast": "decimal", "parens_negative": True}],
    },
    "sheet_date": {
        "steps": [
            {
                "cast": "timestamptz",
                "formats": ["%m/%d/%Y %I:%M %p", "%m/%d/%Y", "excel_serial", "iso"],
            }
        ]
    },
}


def test_money_and_sheet_date_macros() -> None:
    """The design's macros, with a parameter overridden."""
    columns = {
        "usd": {"type": "decimal(12,2)", "transform": "money"},
        "eur": {"type": "decimal(12,2)", "transform": {"money": {"currency": "€"}}},
        "ts": {"type": "timestamptz", "transform": "sheet_date"},
    }
    out = conform(
        columns,
        {"usd": STRING, "eur": STRING, "ts": STRING},
        {"usd": "($1,234.50)", "eur": "€ 99", "ts": "3/14/2026 9:30 PM"},
        {"usd": "$5", "eur": "€1,000", "ts": "46095"},
        macros=DESIGN_MACROS,
    )
    assert out == [
        {"usd": "-1234.50", "eur": "99.00", "ts": "2026-03-14T21:30:00.000000Z"},
        {"usd": "5.00", "eur": "1000.00", "ts": "2026-03-14T00:00:00.000000Z"},
    ]


def test_builtins_casts_and_macros_as_functions() -> None:
    """Builtins, cast() and macros are callable from expressions."""
    columns = {
        "a": {"type": "string", "expr": "pad(value, 5, fill='0')"},
        "b": {"type": "decimal(10,2)", "expr": "cast(value, 'decimal(10,2)') * 2"},
        "c": {"type": "decimal(12,2)", "expr": "money(value, currency='€')"},
    }
    out = conform(columns, {"a": STRING, "b": STRING, "c": STRING},
                  {"a": "42", "b": "1.25", "c": "€3"}, macros=DESIGN_MACROS)  # fmt: skip
    assert out == [{"a": "00042", "b": "2.50", "c": "3.00"}]


def test_bad_function_arguments_follow_on_error() -> None:
    """Kwargs of a builtin called as a function are checked when it runs."""
    _, executor = plan_for({"a": {"type": "string", "expr": "pad(value, nope=1)"}}, {"a": STRING})
    with pytest.raises(ConformError, match="nope: unknown key"):
        executor.run({"a": "x"}, {}, 1)


# --- fields on nested values (12.6) ----------------------------------------------------------


def test_fields_mask_json_members() -> None:
    """Nested json members are transformed, dropped or guarded, and the source is untouched."""
    columns = {
        "doc": {
            "type": "json",
            "fields": {
                "address.zip": {"transform": {"mask": {"keep_first": 2}}},
                "items[*].sku": {"transform": "upper", "when": "value != 'keep'"},
                "secret": {"drop": True},
                "missing.path": {"transform": "upper"},
            },
        }
    }
    source = {
        "address": {"zip": "12345", "city": "X"},
        "items": [{"sku": "ab"}, {"sku": "keep"}],
        "secret": "s",
    }
    record = {"doc": source}
    out = conform(columns, {"doc": OBJECT}, record)
    assert out == [
        {"doc": '{"address": {"zip": "12***", "city": "X"}, "items": [{"sku": "AB"}, '
                '{"sku": "keep"}]}'}
    ]  # fmt: skip
    assert source["secret"] == "s"  # noqa: S105 -- test data
    assert source["address"] == {"zip": "12345", "city": "X"}


def test_fields_on_struct_members_keep_the_type() -> None:
    """A struct member's chain starts and ends at its declared type."""
    columns = {
        "who": {
            "type": "struct<name: string, age: int32>",
            "fields": {"name": {"transform": {"hash": {"algo": "md5"}}}},
        }
    }
    out = conform(columns, {"who": OBJECT}, {"who": {"name": "a", "age": 3}})
    assert out == [{"who": {"name": "0cc175b9c0f1b6a831c399e269772661", "age": 3}}]


@pytest.mark.parametrize(
    ("column", "message"),
    [
        (
            {"type": "struct<a: int32>", "fields": {"b": {"transform": "upper"}}},
            "'b' is not a member of struct<a: int32>",
        ),
        (
            {"type": "struct<a: int32>", "fields": {"a": {"transform": {"hash": {}}}}},
            "the member is int32, but its chain ends as",
        ),
        ({"type": "json", "fields": {"a..b": {"drop": True}}}, "a member path is names"),
        (
            {"type": "struct<a: int32>", "fields": {"a": {"drop": True}}},
            "drop works on json members",
        ),
    ],
)
def test_fields_problems(column: dict[str, Any], message: str) -> None:
    """Bad member paths and type changes are compile errors."""
    found = problems({"c": column}, {"c": OBJECT})
    assert any(message in f for f in found), found
