---
type: metric
title: "Benchmarks"
description: "Throughput baseline for RECORD, row-wise BATCH and columnar BATCH, and the CI regression gate."
resource: tests/bench/
tags: [qa, performance, active]
timestamp: 2026-11-22T21:00:00Z
sources:
  - path: tests/bench/baseline.json
  - path: tests/bench/workload.py
---

# Benchmarks

Parent: [Wiki Index](../index.md) · Related: [Test strategy](test-strategy.md)

## Workload

`tests/bench/workload.py` generates 50,000 deterministic rows shaped like the orders fixture:
text ids, money with and without currency symbols, ISO and US dates, quantities, flags,
UUIDs and padded notes, all strings, about one value in twenty messy. The spec casts them to
int64, decimal(12,2), date, int32, boolean, uuid and a trimmed, uppercased string.

## Baseline (2026-11-22)

Recorded on x86_64, 4 cores, Python 3.14.6, pyarrow 26.0.1 (`tests/bench/baseline.json`).

| Path | Rows/s | What it measures |
|---|---:|---|
| RECORD | 6,099 | RECORD messages through the mapper, row executor |
| BATCH, row by row | 9,186 | a parquet BATCH with the columnar engine off |
| BATCH, columnar | 40,055 | the same BATCH through the columnar engine |

CI's *Benchmarks* job on its first run (ubuntu-latest, Python 3.14) measured RECORD
17,325, row-wise BATCH 23,367 and columnar BATCH 109,735 rows/s.

The columnar engine is about 4–5× the row path on this workload. The uuid column, the messy
values and the `_sdc_*`/policy bookkeeping still run per row, so it gains most on clean,
vectorisable data.

## Regression gate

`pytest -m bench tests/bench` runs in the CI job *Benchmarks*, and the numbers go to the
job summary. It fails when:

- columnar BATCH is less than 2× row-wise BATCH on the same runner (machine-independent);
- any path falls under 25% of its baseline above (lenient, since CI runners vary).

Re-record the baseline when the workload or the engine changes deliberately, and update
this table.
