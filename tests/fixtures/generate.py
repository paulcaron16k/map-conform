"""Regenerate the derived fixtures from the source data defined here.

Run from the repository root::

    uv run python -m tests.fixtures.generate

The hand-authored case tables in ``corpus/`` are not generated. ``test_fixtures.py``
regenerates into a temporary directory and fails when a committed file is stale.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import sys
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
MANIFEST_DIR_PLACEHOLDER = "{FIXTURES}"
"""Stands for this directory in BATCH manifests; ``paths.messages`` resolves it."""

TIME_EXTRACTED = "2026-03-14T12:00:00.000000+00:00"
TABLE_VERSION = 1773489600000

# --- A spreadsheet exported to CSV -----------------------------------------------------------
# Written with a UTF-8 BOM and CRLF line endings, as spreadsheet tools do. Headers need
# conforming; every column needs value cleanup.

ORDERS_STREAM = "Orders Export"
ORDERS_HEADER = [
    "Order ID",
    "Order Date",
    "customerID",
    "Customer Name",
    "Amount ($)",
    "Discount %",
    "Paid?",
    "Ship Date",
    "Notes",
    "SKU",
    "Qty.",
    "Unit Price (€)",
    "Created At (UTC)",
    "Tracking UUID",
]
# fmt: off
ORDERS_ROWS = [
    ["1001", "03/14/2026", "C-001", "  Ada Lovelace ", "$1,234.50", "10%", "Yes", "46097",
     "Rush, gift wrap", "SKU-1", "2", "617.25", "2026-03-14T09:26:53Z",
     "123e4567-e89b-12d3-a456-426614174000"],
    ["1002", "2026-03-15", "C-002", "Grace Hopper", "(250.00)", "0%", "no", "",
     "Refund", "SKU-2", "1", "250", "2026-03-15 10:00:00",
     "{F47AC10B-58CC-4372-A567-0E02B2C3D479}"],
    ["1003", "46096", "C-003", "Zoë Ünal", "USD 99.9", "N/A", "TRUE", "03/20/2026",
     "Line one\nLine two", "SKU-3", "1,000", "0.0999", "2026-03-15T23:59:59.5+02:00",
     "f47ac10b58cc4372a5670e02b2c3d479"],
    ["1004", "03/16/2026", "c-004", "Alan\u00a0Turing", "1,000", "12.5%", "y", "46100",
     "", "SKU-1", "3.0", "333.33", "2026-03-16T08:00:00z", ""],
    ["1005", "-", "C-005", "NULL", "-", "-", "-", "-", "-", "SKU-4", "-", "-", "-", "-"],
    ["1006", "#N/A", "C-006", "Katherine Johnson", "#N/A", "#N/A", "#N/A", "#N/A", "#N/A",
     "#N/A", "#N/A", "#N/A", "#N/A", "#N/A"],
    ["1007", "3/7/2026", "C-007", "Hedy Lamarr", " 15 ", "5 %", "off", "3/9/2026",
     "Leading and trailing spaces  ", "SKU-5", " 4 ", " 3.75 ", "2026-03-07 07:07:07",
     " 123E4567-E89B-12D3-A456-426614174000 "],
    ["1008", "03/18/2026", "C-008", "Barbara Liskov", "1.5e3", "0", "0", "03/18/2026",
     "Exponent amount", "SKU-6", "1", "1500", "2026-03-18T12:00:00+00:00",
     "7c9e6679-7425-40de-944b-e07fc1f90ae7"],
    ["1009", "03/19/2026", "C-009", "Margaret Hamilton", "1234.50-", "", "1", "",
     "Trailing minus", "SKU-7", "-1", "1234.50", "2026-03-19T09:00:00-05:00",
     "N/A"],
    ["1010", "03/20/2026", "C-010", "Radia Perlman", "abc", "ten", "maybe", "next week",
     "Uncleanable values", "SKU-8", "two", "free", "yesterday", "not-a-uuid"],
    ["1011", "2026-03-21", "C-011", "Frances Allen", "£12", "100%", "No", "2026-03-22",
     "Pound amount", "SKU-9", "12", "1", "2026-03-21T00:00:00Z",
     "3f2504e0-4f89-11d3-9a0c-0305e82c3301"],
    ["1012", "03/22/2026", "C-012", "Shafi Goldwasser", "$0.10", "0.5%", "t", "46104",
     "Ten cents", "SKU-10", "1", "0.10", "2026-03-22T18:30:00.123456Z",
     "a8098c1a-f86e-11da-bd1a-00112444be1e"],
]

# --- Records as a spreadsheet (XLSX) tap emits them --------------------------------------------
# Numbers arrive as floats (3.0), date cells either as ISO text or as raw serials, float
# artefacts survive, and error cells arrive as text.

INVENTORY_STREAM = "Inventory - Sheet1"
INVENTORY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "SKU": {"type": ["string", "null"]},
        "On Hand": {"type": ["number", "null"]},
        "Last Counted": {"type": ["string", "null"], "format": "date-time"},
        "Received (serial)": {"type": ["number", "null"]},
        "Price": {"type": ["number", "null"]},
        "Margin": {"type": ["number", "null"]},
        "Active": {"type": ["boolean", "null"]},
        "Weight (kg)": {"type": ["number", "string", "null"]},
        "Supplier": {"type": ["string", "null"]},
        "Big Count": {"type": ["number", "null"]},
    },
}
INVENTORY_ROWS: list[dict[str, Any]] = [
    {"SKU": "SKU-1", "On Hand": 3.0, "Last Counted": "2026-03-14T00:00:00",
     "Received (serial)": 46095.0, "Price": 19.99, "Margin": 0.30000000000000004,
     "Active": True, "Weight (kg)": 1.25, "Supplier": "Supplier A", "Big Count": 100000.0},
    {"SKU": "SKU-2", "On Hand": 0.0, "Last Counted": "2026-03-13T00:00:00",
     "Received (serial)": 46094.25, "Price": 5.0, "Margin": 0.1, "Active": False,
     "Weight (kg)": "n/a", "Supplier": "#N/A", "Big Count": 1.0e15},
    {"SKU": "SKU-3", "On Hand": 12.0, "Last Counted": None, "Received (serial)": None,
     "Price": 0.07, "Margin": -0.05, "Active": None, "Weight (kg)": 0.5,
     "Supplier": "  Supplier B  ", "Big Count": None},
    {"SKU": "SKU-4", "On Hand": 7.5, "Last Counted": "2026-03-12T00:00:00",
     "Received (serial)": 46093.0, "Price": 1234.5, "Margin": 0.333333333333,
     "Active": True, "Weight (kg)": None, "Supplier": "", "Big Count": 42.0},
]
# fmt: on

# --- A typed tap catalog, covering every SCHEMA → CType rule (design §4) -----------------------

TYPED_STREAM = "Typed Source"
# fmt: off
TYPED_PROPERTIES: dict[str, tuple[dict[str, Any], str]] = {
    # name: (JSON Schema, expected CType with the defaults, nested: json)
    "small_int": ({"type": ["integer", "null"], "minimum": -32768, "maximum": 32767}, "int16"),
    "medium_int": (
        {"type": ["integer", "null"], "minimum": -2147483648, "maximum": 2147483647},
        "int32",
    ),
    "plain_int": ({"type": ["integer", "null"]}, "int64"),
    "plain_number": ({"type": ["number", "null"]}, "float64"),
    "number_with_scale": ({"type": ["number", "null"], "precision": 10, "scale": 2},
                          "decimal(10,2)"),
    "singer_decimal": (
        {"type": ["string", "null"], "format": "x-singer.decimal", "precision": 12, "scale": 4},
        "decimal(12,4)",
    ),
    "plain_string": ({"type": ["string", "null"]}, "string"),
    "bounded_string": ({"type": ["string", "null"], "maxLength": 40}, "string(40)"),
    "flag": ({"type": ["boolean", "null"]}, "boolean"),
    "day": ({"type": ["string", "null"], "format": "date"}, "date"),
    "clock": ({"type": ["string", "null"], "format": "time"}, "time"),
    "instant": ({"type": ["string", "null"], "format": "date-time"}, "timestamptz"),
    "ident": ({"type": ["string", "null"], "format": "uuid"}, "uuid"),
    "blob": ({"type": ["string", "null"], "contentEncoding": "base64"}, "binary"),
    "hinted": ({"type": ["string", "null"], "x-sql-datatype": "smallint"}, "int16"),
    "address": (
        {
            "type": ["object", "null"],
            "properties": {"street": {"type": ["string", "null"]},
                           "zip": {"type": ["string", "null"]}},
        },
        "json",
    ),
    "tags": ({"type": ["array", "null"], "items": {"type": "string"}}, "json"),
    "nullable_any_of": ({"anyOf": [{"type": "null"}, {"type": "integer"}]}, "int64"),
    "same_any_of": ({"anyOf": [{"type": "string", "maxLength": 5}, {"type": "string"}]},
                    "string"),
    "mixed_any_of": ({"anyOf": [{"type": "integer"}, {"type": "string"}]}, "json"),
    "multi_type": ({"type": ["integer", "string", "null"]}, "json"),
    "untyped": ({}, "json"),
}
# fmt: on
TYPED_EXPECTED_WITH_KEEP = {
    "address": "struct<street: string, zip: string>",
    "tags": "list<string>",
}


def _json_line(message: dict[str, Any]) -> str:
    return json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"


def _schema_message(stream: str, schema: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {"type": "SCHEMA", "stream": stream, "schema": schema, "key_properties": keys}


def _record(stream: str, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "RECORD",
        "stream": stream,
        "record": record,
        "version": TABLE_VERSION,
        "time_extracted": TIME_EXTRACTED,
    }


def _state(stream: str) -> dict[str, Any]:
    return {"type": "STATE", "value": {"bookmarks": {stream: {}}}}


def _catalog_entry(stream: str, schema: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    metadata: list[dict[str, Any]] = [
        {
            "breadcrumb": [],
            "metadata": {"inclusion": "available", "selected": True, "table-key-properties": keys},
        },
    ]
    metadata += [
        {
            "breadcrumb": ["properties", name],
            "metadata": {"inclusion": "automatic" if name in keys else "available"},
        }
        for name in schema["properties"]
    ]
    return {
        "tap_stream_id": stream,
        "stream": stream,
        "schema": schema,
        "key_properties": keys,
        "metadata": metadata,
    }


def _orders_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {name: {"type": ["string", "null"]} for name in ORDERS_HEADER},
    }


def _orders_records() -> list[dict[str, str]]:
    return [dict(zip(ORDERS_HEADER, row, strict=True)) for row in ORDERS_ROWS]


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _write_parquet(path: Path, table: pa.Table) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd")


def _write_jsonl_gz(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    # mtime=0 and no file name keep the bytes reproducible.
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as gz:
        gz.write("".join(_json_line(r) for r in rows).encode("utf-8"))
    path.write_bytes(buffer.getvalue())


def _batch(stream: str, fmt: str, compression: str, files: list[str]) -> dict[str, Any]:
    return {
        "type": "BATCH",
        "stream": stream,
        "encoding": {"format": fmt, "compression": compression},
        "manifest": [f"file://{MANIFEST_DIR_PLACEHOLDER}/batch/{name}" for name in files],
        "version": TABLE_VERSION,
        "time_extracted": TIME_EXTRACTED,
    }


def generate(out: Path) -> list[Path]:
    """Write every derived fixture under ``out``; return the paths written."""
    written: list[Path] = []

    def text(rel: str, content: str) -> None:
        _write_text(out / rel, content)
        written.append(out / rel)

    # Sources.
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\r\n").writerows([ORDERS_HEADER, *ORDERS_ROWS])
    text("sources/orders_export.csv", "﻿" + buffer.getvalue())

    # Singer RECORD streams.
    orders = _orders_records()
    text(
        "streams/orders_export.singer.jsonl",
        "".join(
            _json_line(m)
            for m in [
                _schema_message(ORDERS_STREAM, _orders_schema(), ["Order ID"]),
                *(_record(ORDERS_STREAM, r) for r in orders),
                _state(ORDERS_STREAM),
            ]
        ),
    )
    text(
        "streams/inventory_xlsx.singer.jsonl",
        "".join(
            _json_line(m)
            for m in [
                _schema_message(INVENTORY_STREAM, INVENTORY_SCHEMA, ["SKU"]),
                *(_record(INVENTORY_STREAM, r) for r in INVENTORY_ROWS),
                _state(INVENTORY_STREAM),
            ]
        ),
    )

    # Catalogs.
    typed_schema = {
        "type": "object",
        "properties": {k: s for k, (s, _) in TYPED_PROPERTIES.items()},
    }
    catalogs = {
        "orders_export": _catalog_entry(ORDERS_STREAM, _orders_schema(), ["Order ID"]),
        "inventory_xlsx": _catalog_entry(INVENTORY_STREAM, INVENTORY_SCHEMA, ["SKU"]),
        "typed": _catalog_entry(TYPED_STREAM, typed_schema, ["plain_int"]),
    }
    for name, entry in catalogs.items():
        text(
            f"catalogs/{name}.catalog.json",
            json.dumps({"streams": [entry]}, ensure_ascii=False, indent=2) + "\n",
        )
    text(
        "catalogs/typed.expected.json",
        json.dumps(
            {
                "stream": TYPED_STREAM,
                "nested_json": {k: c for k, (_, c) in TYPED_PROPERTIES.items()},
                "nested_keep_overrides": TYPED_EXPECTED_WITH_KEEP,
            },
            indent=2,
        )
        + "\n",
    )

    # BATCH files: what an SDK tap writes, in source column names and source types.
    halves = {"0001": orders[:6], "0002": orders[6:]}
    orders_arrow = pa.schema([(name, pa.string()) for name in ORDERS_HEADER])
    for part, rows in halves.items():
        rel = f"batch/orders_export-{part}.parquet"
        _write_parquet(out / rel, pa.Table.from_pylist(rows, schema=orders_arrow))
        written.append(out / rel)
    _write_jsonl_gz(out / "batch/orders_export-0001.jsonl.gz", halves["0001"])
    written.append(out / "batch/orders_export-0001.jsonl.gz")

    inventory_fields: list[pa.Field[Any]] = [
        pa.field("SKU", pa.string()),
        pa.field("On Hand", pa.float64()),
        pa.field("Last Counted", pa.string()),
        pa.field("Received (serial)", pa.float64()),
        pa.field("Price", pa.float64()),
        pa.field("Margin", pa.float64()),
        pa.field("Active", pa.bool_()),
        pa.field("Weight (kg)", pa.string()),  # mixed number/text cells: Arrow needs one type
        pa.field("Supplier", pa.string()),
        pa.field("Big Count", pa.float64()),
    ]
    inventory_arrow = pa.schema(inventory_fields)
    inventory_rows = [
        {**r, "Weight (kg)": None if r["Weight (kg)"] is None else str(r["Weight (kg)"])}
        for r in INVENTORY_ROWS
    ]
    _write_parquet(
        out / "batch/inventory_xlsx-0001.parquet",
        pa.Table.from_pylist(inventory_rows, schema=inventory_arrow),
    )
    written.append(out / "batch/inventory_xlsx-0001.parquet")

    # BATCH message streams; manifests use MANIFEST_DIR_PLACEHOLDER for this directory.
    text(
        "streams/orders_export.batch-parquet.singer.jsonl",
        "".join(
            _json_line(m)
            for m in [
                _schema_message(ORDERS_STREAM, _orders_schema(), ["Order ID"]),
                _batch(
                    ORDERS_STREAM,
                    "parquet",
                    "zstd",
                    ["orders_export-0001.parquet", "orders_export-0002.parquet"],
                ),
                _state(ORDERS_STREAM),
            ]
        ),
    )
    text(
        "streams/orders_export.batch-jsonl.singer.jsonl",
        "".join(
            _json_line(m)
            for m in [
                _schema_message(ORDERS_STREAM, _orders_schema(), ["Order ID"]),
                _batch(ORDERS_STREAM, "jsonl", "gzip", ["orders_export-0001.jsonl.gz"]),
                _state(ORDERS_STREAM),
            ]
        ),
    )
    text(
        "streams/inventory_xlsx.batch-parquet.singer.jsonl",
        "".join(
            _json_line(m)
            for m in [
                _schema_message(INVENTORY_STREAM, INVENTORY_SCHEMA, ["SKU"]),
                _batch(INVENTORY_STREAM, "parquet", "zstd", ["inventory_xlsx-0001.parquet"]),
                _state(INVENTORY_STREAM),
            ]
        ),
    )
    return written


def main() -> int:
    """Regenerate the derived fixtures in place."""
    for path in generate(HERE):
        sys.stdout.write(f"wrote {path.relative_to(HERE)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
