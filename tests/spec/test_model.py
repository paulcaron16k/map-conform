"""The spec model parses strictly, reports every problem with its path, and round-trips."""

from __future__ import annotations

import dataclasses
import json
from typing import Any, cast

import pytest

from map_conform.spec._struct import dump
from map_conform.spec.errors import SpecError
from map_conform.spec.model import ColumnSpec, Defaults, Spec, parse_spec
from map_conform.spec.steps import CallStep, CaseStep, Chain, ExprStep, Macro

FULL: dict[str, Any] = {
    "version": 1,
    "defaults": {
        "naming": {"reserved_dialects": ["ansi"]},
        "values": {"null_tokens": ["", "NULL", "-"]},
        "timestamp": {"assume_tz": "America/New_York", "formats": ["%m/%d/%Y", "iso"]},
        "on_error": "reject",
        "faker": {"seed": 7, "locale": ["en_US", "fr_FR"]},
    },
    "macros": {
        "money": [{"strip_chars": "$€£, "}, {"parens_negative": True}, {"cast": "decimal"}],
        "sheet_date": {
            "params": {"tz": "UTC"},
            "steps": {"cast": "timestamptz", "formats": ["excel_serial", "iso"], "tz": "${tz}"},
            "doc": "Spreadsheet dates",
        },
    },
    "udfs": {"fiscal_week": "my_pkg.udfs:fiscal_week"},
    "streams": {
        "sheets-*": {"prefix": "raw_sheets_", "naming": {"case": "lower"}},
        "orders": {
            "alias": "raw_shop_orders",
            "key_properties": ["order_id"],
            "filter": "status != 'TEST'",
            "columns": {
                "Order ID": {"name": "order_id", "type": "int64", "nullable": False},
                "Total": {"type": "decimal(18,2)", "transform": "money"},
                "Order Date": {
                    "type": "timestamptz",
                    "parse": {"formats": ["%m/%d/%Y %I:%M %p", "excel_serial", "iso"]},
                },
                "Shipped?": {"type": "boolean", "true_values": ["Y", "yes", "shipped"]},
                "SSN": {"drop": True},
                "Email": {"transform": {"hash": {}, "when": "country == 'DE'"}},
                "week": {"type": "int32", "expr": "fiscal_week(order_date)"},
                "Customer": {
                    "type": "json",
                    "fields": {"address.zip": {"transform": {"mask": {"keep_last": 2}}}},
                },
                "Amount": {
                    "type": "decimal(12,2)",
                    "transform": {
                        "case": [
                            {"when": "is_number(value)", "then": {"cast": "decimal"}},
                            {"when": "is_string(value)", "then": ["money"]},
                            {"else": {"on_error": "reject"}},
                        ]
                    },
                },
                "Code": {"source": ["code_a", "code_b"], "default": "n/a", "enum": ["A", "B"]},
            },
        },
        "orders_eu": {"source": "orders", "alias": {"expr": "'orders_' + region"}},
    },
    "else": "drop",
}


def problems(data: object) -> list[str]:
    """Every problem parse_spec reports, as ``path: message`` strings."""
    with pytest.raises(SpecError) as caught:
        parse_spec(data)
    return [str(i) for i in caught.value.issues]


def test_full_spec_round_trips() -> None:
    """Parsing then dumping gives back what was written (values equal to defaults are omitted)."""
    spec = parse_spec(FULL)
    assert dump(spec) == FULL
    assert parse_spec(json.loads(json.dumps(dump(spec)))) == spec


def test_minimal_spec_takes_every_default() -> None:
    """Only version is required; defaults match the design's §3.2 values."""
    spec = parse_spec({"version": 1})
    assert spec.defaults == Defaults()
    assert spec.defaults.naming.max_length == 63  # noqa: PLR2004 -- the documented default
    assert spec.defaults.values.null_tokens[:3] == ("", "NULL", "null")
    assert spec.defaults.on_error == "raise"
    assert spec.else_ == "keep"
    assert dump(spec) == {"version": 1}


def test_spec_is_immutable() -> None:
    """Instances are frozen and their mappings and lists cannot be changed."""
    spec = parse_spec(FULL)
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.__setattr__("version", 1)
    with pytest.raises(TypeError):
        cast("dict[str, Any]", spec.streams)["new"] = spec.streams["orders"]
    assert isinstance(spec.defaults.timestamp.formats, tuple)


def test_steps_parse_into_their_forms() -> None:
    """Bare names, first-key calls with kwargs, when, expr, case and macro forms."""
    spec = parse_spec(FULL)
    money = spec.macros["money"]
    assert money == Macro(Chain((
        CallStep("strip_chars", "$€£, "),
        CallStep("parens_negative", arg=True),
        CallStep("cast", "decimal"),
    )))  # fmt: skip
    sheet_date = spec.macros["sheet_date"]
    assert sheet_date.params == {"tz": "UTC"}
    (cast,) = sheet_date.steps.steps
    assert isinstance(cast, CallStep)
    assert cast.arg == "timestamptz"
    assert dict(cast.kwargs) == {"formats": ("excel_serial", "iso"), "tz": "${tz}"}
    columns = spec.streams["orders"].spec.columns
    email = columns["Email"].transform
    assert email == Chain((CallStep("hash", {}, when="country == 'DE'"),))
    amount = columns["Amount"].transform
    assert amount is not None
    (case,) = amount.steps
    assert isinstance(case, CaseStep)
    assert [b.when for b in case.branches] == ["is_number(value)", "is_string(value)"]
    assert case.otherwise == Chain((CallStep("on_error", "reject"),))
    expr = parse_spec({"version": 1, "macros": {"m": {"expr": "value * 2", "when": "x"}}})
    assert expr.macros["m"].steps.steps == (ExprStep("value * 2", when="x"),)


def test_stream_rules_keep_raw_and_parsed_forms() -> None:
    """A stream entry exposes its StreamSpec and its raw mapping for inheritance."""
    rules = parse_spec(FULL).streams["sheets-*"]
    assert rules.spec.prefix == "raw_sheets_"
    assert dict(rules.raw) == {"prefix": "raw_sheets_", "naming": {"case": "lower"}}


def test_every_problem_is_reported_with_its_path() -> None:
    """One pass reports all problems, at every level, not just the first."""
    bad = {
        "version": 2,
        "extra": True,
        "defaults": {"naming": {"case": "camel", "bogus": 1}, "on_error": "ignore"},
        "macros": {"m": {"steps": [], "params": []}},
        "udfs": {"f": "not a path"},
        "streams": {
            "orders": {
                "what": 1,
                "values": {"trim": "yes"},
                "columns": {
                    "Order ID": {"type": "decimel", "nullable": "no"},
                    "a.b": {"transform": [{"case": [{"else": "x"}, {"when": "y", "then": "z"}]}]},
                    "c": {"transform": [{"expr": 3}, "case", {"when": "only"}]},
                },
            }
        },
        "else": None,
    }
    assert problems(bad) == [
        "extra: unknown key; allowed here: defaults, else, macros, streams, udfs, version",
        "version: expected one of 1, got 2",
        (
            "defaults.naming.bogus: unknown key; allowed here: ascii, case, collapse, "
            "leading_digit, max_length, nested, on_collision, replace_invalid, reserved_dialects, "
            "reserved_words, "
            "split_camel, truncate"
        ),
        "defaults.naming.case: expected one of 'snake', 'lower', 'upper', 'preserve', got 'camel'",
        "defaults.on_error: expected one of 'raise', 'null', 'keep', 'reject', got 'ignore'",
        "macros.m.steps: a chain needs at least one step",
        "macros.m.params: expected a mapping of parameter defaults",
        "udfs: expected 'package.module:function'",
        (
            "streams.orders.what: unknown key; allowed here: alias, boolean, columns, drop, faker, "
            "filter, flatten, key_properties, metadata, naming, nested, on_error, order, prefix, "
            "source, stream, timestamp, undeclared, values"
        ),
        (
            "streams.orders.columns[\"Order ID\"].type: unknown type 'decimel' at position 7 in "
            "'decimel'"
        ),
        'streams.orders.columns["Order ID"].nullable: expected a boolean, got a string',
        "streams.orders.columns[\"a.b\"].transform[0].case[0]: 'else' must be the last branch",
        "streams.orders.columns.c.transform[0].expr: expected an expression string",
        "streams.orders.columns.c.transform[1]: 'case' is not a step name",
        "streams.orders.columns.c.transform[2]: a step needs a name besides 'when'",
        "streams.orders.values.trim: expected a boolean, got a string",
        "else: expected one of 'keep', 'drop', got None",
    ]


@pytest.mark.parametrize(
    ("data", "problem"),
    [
        ({"version": True}, "version: expected one of 1, got True"),
        ({}, "version: required"),
        ([], "<root>: expected a mapping, got a list"),
        ({"version": 1, "defaults": {"naming": {"max_length": 0}}},
         "defaults.naming.max_length: must be at least 8"),
        ({"version": 1, "defaults": {"naming": {"max_length": 63.0}}},
         "defaults.naming.max_length: expected an integer, got a number"),
        ({"version": 1, "streams": {"s": {"columns": {"x": {"max_length": True}}}}},
         "streams.s.columns.x.max_length: expected an integer or null, got a boolean"),
        ({"version": 1, "streams": {"s": {"alias": 3}}},
         "streams.s.alias: expected a string or a mapping or null, got an integer"),
        ({"version": 1, "streams": {"s": {"alias": {"expr": "x", "exp": "y"}}}},
         "streams.s.alias.exp: unknown key; allowed here: expr"),
        ({"version": 1, "streams": {"s": []}}, "streams.s: expected a mapping of stream rules"),
        ({"version": 1, "streams": {"s": {"columns": {"x": {"transform": {}}}}}},
         "streams.s.columns.x.transform: a step is a name or a non-empty mapping"),
        ({"version": 1, "streams": {"s": {"columns": {"x": {"transform": {"case": []}}}}}},
         ("streams.s.columns.x.transform.case: expected a non-empty list of {when, then} and an "
         "optional {else}")),
        ({"version": 1, "streams": {"s": {"columns": {"x": {"fields": {"a": {"type": "int"}}}}}}},
         "streams.s.columns.x.fields.a.type: unknown key; allowed here: drop, transform, when"),
    ],
)  # fmt: skip
def test_single_problems(data: object, problem: str) -> None:
    """Representative problems carry precise paths and messages."""
    assert problems(data) == [problem]


def test_error_message_lists_problems_and_source() -> None:
    """SpecError's message names the file and every problem."""
    with pytest.raises(
        SpecError, match=r"2 problem\(s\) in conform\.yml:\n  bogus: .*\n  version: required"
    ):
        parse_spec({"bogus": 1}, "conform.yml")


def test_column_defaults_mean_inherit() -> None:
    """Unset column overrides are None, so the stream's defaults apply at compile time."""
    column = ColumnSpec()
    assert column.trim is None
    assert column.on_error is None
    assert column.nullable is True


def test_spec_keys_use_spec_spelling() -> None:
    """The ``else_`` field is written ``else``."""
    assert parse_spec({"version": 1, "else": "drop"}).else_ == "drop"
    assert "else" in Spec.__dataclass_fields__["else_"].metadata["key"]
