"""Nested member names in struct shapes (WBS 3.5)."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from map_conform.naming.conform import NameConformer, NamingError
from map_conform.naming.nested import MemberNames, conform_ctype, conform_schema, rename_value
from map_conform.spec.model import NamingDefaults
from map_conform.types.canonical import parse_ctype


def conformer(**overrides: object) -> NameConformer:
    """A conformer with the defaults, optionally overridden."""
    return NameConformer(dataclasses.replace(NamingDefaults(), **overrides))  # type: ignore[arg-type]


ORDER = (
    "struct<customerID: string, Address: struct<ZipCode: string, streetName: string>, "
    "Items: list<struct<SKU: string, unitPrice: decimal(10,2)>>, select: boolean>"
)


@pytest.mark.parametrize(
    ("ctype", "expected"),
    [
        (ORDER, ("struct<customer_id: string, address: struct<zip_code: string, street_name: "
                "string>, items: list<struct<sku: string, unit_price: decimal(10,2)>>, select_: "
                "boolean>")),
        ("list<struct<userId: int64>>", "list<struct<user_id: int64>>"),
        ("struct<a: list<list<struct<HTTPCode: int32>>>>",
         "struct<a: list<list<struct<http_code: int32>>>>"),
        ("decimal(10,2)", "decimal(10,2)"),
        ("list<string>", "list<string>"),
    ],
)  # fmt: skip
def test_nested_golden_ctypes(ctype: str, expected: str) -> None:
    """Struct members conform at every depth, through lists."""
    conformed, _ = conform_ctype(parse_ctype(ctype), conformer())
    assert str(conformed) == expected


def test_name_tree_and_value_renaming() -> None:
    """The name tree renames record values, including inside lists of structs."""
    _, names = conform_ctype(parse_ctype(ORDER), conformer())
    assert names is not None
    value = {
        "customerID": "C-1",
        "Address": {"ZipCode": "02139", "streetName": "Main"},
        "Items": [{"SKU": "A", "unitPrice": "1.50"}, {"SKU": "B", "unitPrice": "2.00"}],
        "select": True,
        "extra": 1,
    }
    assert rename_value(value, names) == {
        "customer_id": "C-1",
        "address": {"zip_code": "02139", "street_name": "Main"},
        "items": [{"sku": "A", "unit_price": "1.50"}, {"sku": "B", "unit_price": "2.00"}],
        "select_": True,
        "extra": 1,
    }


def test_tap_schema_objects() -> None:
    """JSON Schema properties (any spelling) and required lists are conformed."""
    schema: dict[str, Any] = {
        "type": ["object", "null"],
        "properties": {
            "Zip Code": {"type": "string"},
            "Lines": {
                "type": "array",
                "items": {"type": "object", "properties": {"Unit Price ($)": {"type": "number"}}},
            },
        },
        "required": ["Zip Code"],
        "additionalProperties": False,
    }
    conformed, names = conform_schema(schema, conformer())
    assert conformed == {
        "type": ["object", "null"],
        "properties": {
            "zip_code": {"type": "string"},
            "lines": {
                "type": "array",
                "items": {"type": "object", "properties": {"unit_price": {"type": "number"}}},
            },
        },
        "required": ["zip_code"],
        "additionalProperties": False,
    }
    assert names == MemberNames(
        {"Zip Code": "zip_code", "Lines": "lines"},
        {"Lines": MemberNames({"Unit Price ($)": "unit_price"}, {})},
    )
    assert schema["properties"]["Zip Code"] == {"type": "string"}  # input untouched


def test_nested_off_leaves_shapes_alone() -> None:
    """naming.nested: false keeps member names."""
    ctype = parse_ctype(ORDER)
    assert conform_ctype(ctype, conformer(nested=False)) == (ctype, None)
    schema = {"type": "object", "properties": {"Zip Code": {}}}
    assert conform_schema(schema, conformer(nested=False)) == (schema, None)


def test_collisions_are_checked_per_struct() -> None:
    """Two members of one struct conforming alike follow on_collision."""
    ctype = parse_ctype("struct<userId: int64, user_id: int64>")
    with pytest.raises(NamingError, match="on_collision: error"):
        conform_ctype(ctype, conformer())
    fixed, _ = conform_ctype(ctype, conformer(on_collision="suffix"))
    assert str(fixed) == "struct<user_id: int64, user_id_2: int64>"
    same_name_in_two_structs = parse_ctype("struct<a: struct<id: int64>, b: struct<id: int64>>")
    assert conform_ctype(same_name_in_two_structs, conformer())[0] == same_name_in_two_structs
