"""BATCH: manifests over fsspec, parquet and JSONL in and out, record mode (WBS 8.1-8.3, 8.8)."""

from __future__ import annotations

import datetime as dt
import gzip
import io
import json
import os
import shutil
from pathlib import Path
from typing import Any

import fsspec
import pyarrow.parquet as pq
import pytest

from map_conform.batch.arrow import arrow_schema, output_columns
from map_conform.mapper import MapConformMapper
from tests.fixtures.paths import FIXTURES, messages

SPEC: dict[str, Any] = {
    "version": 1,
    "defaults": {"on_error": "null"},
    "streams": {
        "Orders Export": {
            "columns": {
                "Order ID": {"name": "order_id", "type": "int64"},
                "Amount ($)": {"type": "decimal(12,2)", "parse": {"parens_negative": True,
                                                                  "trailing_minus": True}},
                "Order Date": {"type": "date", "parse": {"formats": ["%m/%d/%Y", "iso",
                                                                    "excel_serial"]}},
                "Tracking UUID": {"type": "uuid"},
                "Created At (UTC)": {"type": "timestamptz"},
            }
        }
    },
}  # fmt: skip


def run(
    stream: list[dict[str, Any]], capsys: pytest.CaptureFixture[str], **config: Any
) -> tuple[MapConformMapper, list[dict[str, Any]]]:
    """Feed messages to a mapper with SPEC and the given settings."""
    mapper = MapConformMapper(config={"spec": config.pop("spec", SPEC), **config})
    capsys.readouterr()
    mapper.listen(io.StringIO("".join(json.dumps(m) + "\n" for m in stream)))
    return mapper, [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def records_of(
    stream: list[dict[str, Any]], capsys: pytest.CaptureFixture[str], **config: Any
) -> list[dict[str, Any]]:
    """The RECORD path's output for the same rows."""
    _, out = run(stream, capsys, **config)
    return [m["record"] for m in out if m["type"] == "RECORD"]


def copied(tmp_path: Path, name: str) -> list[dict[str, Any]]:
    """The fixture stream with its BATCH files copied into tmp_path (so they can be deleted)."""
    for file in (FIXTURES / "batch").iterdir():
        shutil.copy(file, tmp_path / file.name)
    text = json.dumps(messages(name)).replace(
        f"file://{FIXTURES.as_posix()}/batch", f"file://{tmp_path.as_posix()}"
    )
    return json.loads(text)


def test_parquet_in_parquet_out_matches_the_record_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One output file per input file, in order; schema = to_arrow(plan); same values as RECORDs."""
    stream = copied(tmp_path, "orders_export.batch-parquet.singer.jsonl")
    mapper, out = run(stream, capsys, batch_output={"storage": {"root": f"file://{tmp_path}/out"}})
    batch = next(m for m in out if m["type"] == "BATCH")
    assert batch["stream"] == "orders_export"
    assert batch["encoding"] == {"format": "parquet", "compression": "zstd"}
    assert batch["version"] == 1773489600000  # noqa: PLR2004
    assert [Path(u).name.rsplit("-", 1)[1] for u in batch["manifest"]] == [
        "0001.parquet",
        "0002.parquet",
    ]
    assert [m["type"] for m in out] == ["SCHEMA", "BATCH", "STATE"]
    plan = mapper._executors["Orders Export"][0].plan  # noqa: SLF001
    tables = [pq.read_table(u.removeprefix("file://")) for u in batch["manifest"]]
    assert tables[0].schema == arrow_schema(output_columns(plan, metadata=False))
    expected = records_of(messages("orders_export.singer.jsonl"), capsys)
    rows = [r for t in tables for r in t.to_pylist()]
    assert [r["order_id"] for r in rows] == [r["order_id"] for r in expected]
    assert [str(r["amount"]) if r["amount"] is not None else None for r in rows] == [
        r["amount"] for r in expected
    ]
    assert [str(r["tracking_uuid"]) if r["tracking_uuid"] else None for r in rows] == [
        r["tracking_uuid"] for r in expected
    ]


@pytest.mark.parametrize(("compression", "suffix"), [("gzip", ".jsonl.gz"), ("none", ".jsonl")])
def test_jsonl_in_jsonl_out(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], compression: str, suffix: str
) -> None:
    """JSONL input (gzip) to JSONL output, gzipped or plain, with the RECORD path's values."""
    stream = copied(tmp_path, "orders_export.batch-jsonl.singer.jsonl")
    output = {"format": "jsonl", "compression": compression, "storage": {"root": str(tmp_path)}}
    _, out = run(stream, capsys, batch_output=output)
    (uri,) = next(m for m in out if m["type"] == "BATCH")["manifest"]
    assert uri.endswith(suffix)
    raw = Path(uri.removeprefix("file://")).read_bytes()
    text = gzip.decompress(raw).decode() if compression == "gzip" else raw.decode()
    rows = [json.loads(line) for line in text.splitlines()]
    assert rows == records_of(messages("orders_export.singer.jsonl"), capsys)[:6]


def test_memory_filesystem(capsys: pytest.CaptureFixture[str]) -> None:
    """Manifests and output on fsspec's memory filesystem."""
    fs = fsspec.filesystem("memory")
    fs.pipe(
        "/in/orders-0001.parquet", (FIXTURES / "batch" / "orders_export-0001.parquet").read_bytes()
    )
    stream = messages("orders_export.batch-parquet.singer.jsonl")
    stream[1]["manifest"] = ["memory://in/orders-0001.parquet"]
    _, out = run(stream, capsys, batch_output={"storage": {"root": "memory://out"}})
    (uri,) = next(m for m in out if m["type"] == "BATCH")["manifest"]
    assert uri.startswith("memory://out/orders_export/")
    with fs.open(uri.removeprefix("memory://"), "rb") as handle:
        assert pq.read_table(handle).num_rows == 6  # noqa: PLR2004
    fs.rm("/in", recursive=True)
    fs.rm("/out", recursive=True)


def test_record_mode_and_delete_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """batch_output.mode: record emits RECORDs (for targets without BATCH); inputs deleted."""
    stream = copied(tmp_path, "orders_export.batch-parquet.singer.jsonl")
    _, out = run(stream, capsys, batch_output={"mode": "record", "delete_input": True})
    records = [m for m in out if m["type"] == "RECORD"]
    assert [m["record"] for m in records] == records_of(
        messages("orders_export.singer.jsonl"), capsys
    )
    assert all(m["version"] == 1773489600000 for m in records)  # noqa: PLR2004
    assert not (tmp_path / "orders_export-0001.parquet").exists()
    assert not (tmp_path / "orders_export-0002.parquet").exists()


def test_batched_at_is_the_input_files_mtime(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """_sdc_batched_at is each input file's last-modified time."""
    stream = copied(tmp_path, "orders_export.batch-parquet.singer.jsonl")
    moment = dt.datetime(2026, 3, 1, 12, tzinfo=dt.UTC)
    os.utime(tmp_path / "orders_export-0001.parquet", (moment.timestamp(), moment.timestamp()))
    spec = {**SPEC, "defaults": {**SPEC["defaults"], "add_record_metadata": True}}
    _, out = run(stream, capsys, spec=spec, batch_output={"mode": "record"})
    first = next(m["record"] for m in out if m["type"] == "RECORD")
    assert first["_sdc_batched_at"] == moment.isoformat()
    assert first["_sdc_extracted_at"] == "2026-03-14T12:00:00.000000+00:00"
    _, out = run(copied(tmp_path, "orders_export.batch-parquet.singer.jsonl"), capsys, spec=spec,
                 batch_output={"storage": {"root": str(tmp_path / "o")}})  # fmt: skip
    batch = next(m for m in out if m["type"] == "BATCH")
    table = pq.read_table(batch["manifest"][0].removeprefix("file://"))
    assert "_sdc_batched_at" in table.schema.names
    assert table.schema.field("_sdc_sequence").type == "int64"


def test_rejected_batch_rows_go_to_the_sink(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """on_error: reject works the same for BATCH rows."""
    spec = {"version": 1, "defaults": {"on_error": "reject"},
            "streams": {"Orders Export": {"columns": {"Order ID": {"type": "int64"},
                                                      "Qty.": {"type": "int16"}}}}}  # fmt: skip
    stream = copied(tmp_path, "orders_export.batch-parquet.singer.jsonl")
    mapper, _ = run(stream, capsys, spec=spec, reject={"storage": str(tmp_path / "rejects")},
                    batch_output={"storage": {"root": str(tmp_path / "out")}})  # fmt: skip
    metrics = mapper._metrics["orders_export"]  # noqa: SLF001
    assert metrics.rows_rejected > 0
    assert metrics.rows_out + metrics.rows_rejected == metrics.rows_in == 12  # noqa: PLR2004
    assert any((tmp_path / "rejects").rglob("*.jsonl"))


def test_unreadable_manifest(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """A missing file or an unknown format stops the run with the URI."""
    stream = messages("orders_export.batch-parquet.singer.jsonl")
    stream[1]["manifest"] = [f"file://{tmp_path}/nope.parquet"]
    with pytest.raises(Exception, match="cannot read file://"):
        run(stream, capsys)
    stream[1]["encoding"] = {"format": "csv"}
    with pytest.raises(Exception, match="BATCH format 'csv' is not supported"):
        run(stream, capsys)
