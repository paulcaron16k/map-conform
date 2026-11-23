"""Benchmarks and the CI regression gate (WBS 8.9).

Run with ``pytest -m bench tests/bench``; CI runs them in their own job. Two gates:

- **Relative, machine-independent:** the columnar BATCH path is at least three times as
  fast as the row-by-row BATCH path on the same machine (CI has measured 3.7x to 4.7x).
  This is what the columnar engine is for.
- **Absolute, on CI only** (``CI`` set): each path keeps at least 60% of the baseline in
  ``baseline.json``, which is recorded on the slower class of CI runner. A 40% loss fails on
  a slow runner; on a fast one (about twice the speed) only a larger loss does.

The measured numbers are printed, and written to ``$BENCH_RESULTS`` in ``baseline.json``'s
own format, so re-recording the baseline is a copy (wiki/qa/benchmarks.md).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import platform
from pathlib import Path

import pyarrow as pa
import pytest

from tests.bench.workload import rows, time_batch, time_record

pytestmark = pytest.mark.bench

BASELINE = json.loads((Path(__file__).parent / "baseline.json").read_text(encoding="utf-8"))
FLOOR = 0.6
COLUMNAR_SPEEDUP = 3.0


def test_throughput_and_gates(tmp_path: Path) -> None:
    """Measure the three paths and apply both gates."""
    data = rows(BASELINE["rows"])
    measured = {
        "record": time_record(data),
        "batch_rows": time_batch(data, tmp_path, columnar=False),
        "batch_columnar": time_batch(data, tmp_path, columnar=True),
    }
    report = {k: round(v) for k, v in measured.items()}
    print(f"rows/s: {report}")  # noqa: T201 -- the benchmark's output
    if target := os.environ.get("BENCH_RESULTS"):
        recorded = {
            "recorded": dt.datetime.now(dt.UTC).date().isoformat(),
            "machine": f"{platform.machine()}, {os.cpu_count()} cores, Python "
            f"{platform.python_version()}, pyarrow {pa.__version__}",
            "rows": BASELINE["rows"],
            "rows_per_second": report,
        }
        Path(target).write_text(json.dumps(recorded, indent=2) + "\n", encoding="utf-8")
    speedup = measured["batch_columnar"] / measured["batch_rows"]
    assert speedup >= COLUMNAR_SPEEDUP, f"columnar is only {speedup:.1f}x the row path"
    if not os.environ.get("CI"):
        return  # the baseline is a CI runner's; elsewhere only the relative gate applies
    for path, baseline in BASELINE["rows_per_second"].items():
        assert measured[path] >= FLOOR * baseline, (
            f"{path}: {measured[path]:.0f} rows/s, under {FLOOR:.0%} of the baseline {baseline}"
        )
