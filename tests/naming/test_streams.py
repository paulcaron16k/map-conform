"""Stream naming: conform, prefix, alias, split (WBS 3.4)."""

from __future__ import annotations

from typing import Any

import pytest

from map_conform.naming.conform import NamingError
from map_conform.naming.streams import stream_name
from map_conform.spec.load import output_streams, resolve_stream
from map_conform.spec.model import parse_spec


def name_of(spec: dict[str, Any], tap_stream: str) -> str:
    """The output name of a tap stream under a spec."""
    resolved = resolve_stream(parse_spec({"version": 1, **spec}), tap_stream)
    assert resolved is not None
    return stream_name(resolved).name


def test_acceptance_example() -> None:
    """`sheets-Orders 2024` with prefix raw_ lands as raw_sheets_orders_2024."""
    assert name_of({"defaults": {"stream": {"prefix": "raw_"}}}, "sheets-Orders 2024") == (
        "raw_sheets_orders_2024"
    )


@pytest.mark.parametrize(
    ("spec", "tap_stream", "expected"),
    [
        ({}, "Customer Orders", "customer_orders"),
        ({}, "public-Customer", "public_customer"),
        ({"defaults": {"stream": {"split": "-"}}}, "public-Customer", "customer"),
        ({"defaults": {"stream": {"split": "-"}}}, "db-public-Customer", "customer"),
        ({"defaults": {"stream": {"split": "-"}}}, "Customer", "customer"),
        ({"defaults": {"stream": {"name": "preserve"}}}, "Customer Orders", "Customer Orders"),
        ({"defaults": {"stream": {"name": "preserve", "prefix": "x_"}}}, "A b", "x_A b"),
        ({"streams": {"sheets-*": {"prefix": "raw_sheets_"}}}, "sheets-Orders",
         "raw_sheets_sheets_orders"),
        ({"streams": {"sheets-*": {"prefix": "raw_"}, "sheets-Orders": {"prefix": ""}}},
         "sheets-Orders", "sheets_orders"),
        ({"defaults": {"stream": {"prefix": "Raw-Data "}}}, "orders", "raw_data_orders"),
        ({"streams": {"orders": {"alias": "shop_orders"}}}, "orders", "shop_orders"),
        ({"streams": {"orders": {"alias": "shop_orders", "prefix": "raw_"}}}, "orders",
         "shop_orders"),
        ({"defaults": {"stream": {"name": "preserve"}},
          "streams": {"orders": {"alias": "Shop Orders"}}}, "orders", "Shop Orders"),
        ({}, "select", "select_"),
    ],
)  # fmt: skip
def test_stream_names(spec: dict[str, Any], tap_stream: str, expected: str) -> None:
    """Each stream-naming rule, alone and combined."""
    assert name_of(spec, tap_stream) == expected


def test_prefixed_long_name_still_fits() -> None:
    """A prefix on a long name is truncated with the usual hash."""
    name = name_of(
        {"defaults": {"stream": {"prefix": "raw_"}, "naming": {"max_length": 20}}},
        "a very long stream name indeed",
    )
    assert len(name) <= 20  # noqa: PLR2004
    assert name.startswith("raw_a_very")


def test_source_stream_is_named_from_its_key() -> None:
    """A stream split off with source takes its key as the base name."""
    spec = parse_spec({
        "version": 1,
        "defaults": {"stream": {"prefix": "raw_"}},
        "streams": {"Orders EU": {"source": "orders"}},
    })  # fmt: skip
    assert [stream_name(o).name for o in output_streams(spec, "orders")] == [
        "raw_orders",
        "raw_orders_eu",
    ]


def test_illegal_alias_is_an_error() -> None:
    """An alias is checked, never silently conformed."""
    with pytest.raises(NamingError, match=r"alias 'Shop Orders' is not a legal name here; it "
                       r"would conform to 'shop_orders'"):  # fmt: skip
        name_of({"streams": {"orders": {"alias": "Shop Orders"}}}, "orders")


def test_expression_aliases() -> None:
    """An {expr} alias is evaluated with stream (or __stream_name__) as the tap stream."""
    assert name_of({"streams": {"orders": {"alias": {"expr": "'raw_' + stream"}}}}, "orders") == (
        "raw_orders"
    )
    preserve = {"defaults": {"stream": {"name": "preserve"}}}
    spec = {"streams": {"o*": {"alias": {"expr": "__stream_name__.upper() + '_v2'"}}}}
    assert name_of({**preserve, **spec}, "orders") == "ORDERS_v2"
    with pytest.raises(NamingError, match="would conform to 'orders_v2'"):
        name_of(spec, "orders")
    with pytest.raises(NamingError, match="gave 3, not a name"):
        name_of({"streams": {"orders": {"alias": {"expr": "1 + 2"}}}}, "orders")
    with pytest.raises(NamingError, match="alias expression 'nope': unknown name"):
        name_of({"streams": {"orders": {"alias": {"expr": "nope"}}}}, "orders")


def test_lossy_stream_names_carry_notes() -> None:
    """Notes from conforming the base name are kept."""
    resolved = resolve_stream(parse_spec({"version": 1}), "Umsatz € 2024")
    assert resolved is not None
    result = stream_name(resolved)
    assert result.name == "umsatz_2024"
    assert result.notes == ("dropped '€' (no transliteration)",)
