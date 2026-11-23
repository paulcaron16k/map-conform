"""A column's ``flatten`` without a shape flattens it from the tap's schema (MAPC-141)."""

from __future__ import annotations

import io
import json
from typing import Any

import fsspec
import pyarrow.parquet as pq
import pytest
from singer_sdk.exceptions import ConfigValidationError

from map_conform.mapper import MapConformMapper

TEXT = {"type": ["string", "null"]}
PROPERTIES = {
    "id": TEXT,
    "address": {"type": ["object", "null"], "properties": {"city": TEXT}},
    "billing": {"type": ["object", "null"], "properties": {"city": TEXT, "zip": TEXT}},
}
RECORDS = [
    {"id": "1", "address": {"city": "Lyon"}, "billing": {"city": "Paris", "zip": "75001"}},
    {"id": "2", "address": None, "billing": None},
]


def spec(defaults: dict[str, Any], columns: dict[str, Any]) -> dict[str, Any]:
    """A one-stream spec that keeps the separator."""
    naming = {"naming": {"collapse": False}}
    return {
        "version": 1,
        "defaults": {**naming, **defaults},
        "streams": {"s": {"columns": columns}},
    }


def run(config: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    """SCHEMA and RECORDs through the mapper; the messages it writes."""
    mapper = MapConformMapper(config=config)
    lines: list[dict[str, Any]] = [{"type": "SCHEMA", "stream": "s", "key_properties": [],
              "schema": {"properties": PROPERTIES}}]  # fmt: skip
    lines += [{"type": "RECORD", "stream": "s", "record": r} for r in RECORDS]
    capsys.readouterr()
    mapper.listen(io.StringIO("".join(json.dumps(m) + "\n" for m in lines)))
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_flatten_true_flattens_one_column(capsys: pytest.CaptureFixture[str]) -> None:
    """Only the flagged column is flattened; the other object stays JSON text."""
    out = run({"spec": spec({}, {"billing": {"flatten": True}})}, capsys)
    schema = next(m for m in out if m["type"] == "SCHEMA")["schema"]["properties"]
    assert list(schema) == ["id", "address", "billing__city", "billing__zip"]
    assert [m["record"] for m in out if m["type"] == "RECORD"] == [
        {"id": "1", "address": '{"city": "Lyon"}', "billing__city": "Paris",
         "billing__zip": "75001"},
        {"id": "2", "address": None, "billing__city": None, "billing__zip": None},
    ]  # fmt: skip


def test_leaf_columns_can_be_declared(capsys: pytest.CaptureFixture[str]) -> None:
    """A leaf of a flagged column takes its own column spec."""
    columns = {"billing": {"flatten": True}, "billing__zip": {"type": "int32"}}
    out = run({"spec": spec({}, columns)}, capsys)
    assert next(m for m in out if m["type"] == "RECORD")["record"]["billing__zip"] == 75001  # noqa: PLR2004


def test_flatten_false_keeps_a_column_under_nested_flatten(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Under nested: flatten, flatten: false leaves that column whole."""
    columns = {"billing": {"flatten": False}}
    out = run({"spec": spec({"nested": "flatten"}, columns)}, capsys)
    record = next(m for m in out if m["type"] == "RECORD")["record"]
    assert "address__city" in record
    assert record["billing"] == {"city": "Paris", "zip": "75001"}


@pytest.mark.parametrize(
    ("column", "path"),
    [
        ({"flatten": True, "type": "string"}, "streams.s.columns.billing"),
        ({"flatten": True, "source": ["a", "b"]}, "streams.s.columns.billing.source"),
    ],
)
def test_other_keys_on_a_flagged_column_are_errors(
    column: dict[str, Any], path: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Types and steps belong on the leaf columns."""
    with pytest.raises(ConfigValidationError, match="Problems in") as caught:
        run({"spec": spec({}, {"billing": column})}, capsys)
    errors = caught.value.errors
    assert [e.split(":", 1)[0] for e in errors] == [path]


def test_flagged_column_in_batch(capsys: pytest.CaptureFixture[str]) -> None:
    """A JSONL BATCH flattens the flagged column the same way."""
    fs = fsspec.filesystem("memory")
    fs.pipe("/flat/in.jsonl", "".join(json.dumps(r) + "\n" for r in RECORDS).encode())
    config = {"spec": spec({}, {"billing": {"flatten": True}}),
              "batch_output": {"storage": {"root": "memory://flat/out"}}}  # fmt: skip
    mapper = MapConformMapper(config=config)
    schema = {"type": "SCHEMA", "stream": "s", "key_properties": [],
              "schema": {"properties": PROPERTIES}}  # fmt: skip
    batch = {"type": "BATCH", "stream": "s", "encoding": {"format": "jsonl"},
             "manifest": ["memory://flat/in.jsonl"]}  # fmt: skip
    capsys.readouterr()
    mapper.listen(io.StringIO(json.dumps(schema) + "\n" + json.dumps(batch) + "\n"))
    out = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    (uri,) = next(m for m in out if m["type"] == "BATCH")["manifest"]
    with fs.open(uri.removeprefix("memory://"), "rb") as handle:
        rows = pq.read_table(handle).to_pylist()
    fs.rm("/flat", recursive=True)
    assert [(r["billing__city"], r["billing__zip"]) for r in rows] == [("Paris", "75001"),
                                                                        (None, None)]  # fmt: skip
