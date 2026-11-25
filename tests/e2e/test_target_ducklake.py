"""A messy export lands clean in DuckLake with the target's own cleanup off (WBS 11.2).

map-conform's output goes into target-ducklake with every cleanup option the target has
turned off: no ``type_source``, no ``conform_column_names``, no ``auto_cast_timestamps``,
``value_type_checking: strict`` (a value the column would round fails instead of being
repaired) and ``validate_records: true`` (records are checked against the SCHEMA). The lake
must then hold exactly what the mapper wrote, in the declared column types. The findings
are in wiki/qa/target-ducklake-clean-landing.md.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from tests.e2e.test_target_jsonl import SPEC as JSONL_SPEC
from tests.fixtures.paths import FIXTURES, messages

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(shutil.which("uvx") is None, reason="needs uv to run target-ducklake"),
]

SPEC = (
    JSONL_SPEC
    + """\
      line: {type: json, expr: '{"sku": sku, "qty": qty, "tags": [sku, notes]}'}
      amount_wide: {type: "decimal(50,10)", expr: amount}
"""
)
"""The target-jsonl spec, plus a json column and a decimal wider than DuckDB's 38 digits."""
TARGET_COMMIT = "cfbd0126ffd5f74b68cab0d9b4fac5d273cb4578"
"""target-ducklake (the paulcaron16k fork) as tested; move it on deliberately."""
LOCAL_TARGET = os.environ.get("MAP_CONFORM_TARGET_DUCKLAKE")
"""A target-ducklake checkout to test instead, e.g. a fix before it is pushed."""
TARGET = (
    ["uv", "run", "--project", LOCAL_TARGET, "target-ducklake"]
    if LOCAL_TARGET
    else [
        "uvx", "--python", "3.12", "--from",
        f"git+https://github.com/paulcaron16k/target-ducklake-definite.git@{TARGET_COMMIT}",
        "target-ducklake",
    ]
)  # fmt: skip
"""A checkout runs from its own environment, so its source as it is now (uvx would reuse
its first build of the path). The pinned commit runs on Python 3.12, which duckdb has
wheels for, so nothing is compiled."""
LAKE_ROWS = [
    "uv", "run", "--no-project", "--python", "3.12", "--with", "duckdb==1.5.2", "python",
    str(Path(__file__).with_name("lake_rows.py")),
]  # fmt: skip
CLEANUP_OFF = {
    "conform_column_names": False,
    "auto_cast_timestamps": False,
    "value_type_checking": "strict",
    "validate_records": True,
    "add_record_metadata": True,
}
TYPES = {
    "order_id": "BIGINT",
    "order_date": "DATE",
    "customer_id": "VARCHAR",
    "customer_name": "VARCHAR",
    "amount": "DECIMAL(12,2)",
    "discount": "DECIMAL(6,4)",
    "paid": "BOOLEAN",
    "ship_date": "DATE",
    "qty": "INTEGER",
    "unit_price": "DECIMAL(12,4)",
    "created_at_utc": "TIMESTAMP WITH TIME ZONE",
    "tracking_uuid": "UUID",
    "sku": "VARCHAR",
    "notes": "VARCHAR",
    "line": "JSON",
    "amount_wide": "DECIMAL(38,9)",
}
SET_BY_TARGET = {"_sdc_received_at", "_sdc_batched_at", "_sdc_sequence", "_sdc_sync_started_at"}
"""The Singer SDK in the target writes these itself; the others come from the messages."""


def conform(tmp_path: Path, source: Path, batch_format: str = "parquet") -> str:
    """Run map-conform on a Singer file; return what it writes."""
    (tmp_path / "conform.yml").write_text(SPEC, encoding="utf-8")
    config = {
        "spec_path": str(tmp_path / "conform.yml"),
        "batch_output": {
            "format": batch_format,
            "storage": {"root": f"file://{tmp_path}/batch-{batch_format}"},
        },
    }
    (tmp_path / "mapper.json").write_text(json.dumps(config))
    executable = str(Path(sys.executable).with_name("map-conform"))
    return subprocess.run(  # noqa: S603 -- fixed argv: the installed console script
        [executable, "--config", str(tmp_path / "mapper.json"), "--input", str(source)],
        capture_output=True, text=True, check=True, timeout=120,
    ).stdout  # fmt: skip


def records(singer: str) -> list[dict[str, Any]]:
    """The records in Singer output."""
    messages = [json.loads(line) for line in singer.splitlines()]
    return [m["record"] for m in messages if m["type"] == "RECORD"]


def land(tmp_path: Path, singer: str) -> dict[str, Any]:
    """Load Singer output with target-ducklake, cleanup off; return the lake's table."""
    lake = tmp_path / "lake"
    (lake / "data").mkdir(parents=True)
    config = {
        "catalog_type": "sqlite",
        "catalog_url": str(lake / "catalog.sqlite"),
        "data_path": f"{lake}/data/",
        "storage_type": "local",
        "default_target_schema": "raw",
        **CLEANUP_OFF,
    }
    (tmp_path / "target.json").write_text(json.dumps(config))
    target = subprocess.run(  # noqa: S603 -- fixed argv: uvx runs the pinned target
        [*TARGET, "--config", str(tmp_path / "target.json")],
        input=singer, capture_output=True, text=True, check=False, timeout=600, cwd=tmp_path,
    )  # fmt: skip
    assert target.returncode == 0, target.stderr[-3000:]
    queried = subprocess.run(  # noqa: S603 -- fixed argv: uv runs the query script
        [*LAKE_ROWS, str(lake), "raw.raw_orders_export"],
        capture_output=True, text=True, check=True, timeout=300,
    )  # fmt: skip
    return dict(json.loads(queried.stdout))


COMPARE: dict[str, Callable[[str, object], bool]] = {
    "DECIMAL": lambda landed, sent: Decimal(landed) == Decimal(str(sent)),
    "BIGINT": lambda landed, sent: int(landed) == sent,
    "INTEGER": lambda landed, sent: int(landed) == sent,
    "BOOLEAN": lambda landed, sent: landed == str(sent).lower(),
    "JSON": lambda landed, sent: json.loads(landed) == json.loads(str(sent)),
    "TIMESTAMP": lambda landed, sent: (
        datetime.fromisoformat(landed) == datetime.fromisoformat(str(sent))
    ),
}
"""How the lake's text of a value compares with the value sent, by column type."""


def same(kind: str, landed: str | None, sent: object) -> bool:
    """Whether the lake's text for a value of column type ``kind`` is the value sent."""
    if landed is None or sent is None:
        return landed is None and sent is None
    prefix = next((p for p in COMPARE if kind.startswith(p)), None)
    return COMPARE[prefix](landed, sent) if prefix else landed == sent


def check(sent: list[dict[str, Any]], lake: dict[str, Any]) -> None:
    """The lake has the declared types and, row for row, the values the mapper wrote."""
    types = lake["types"]
    assert {k: v for k, v in types.items() if not k.startswith("_sdc_")} == TYPES
    assert {k for k in types if k.startswith("_sdc_")} == {
        k for k in sent[0] if k.startswith("_sdc_")
    }
    rows = {int(row["order_id"]): row for row in lake["rows"]}
    assert len(rows) == len(sent) == 12  # noqa: PLR2004
    for record in sent:
        row = rows[record["order_id"]]
        for column, kind in types.items():
            if column not in SET_BY_TARGET:
                assert same(kind, row[column], record[column]), (
                    column,
                    row[column],
                    record[column],
                )


def test_records_land_clean_with_target_cleanup_off(tmp_path: Path) -> None:
    """RECORD messages: every column in its declared type, every value as the mapper wrote it."""
    singer = conform(tmp_path, FIXTURES / "streams" / "orders_export.singer.jsonl")
    check(records(singer), land(tmp_path, singer))


@pytest.mark.parametrize("batch_format", ["parquet", "jsonl"])
def test_batch_files_land_clean_with_target_cleanup_off(tmp_path: Path, batch_format: str) -> None:
    """BATCH files of the same rows, parquet or JSONL: the same lake as the RECORD path."""
    expected = records(conform(tmp_path, FIXTURES / "streams" / "orders_export.singer.jsonl"))
    source = tmp_path / "batch.singer.jsonl"
    source.write_text("".join(json.dumps(m) + "\n" for m in messages(
        "orders_export.batch-parquet.singer.jsonl")))  # fmt: skip
    singer = conform(tmp_path, source, batch_format)
    written = [json.loads(line) for line in singer.splitlines()]
    batches = [m for m in written if m["type"] == "BATCH"]
    assert batches
    assert not [m for m in written if m["type"] == "RECORD"]
    assert {b["encoding"]["format"] for b in batches} == {batch_format}
    check(expected, land(tmp_path, singer))
