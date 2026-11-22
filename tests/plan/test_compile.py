"""Plan compilation at SCHEMA time (WBS 5.7)."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pyarrow as pa
import pytest

from map_conform.plan.compile import StreamPlan, compile_stream
from map_conform.spec.errors import SpecError
from map_conform.spec.load import resolve_stream
from map_conform.spec.model import parse_spec
from map_conform.transforms.builtins import builtin_registry
from tests.fixtures.paths import FIXTURES

ORDERS = json.loads((FIXTURES / "catalogs" / "orders_export.catalog.json").read_text())["streams"][
    0
]
TYPED = json.loads((FIXTURES / "catalogs" / "typed.catalog.json").read_text())["streams"][0]


def compile_plan(
    streams: dict[str, Any], entry: dict[str, Any] = ORDERS, **kwargs: Any
) -> StreamPlan:
    """Compile one catalog stream under a spec."""
    spec = parse_spec({"version": 1, **streams})
    resolved = resolve_stream(spec, entry["stream"])
    assert resolved is not None
    return compile_stream(
        spec,
        resolved,
        entry["schema"],
        builtin_registry(),
        key_properties=tuple(entry["key_properties"]),
        **kwargs,
    )


def problems(streams: dict[str, Any], entry: dict[str, Any] = ORDERS, **kwargs: Any) -> list[str]:
    """The problems a compile reports."""
    with pytest.raises(SpecError) as caught:
        compile_plan(streams, entry, **kwargs)
    return [str(i) for i in caught.value.issues]


SPEC = {
    "defaults": {"stream": {"prefix": "raw_"}},
    "streams": {
        "Orders Export": {
            "columns": {
                "Order ID": {
                    "name": "order_id",
                    "type": "int64",
                    "nullable": False,
                    "doc": "The order",
                },
                "Amount ($)": {
                    "type": "decimal(12,2)",
                    "transform": [{"strip_chars": "$, "}],
                    "parse": {"parens_negative": True},
                },
                "Paid?": {"type": "boolean", "on_error": "null"},
                "Notes": {"drop": True},
                "Customer Name": {"default": "unknown", "sql_type": "varchar(200)"},
                "SKU": {"enum": ["SKU-1", "SKU-2"]},
            }
        }
    },
}


def test_plan_for_the_orders_export() -> None:
    """Names, types, steps, keys and schemas of a declared-plus-undeclared stream."""
    plan = compile_plan(SPEC)
    assert plan.name == "raw_orders_export"
    columns = {c.name: c for c in plan.columns}
    assert "notes" not in columns
    assert [c.name for c in plan.columns][:3] == ["order_id", "order_date", "customer_id"]
    assert str(columns["amount"].ctype) == "decimal(12,2)"
    assert columns["amount"].steps == ("strip_chars", "cast: decimal(12,2)")
    assert columns["order_date"].declared is False
    assert str(columns["order_date"].ctype) == "string"
    assert columns["paid"].on_error == "null"
    assert columns["customer_name"].default == "unknown"
    assert columns["sku"].enum == frozenset({"SKU-1", "SKU-2"})
    assert plan.key_properties == ("order_id",)
    assert plan.schema["properties"]["order_id"] == {
        "type": "integer",
        "minimum": -(2**63),
        "maximum": 2**63 - 1,
        "x-sql-datatype": "bigint",
        "description": "The order",
    }
    assert plan.schema["properties"]["amount"]["format"] == "x-singer.decimal"
    assert plan.schema["properties"]["customer_name"]["x-sql-datatype"] == "varchar(200)"
    assert plan.arrow_schema.field("order_id").type == pa.int64()
    assert not plan.arrow_schema.field("order_id").nullable
    assert plan.arrow_schema.field("amount").type == pa.decimal128(12, 2)
    assert "column 'Amount ($)' -> 'amount': dropped '$'" in plan.notes


def test_undeclared_columns_take_tap_types() -> None:
    """Every SCHEMA -> CType rule applies to undeclared columns; nested shapes conform."""
    plan = compile_plan({"defaults": {"nested": "keep"}}, TYPED)
    types = {c.name: str(c.ctype) for c in plan.columns}
    assert types["small_int"] == "int16"
    assert types["singer_decimal"] == "decimal(12,4)"
    assert types["instant"] == "timestamptz"
    assert types["address"] == "struct<street: string, zip: string>"
    assert types["mixed_any_of"] == "json"
    assert any("kept as json" in n for n in plan.notes)
    nullable = {c.name: c.nullable for c in plan.columns}
    assert nullable["nullable_any_of"] is True


def test_key_and_bookmark_properties_are_renamed() -> None:
    """Keys and bookmarks given as source names come out as output names."""
    plan = compile_plan(
        {"streams": {"Orders Export": {"key_properties": ["Order ID", "SKU"]}}},
        bookmark_properties=("Created At (UTC)",),
    )
    assert plan.key_properties == ("order_id", "sku")
    assert plan.bookmark_properties == ("created_at_utc",)


@pytest.mark.parametrize(
    ("columns", "message"),
    [
        (
            {"Order ID": {"type": "int64", "on_error": "keep"}},
            'columns["Order ID"].on_error: keep would put raw text in a int64 column',
        ),
        (
            {"Order ID": {"transform": "set_null", "nullable": False}},
            'columns["Order ID"].nullable: set_null makes the column nullable',
        ),
        (
            {"Order ID": {"type": "int64", "default": "abc"}},
            "columns[\"Order ID\"].default: 'abc' does not pass the column's chain: cast: int64:",
        ),
        (
            {"Order ID": {"type": "int64", "enum": [1, "two"]}},
            "columns[\"Order ID\"].enum: 'two' does not pass the column's chain",
        ),
        (
            {"Order ID": {"expr": "nope + 1"}},
            "columns[\"Order ID\"].expr: unknown name 'nope'",
        ),
        (
            {"Order ID": {"when": "x"}},
            "columns[\"Order ID\"].when: unknown name 'x'",
        ),
        (
            {"Order ID": {"type": "string", "fields": {"a": {"drop": True}}}},
            'columns["Order ID"].fields: fields needs a struct or json column, not string',
        ),
        (
            {"total": {"source": ["SKU", "Qty."]}},
            "columns.total: declare its type: the tap SCHEMA has no single source property",
        ),
    ],
)
def test_compile_problems(columns: dict[str, Any], message: str) -> None:
    """Each plan problem is reported at its path."""
    found = problems({"streams": {"Orders Export": {"columns": columns}}})
    assert any(message in f for f in found), found


def test_filter_and_unknown_key_property() -> None:
    """A filter with an unknown name and an unknown key property are both reported."""
    found = problems({"streams": {"Orders Export": {"filter": "x", "key_properties": ["nope"]}}})
    assert any("streams[\"Orders Export\"].filter: unknown name 'x'" in f for f in found)
    assert any(
        "key_properties: 'nope' is neither a source nor an output column" in f for f in found
    )


def test_strict_makes_undeclared_columns_errors() -> None:
    """Strict overrides undeclared to error."""
    found = problems(
        {"streams": {"Orders Export": {"columns": {"Order ID": {"type": "int64"}}}}}, strict=True
    )
    assert len([f for f in found if "(undeclared: error)" in f]) == 13  # noqa: PLR2004


def test_coalesced_sources_with_a_declared_type() -> None:
    """A list of sources coalesces; with a type it compiles."""
    plan = compile_plan(
        {
            "streams": {
                "Orders Export": {
                    "columns": {
                        "ship_or_order": {"source": ["Ship Date", "Order Date"], "type": "string"}
                    }
                }
            }
        }
    )
    column = next(c for c in plan.columns if c.name == "ship_or_order")
    assert column.sources == ("Ship Date", "Order Date")


def test_decimal_default_is_typed() -> None:
    """A default is cast through the column's chain once, at compile time."""
    plan = compile_plan(
        {
            "streams": {
                "Orders Export": {
                    "columns": {"Amount ($)": {"type": "decimal(12,2)", "default": "0"}}
                }
            }
        }
    )
    amount = next(c for c in plan.columns if c.name == "amount")
    assert amount.default == Decimal("0.00")
