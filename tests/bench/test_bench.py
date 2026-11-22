"""Benchmarks and the CI regression gate (WBS 8.9).

Run with ``pytest -m bench tests/bench``; CI runs them in their own job. Two gates:

- **Relative, machine-independent:** the columnar BATCH path is at least twice as fast as
  the row-by-row BATCH path on the same machine. This is what the columnar engine is for.
- **Absolute, lenient:** each path keeps at least a quarter of the baseline in
  ``baseline.json`` (recorded on a developer machine; CI runners vary), which catches a
  collapse rather than noise.

The measured numbers are printed, and written to ``$BENCH_RESULTS`` when it is set.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.bench.workload import rows, time_batch, time_record

pytestmark = pytest.mark.bench

BASELINE = json.loads((Path(__file__).parent / "baseline.json").read_text(encoding="utf-8"))
FLOOR = 0.25
COLUMNAR_SPEEDUP = 2.0


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
        Path(target).write_text(json.dumps(report, indent=2), encoding="utf-8")
    speedup = measured["batch_columnar"] / measured["batch_rows"]
    assert speedup >= COLUMNAR_SPEEDUP, f"columnar is only {speedup:.1f}x the row path"
    for path, baseline in BASELINE["rows_per_second"].items():
        assert measured[path] >= FLOOR * baseline, (
            f"{path}: {measured[path]:.0f} rows/s, under {FLOOR:.0%} of the baseline {baseline}"
        )
