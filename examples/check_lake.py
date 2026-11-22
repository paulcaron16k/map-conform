"""Check what the example run landed in the lake (run by CI after `meltano run load`)."""

from __future__ import annotations

from decimal import Decimal

import duckdb

LANDED = 11
"""12 rows in the CSV; one is rejected, since its amount is 'abc'."""

lake = duckdb.connect()
lake.execute("INSTALL ducklake; INSTALL sqlite; LOAD ducklake")
lake.execute("ATTACH 'ducklake:sqlite:output/catalog.sqlite' AS lake (DATA_PATH 'output/data/')")
types = dict(
    lake.execute("SELECT column_name, column_type FROM (DESCRIBE lake.raw.orders)").fetchall()
)
expected = {
    "order_id": "BIGINT",
    "amount": "DECIMAL(12,2)",
    "discount": "DECIMAL(6,4)",
    "order_date": "DATE",
    "paid": "BOOLEAN",
}
for column, kind in expected.items():
    assert types[column] == kind, f"{column}: {types[column]}, expected {kind}"
assert "_sdc_batched_at" in types, "add_record_metadata: the _sdc_* columns are kept"
rows = lake.execute(
    "SELECT order_id, amount, discount, paid FROM lake.raw.orders ORDER BY order_id"
).fetchall()
assert len(rows) == LANDED, f"{len(rows)} rows, expected {LANDED}"
first = rows[0]
assert first == (1001, Decimal("1234.50"), Decimal("0.1000"), True), first
assert rows[1][1] == Decimal("-250.00"), rows[1]
print(f"lake.raw.orders: {len(rows)} rows, types {expected} - ok")
