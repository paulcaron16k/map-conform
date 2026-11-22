"""A deterministic messy-spreadsheet workload and the three paths to time (WBS 8.9).

The rows look like the orders fixture at scale: text ids, money with and without currency
symbols, ISO and US dates, quantities, flags and UUIDs, all as strings, about one value in
twenty messy. Timed paths:

- ``record``: RECORD messages through the mapper, in process;
- ``batch_rows``: a parquet BATCH conformed row by row (the columnar engine switched off);
- ``batch_columnar``: the same BATCH through the columnar engine.
"""

from __future__ import annotations

import io
import json
import random
import time
from contextlib import redirect_stdout
from typing import TYPE_CHECKING, Any
from unittest import mock

import pyarrow as pa
import pyarrow.parquet as pq

from map_conform.batch import engine
from map_conform.mapper import MapConformMapper

if TYPE_CHECKING:
    from pathlib import Path

COLUMNS = ("Order ID", "Amount", "Order Date", "Qty", "Paid", "Tracking", "Note")
SPEC: dict[str, Any] = {
    "version": 1,
    "defaults": {"on_error": "null"},
    "streams": {"orders": {"columns": {
        "Order ID": {"type": "int64"},
        "Amount": {"type": "decimal(12,2)", "parse": {"parens_negative": True}},
        "Order Date": {"type": "date"},
        "Qty": {"type": "int32"},
        "Paid": {"type": "boolean"},
        "Tracking": {"type": "uuid"},
        "Note": {"type": "string", "transform": ["trim", "upper"]},
    }}},
}  # fmt: skip


def rows(n: int, seed: int = 7) -> list[dict[str, str | None]]:
    """Deterministic rows, n of them, about one value in twenty messy."""
    rng = random.Random(seed)  # noqa: S311 -- reproducible test data
    out = []
    for i in range(n):
        messy = rng.random() < 0.05  # noqa: PLR2004
        out.append({
            "Order ID": str(1000 + i),
            "Amount": f"${rng.randint(1, 9999):,}.{rng.randint(0, 99):02d}" if messy
            else f"{rng.randint(1, 9999)}.{rng.randint(0, 99):02d}",
            "Order Date": f"{rng.randint(1, 12)}/{rng.randint(1, 28)}/2026" if messy
            else f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            "Qty": str(rng.randint(1, 500)),
            "Paid": rng.choice(["true", "false", "yes", "no"]),
            "Tracking": f"{rng.getrandbits(128):032x}",
            "Note": rng.choice(["  ok ", "rush", None, "gift wrap"]),
        })  # fmt: skip
    return out


def _schema() -> dict[str, Any]:
    properties = {c: {"type": ["string", "null"]} for c in COLUMNS}
    return {"type": "SCHEMA", "stream": "orders", "schema": {"properties": properties},
            "key_properties": []}  # fmt: skip


def _run(lines: list[str], config: dict[str, Any]) -> float:
    mapper = MapConformMapper(config={"spec": SPEC, **config})
    started = time.perf_counter()
    with redirect_stdout(io.StringIO()):
        mapper.listen(io.StringIO("\n".join(lines) + "\n"))
    return time.perf_counter() - started


def time_record(data: list[dict[str, str | None]]) -> float:
    """Rows per second through RECORD messages."""
    lines = [json.dumps(_schema())]
    lines += [json.dumps({"type": "RECORD", "stream": "orders", "record": r}) for r in data]
    return len(data) / _run(lines, {})


def _batch_lines(data: list[dict[str, str | None]], folder: Path) -> list[str]:
    path = folder / "orders.parquet"
    table = pa.table({c: pa.array([r[c] for r in data], pa.string()) for c in COLUMNS})
    pq.write_table(table, path, row_group_size=50_000)
    batch = {"type": "BATCH", "stream": "orders", "encoding": {"format": "parquet"},
             "manifest": [f"file://{path}"]}  # fmt: skip
    return [json.dumps(_schema()), json.dumps(batch)]


def time_batch(data: list[dict[str, str | None]], folder: Path, *, columnar: bool) -> float:
    """Rows per second through a parquet BATCH, with or without the columnar engine."""
    lines = _batch_lines(data, folder)
    config = {"batch_output": {"storage": {"root": str(folder / "out")}}}
    if columnar:
        return len(data) / _run(lines, config)
    with mock.patch.object(engine, "columnar", return_value=False):
        return len(data) / _run(lines, config)
