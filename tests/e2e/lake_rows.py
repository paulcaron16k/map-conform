"""Print a DuckLake table's column types and rows as JSON (run by test_target_ducklake.py).

Runs in its own environment, with duckdb, so the test suite does not depend on it:
``uv run --no-project --with duckdb python lake_rows.py <lake dir> <schema.table>``. Every
value is cast to text in SQL, so the output needs no Python time-zone support.
"""

from __future__ import annotations

import json
import sys

import duckdb  # type: ignore[import-not-found]  # ty: ignore[import-not-found]

lake_dir, table = sys.argv[1], sys.argv[2]
lake = duckdb.connect()
lake.execute("INSTALL ducklake; INSTALL sqlite; LOAD ducklake")
lake.execute(
    f"ATTACH 'ducklake:sqlite:{lake_dir}/catalog.sqlite' AS lake (DATA_PATH '{lake_dir}/data/')"
)
types = dict(
    lake.execute(f"SELECT column_name, column_type FROM (DESCRIBE lake.{table})").fetchall()  # noqa: S608 -- the test names the table
)
columns = ", ".join(f'CAST("{c}" AS VARCHAR) AS "{c}"' for c in types)
cursor = lake.execute(f"SELECT {columns} FROM lake.{table}")  # noqa: S608 -- the lake's own columns
names = [d[0] for d in cursor.description]
rows = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
json.dump({"types": types, "rows": rows}, sys.stdout)
