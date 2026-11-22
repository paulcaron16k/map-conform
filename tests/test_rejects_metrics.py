"""Reject sink, rate thresholds (WBS 7.3) and metrics (WBS 7.4)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pyarrow.parquet as pq
import pytest

from map_conform.errors import ThresholdExceeded
from map_conform.spec.errors import SpecError
from map_conform.spec.model import parse_spec
from tests.test_mapper import RECORD, SCHEMA, STATE, run_mapper

if TYPE_CHECKING:
    from pathlib import Path


def spec(**defaults: Any) -> dict[str, Any]:
    """Order ID as int64, Amount as decimal, with the given defaults."""
    return {
        "version": 1,
        "defaults": {"metadata": "none", **defaults},
        "streams": {
            "Customer Orders": {
                "columns": {
                    "Order ID": {"name": "order_id", "type": "int64"},
                    "Amount": {"type": "decimal(12,2)"},
                }
            }
        },
    }


def record(amount: str, order_id: str = "1") -> dict[str, Any]:
    """A RECORD with the given values."""
    return {**RECORD, "record": {**RECORD["record"], "Amount": amount, "Order ID": order_id}}


def test_rejected_rows_go_to_the_jsonl_sink(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Each rejected row is written with its context and the whole raw record."""
    out = run_mapper(
        [SCHEMA, record("1"), record("lots", "2"), record("3", "3")],
        capsys,
        spec(on_error="reject"),
        reject={"storage": str(tmp_path)},
    )
    assert [m["record"]["order_id"] for m in out if m["type"] == "RECORD"] == [1, 3]
    (path,) = (tmp_path / "customer_orders").glob("*.jsonl")
    (row,) = [json.loads(line) for line in path.read_text().splitlines()]
    assert row["stream"] == "customer_orders"
    assert row["row_number"] == 2  # noqa: PLR2004
    assert row["column"] == "amount"
    assert row["rule"] == "cast: decimal(12,2)"
    assert "failed on 'lots'" in row["error"]
    assert row["value"] == '"lots"'
    assert json.loads(row["record"])["Amount"] == "lots"


def test_parquet_sink(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """reject.format: parquet writes the same columns as a parquet file."""
    run_mapper(
        [SCHEMA, record("lots")],
        capsys,
        spec(on_error="reject"),
        reject={"storage": str(tmp_path), "format": "parquet"},
    )
    (path,) = (tmp_path / "customer_orders").glob("*.parquet")
    table = pq.read_table(path)
    assert table.column_names == [
        "stream",
        "row_number",
        "column",
        "rule",
        "error",
        "value",
        "record",
        "rejected_at",
    ]
    assert table.column("column").to_pylist() == ["amount"]


def test_reject_rate_stops_before_state_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Over max_reject_rate, the run fails before the STATE reaches the target."""
    messages = [SCHEMA, record("1"), record("bad"), record("worse"), STATE]
    with pytest.raises(
        ThresholdExceeded, match=r"2 of 3 rows rejected \(66.7%\), over the limit of 50.0%"
    ):
        run_mapper(
            messages,
            capsys,
            spec(on_error="reject", max_reject_rate=0.5),
            reject={"storage": str(tmp_path)},
        )
    assert '"type": "STATE"' not in capsys.readouterr().out


def test_null_rate_is_checked_at_the_end_too(capsys: pytest.CaptureFixture[str]) -> None:
    """max_null_rate counts rows where on_error: null nulled a value."""
    with pytest.raises(ThresholdExceeded, match="1 of 2 rows nulled"):
        run_mapper(
            [SCHEMA, record("1"), record("bad")], capsys, spec(on_error="null", max_null_rate=0.25)
        )
    out = run_mapper(
        [SCHEMA, record("1"), record("bad"), STATE],
        capsys,
        spec(on_error="null", max_null_rate=0.5),
    )
    assert out[-1] == STATE


def test_metrics_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """metrics_path gets each stream's counters."""
    metrics = tmp_path / "m" / "metrics.json"
    run_mapper(
        [SCHEMA, record("1"), record("bad"), record("x", "y")],
        capsys,
        spec(on_error="null"),
        metrics_path=str(metrics),
    )
    document = json.loads(metrics.read_text())
    assert document == {
        "streams": {
            "customer_orders": {
                "rows_in": 3,
                "rows_out": 3,
                "rows_rejected": 0,
                "rows_nulled": 2,
                "rows_filtered": 0,
                "values_kept": 0,
                "errors": [
                    {"column": "amount", "rule": "cast: decimal(12,2)", "count": 2},
                    {"column": "order_id", "rule": "cast: int64", "count": 1},
                ],
            }
        }
    }


def test_metrics_are_logged(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    """Each stream's counters are logged at the end of the run."""
    run_mapper([SCHEMA, record("1")], capsys, spec())
    assert 'Metrics for \'customer_orders\': {"rows_in": 1, "rows_out": 1' in caplog.text


def test_threshold_values_are_validated() -> None:
    """A rate must be a fraction."""
    with pytest.raises(SpecError, match=r"defaults\.max_reject_rate: must be between 0 and 1"):
        parse_spec({"version": 1, "defaults": {"max_reject_rate": 1.5}})
