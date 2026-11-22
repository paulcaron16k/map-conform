"""Declared shapes in BATCH output: stable parquet schema and empty values (WBS 8.10)."""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING, Any

import fsspec
import pyarrow.parquet as pq

from map_conform.mapper import MapConformMapper
from tests.naming.test_shape import DEFAULTS, SHAPE

if TYPE_CHECKING:
    import pytest

RECORDS = [
    {"id": "a", "user": {"id": 1, "tags": ["t"], "prefs": {"k": 1}, "extra": 1}},
    {"id": "b", "user": {"id": 2, "tags": [], "prefs": {}}},
    {"id": "c", "user": None},
]


def run_batch(tap_user: dict[str, Any], capsys: pytest.CaptureFixture[str], name: str) -> Any:  # noqa: ANN401 -- a table and a mapper
    """Write RECORDS as a JSONL BATCH in memory, conform it, read the parquet output."""
    fs = fsspec.filesystem("memory")
    fs.pipe(f"/shape/{name}.jsonl", "".join(json.dumps(r) + "\n" for r in RECORDS).encode())
    schema = {"type": "SCHEMA", "stream": "s", "key_properties": [],
              "schema": {"properties": {"id": {"type": "string"}, **tap_user}}}  # fmt: skip
    batch = {"type": "BATCH", "stream": "s", "encoding": {"format": "jsonl"},
             "manifest": [f"memory://shape/{name}.jsonl"]}  # fmt: skip
    spec = {"version": 1, "defaults": DEFAULTS,
            "streams": {"s": {"columns": {"user": {"shape": SHAPE, "flatten": True}}}}}  # fmt: skip
    output = {"storage": {"root": "memory://shape/out"}}
    mapper = MapConformMapper(config={"spec": spec, "batch_output": output})
    capsys.readouterr()
    mapper.listen(io.StringIO(json.dumps(schema) + "\n" + json.dumps(batch) + "\n"))
    out = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    (uri,) = next(m for m in out if m["type"] == "BATCH")["manifest"]
    with fs.open(uri.removeprefix("memory://"), "rb") as handle:
        table = pq.read_table(handle)
    return table, mapper


def test_batch_schema_is_stable_and_defaults_apply(capsys: pytest.CaptureFixture[str]) -> None:
    """The parquet schema ignores tap drift; missing and empty members land as their defaults."""
    table, mapper = run_batch({"user": {"type": "object"}}, capsys, "one")
    drifted, _ = run_batch({"user": {"type": "string"}}, capsys, "two")
    assert drifted.schema == table.schema
    assert str(table.schema.field("user__tags").type) == "list<element: string>"
    rows = table.to_pylist()
    assert [r["user__tags"] for r in rows] == [["t"], [], []]
    assert [r["user__prefs"] for r in rows] == ['{"k": 1}', "{}", "{}"]
    assert [r["user__address__geo"] for r in rows] == [None, None, None]
    assert mapper._metrics["s"].members_dropped == {("user", "extra"): 1}  # noqa: SLF001
    fsspec.filesystem("memory").rm("/shape", recursive=True)
