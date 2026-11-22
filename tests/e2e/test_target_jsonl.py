"""A messy spreadsheet export lands clean in target-jsonl (WBS 5.8 acceptance)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fixtures.paths import FIXTURES

pytestmark = pytest.mark.e2e

SPEC = """\
version: 1
defaults: {stream: {prefix: raw_}, on_error: "null"}
streams:
  Orders Export:
    key_properties: [order_id]
    columns:
      Order ID: {name: order_id, type: int64, nullable: false}
      Order Date: {type: date, parse: {formats: ["%m/%d/%Y", iso, excel_serial]}}
      Amount ($): {type: "decimal(12,2)", parse: {parens_negative: true, trailing_minus: true}}
      Discount %: {type: "decimal(6,4)", parse: {percent: divide}}
      Paid?: {type: boolean}
      Ship Date: {type: date, parse: {formats: ["%m/%d/%Y", iso, excel_serial]}}
      Qty.: {type: int32}
      Unit Price (€): {type: "decimal(12,4)"}
      Created At (UTC): {type: timestamptz}
      Tracking UUID: {type: uuid}
"""


@pytest.mark.skipif(shutil.which("uvx") is None, reason="needs uvx to run target-jsonl")
def test_orders_export_lands_clean_in_target_jsonl(tmp_path: Path) -> None:
    """map-conform | target-jsonl: conformed names, cleaned values, metadata."""
    (tmp_path / "conform.yml").write_text(SPEC, encoding="utf-8")
    (tmp_path / "mapper.json").write_text(json.dumps({"spec_path": str(tmp_path / "conform.yml")}))
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (tmp_path / "target.json").write_text(json.dumps({"destination_path": str(out_dir)}))
    executable = str(Path(sys.executable).with_name("map-conform"))
    source = FIXTURES / "streams" / "orders_export.singer.jsonl"
    mapper = subprocess.run(  # noqa: S603 -- fixed argv: the installed console script
        [executable, "--config", str(tmp_path / "mapper.json"), "--input", str(source)],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    target = ["uvx", "--from", "target-jsonl", "target-jsonl"]
    subprocess.run(  # noqa: S603 -- fixed argv: uvx runs the published target
        [*target, "--config", str(tmp_path / "target.json")],
        input=mapper.stdout,
        capture_output=True,
        text=True,
        check=True,
        timeout=300,
    )
    (landed,) = out_dir.glob("raw_orders_export*.jsonl")
    rows = [json.loads(line) for line in landed.read_text().splitlines()]
    assert len(rows) == 12  # noqa: PLR2004
    first, refund, serial_date, nulls, uncleanable = rows[0], rows[1], rows[2], rows[4], rows[9]
    assert first["order_id"] == 1001  # noqa: PLR2004
    assert first["amount"] == "1234.50"
    assert first["discount"] == "0.1000"
    assert first["paid"] is True
    assert first["ship_date"] == "2026-03-16"  # Excel serial 46097
    assert first["customer_name"] == "Ada Lovelace"
    assert first["created_at_utc"] == "2026-03-14T09:26:53.000000Z"
    assert refund["amount"] == "-250.00"
    assert refund["tracking_uuid"] == "f47ac10b-58cc-4372-a567-0e02b2c3d479"
    assert serial_date["order_date"] == "2026-03-15"  # Excel serial 46096
    assert serial_date["created_at_utc"] == "2026-03-15T21:59:59.500000Z"
    assert all(nulls[k] is None for k in ("amount", "discount", "paid", "qty", "unit_price"))
    assert uncleanable["amount"] is None  # "abc" under on_error: null
    assert first["_sdc_table_version"] == 1773489600000  # noqa: PLR2004
    assert first["_sdc_extracted_at"] == "2026-03-14T12:00:00.000000+00:00"
