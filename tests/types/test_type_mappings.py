"""CType mappings: tap SCHEMA -> CType, CType -> contract JSON Schema, CType -> Arrow (E4)."""

from __future__ import annotations

import json
import os
from typing import Any

import pyarrow as pa
import pytest

from map_conform.types.canonical import CType, CTypeError, parse_ctype
from map_conform.types.from_jsonschema import from_jsonschema
from map_conform.types.to_arrow import to_arrow
from map_conform.types.to_jsonschema import to_jsonschema
from tests.fixtures.paths import FIXTURES

SNAPSHOT = FIXTURES.parent / "types" / "snapshots" / "to_jsonschema.json"

EVERY_TYPE = [
    "boolean", "int16", "int32", "int64", "float32", "float64", "decimal(18,2)",
    "decimal(50,10)", "string", "string(40)", "date", "time", "timestamp", "timestamptz",
    "uuid", "binary", "json", "list<string>", "struct<a: int64, b: list<decimal(10,2)>>",
]  # fmt: skip


def _typed() -> tuple[dict[str, Any], dict[str, Any]]:
    catalog = json.loads((FIXTURES / "catalogs" / "typed.catalog.json").read_text())
    expected = json.loads((FIXTURES / "catalogs" / "typed.expected.json").read_text())
    return catalog["streams"][0]["schema"]["properties"], expected


# --- 4.1 ------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", EVERY_TYPE)
def test_parse_print_round_trip(text: str) -> None:
    """Every CType prints in its canonical spelling and parses back to itself."""
    assert str(parse_ctype(text)) == text


def test_malformed_shapes_are_rejected() -> None:
    """A decimal without precision or a list without an item cannot be built."""
    with pytest.raises(CTypeError):
        CType("decimal")
    with pytest.raises(CTypeError):
        CType("list")
    with pytest.raises(CTypeError, match="is not a decimal"):
        _ = CType("int64").decimal_params


# --- 4.2 ------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(_typed()[0]))
def test_typed_catalog_with_nested_json(name: str) -> None:
    """Every SCHEMA -> CType rule, on the typed fixture catalog."""
    properties, expected = _typed()
    assert str(from_jsonschema(properties[name]).ctype) == expected["nested_json"][name]


@pytest.mark.parametrize("name", list(_typed()[1]["nested_keep_overrides"]))
def test_typed_catalog_with_nested_keep(name: str) -> None:
    """With nested: keep, typed objects and arrays become struct and list."""
    properties, expected = _typed()
    inferred = from_jsonschema(properties[name], nested="keep").ctype
    assert str(inferred) == expected["nested_keep_overrides"][name]


@pytest.mark.parametrize(
    ("schema", "ctype", "nullable", "warning"),
    [
        ({"type": "integer"}, "int64", False, None),
        ({"type": ["integer", "null"], "minimum": 0, "maximum": 100}, "int16", True, None),
        ({"type": "integer", "minimum": 0}, "int64", False, None),
        ({"type": "number", "multipleOf": 0.01}, "float64", False, None),
        ({"type": "string", "format": "x-singer.decimal"}, "decimal(38,9)", False, None),
        ({"type": "number", "precision": 12}, "decimal(12,0)", False, None),
        ({"type": "string", "format": "email"}, "string", False, None),
        ({"type": "string", "x-sql-datatype": "numeric(10,2)"}, "decimal(10,2)", False, None),
        ({"type": "string", "x-sql-datatype": "geography"}, "string", False,
         "ignored unrecognised x-sql-datatype 'geography'"),
        ({"anyOf": [{"type": "string", "format": "date-time"}, {"type": "null"}]},
         "timestamptz", True, None),
        ({"oneOf": [{"type": "integer"}, {"type": "number"}]}, "json", False,
         "anyOf/oneOf of different types: kept as json"),
        ({"type": ["string", "integer"]}, "json", False,
         "several types ['string', 'integer']: kept as json"),
        ({"type": "null"}, "json", True, None),
        ({}, "json", True, None),
        ({"type": "object"}, "json", False, None),
    ],
)  # fmt: skip
def test_sdk_style_schemas(
    schema: dict[str, Any], ctype: str, *, nullable: bool, warning: str | None
) -> None:
    """Representative tap schemas, with nullability and warnings."""
    inferred = from_jsonschema(schema)
    assert str(inferred.ctype) == ctype
    assert inferred.nullable is nullable
    assert inferred.warnings == ((warning,) if warning else ())


def test_untyped_object_stays_json_even_when_kept() -> None:
    """An object without properties, or an array without items, has no shape to keep."""
    assert str(from_jsonschema({"type": "object"}, nested="keep").ctype) == "json"
    assert str(from_jsonschema({"type": "array"}, nested="keep").ctype) == "json"


# --- 4.3 ------------------------------------------------------------------------------------


def _render_snapshot() -> str:
    snapshot = {text: to_jsonschema(parse_ctype(text)) for text in EVERY_TYPE}
    snapshot["int64 not null"] = to_jsonschema(CType("int64"), nullable=False)
    return json.dumps(snapshot, indent=2) + "\n"


def test_contract_json_schema_snapshot() -> None:
    """The contract SCHEMA for every type matches the committed snapshot."""
    rendered = _render_snapshot()
    if os.environ.get("UPDATE_SNAPSHOTS"):
        SNAPSHOT.write_text(rendered)
    assert SNAPSHOT.read_text() == rendered, "review, then run with UPDATE_SNAPSHOTS=1"


def test_decimals_are_x_singer_decimal_strings() -> None:
    """Decimals go on the wire as strings with format x-singer.decimal, precision and scale."""
    assert to_jsonschema(parse_ctype("decimal(18,2)")) == {
        "type": ["string", "null"],
        "format": "x-singer.decimal",
        "precision": 18,
        "scale": 2,
    }


@pytest.mark.parametrize("text", EVERY_TYPE)
def test_contract_schema_reads_back_to_the_same_type(text: str) -> None:
    """from_jsonschema(to_jsonschema(t)) == t: the contract is lossless for every CType."""
    ctype = parse_ctype(text)
    back = from_jsonschema(to_jsonschema(ctype), nested="keep")
    assert back.ctype == ctype
    assert back.nullable
    assert back.warnings == ()


# --- 4.4 ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "arrow"),
    [
        ("boolean", pa.bool_()),
        ("int16", pa.int16()),
        ("int32", pa.int32()),
        ("int64", pa.int64()),
        ("float32", pa.float32()),
        ("float64", pa.float64()),
        ("decimal(38,2)", pa.decimal128(38, 2)),
        ("decimal(39,2)", pa.decimal256(39, 2)),
        ("string", pa.string()),
        ("string(40)", pa.string()),
        ("date", pa.date32()),
        ("time", pa.time64("us")),
        ("timestamp", pa.timestamp("us")),
        ("timestamptz", pa.timestamp("us", tz="UTC")),
        ("uuid", pa.uuid()),
        ("binary", pa.binary()),
        ("json", pa.string()),
        ("list<int32>", pa.list_(pa.int32())),
        ("struct<a: uuid, b: list<date>>",
         pa.struct([pa.field("a", pa.uuid()), pa.field("b", pa.list_(pa.date32()))])),
    ],
)  # fmt: skip
def test_arrow_types(text: str, arrow: pa.DataType) -> None:
    """Each CType maps to its Arrow type."""
    assert to_arrow(parse_ctype(text)) == arrow


def test_uuid_as_string() -> None:
    """uuid_as: string gives plain strings, nested too."""
    assert to_arrow(parse_ctype("struct<id: uuid>"), uuid_as="string") == pa.struct(
        [pa.field("id", pa.string())]
    )
