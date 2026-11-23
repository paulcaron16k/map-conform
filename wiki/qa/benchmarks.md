---
type: metric
title: "Benchmarks"
description: "Throughput baseline for RECORD, row-wise BATCH and columnar BATCH, and the CI regression gate."
resource: tests/bench/
tags: [qa, performance, active]
timestamp: 2026-11-23T18:00:00Z
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

## Baseline (2026-11-23, CI)

Recorded on GitHub Actions `ubuntu-latest`, Python 3.14 (`tests/bench/baseline.json`), from
twelve runs of `main`. The runners come in two speeds about 2× apart; the baseline is the
slower class, so a slow runner does not fail the gate on its own.

| Path | Slow runner, rows/s | Fast runner, rows/s | What it measures |
|---|---:|---:|---|
| RECORD | 11,100 | 17,000–26,000 | RECORD messages through the mapper, row executor |
| BATCH, row by row | 15,350 | 23,500–35,000 | a parquet BATCH with `engine: row` |
| BATCH, columnar | 72,600 | 100,000–142,000 | the same BATCH through the columnar engine |

The columnar engine is about 4–5× the row path on this workload. The uuid column, the messy
values and the `_sdc_*`/policy bookkeeping still run per row, so it gains most on clean,
vectorisable data. The first baseline (2026-11-22) came from a 4-core developer machine
(6,099 / 9,186 / 40,055), below every CI runner, so the gate then caught only a collapse.

## Regression gate

`pytest -m bench tests/bench` runs in the CI job *Benchmarks* on every PR, and the numbers go
to the job summary. It fails when:

- columnar BATCH is less than 3× row-wise BATCH on the same runner (machine-independent;
  CI has measured 3.7–4.7×);
- any path falls under 60% of its baseline: a 40% loss on a slow runner, or about 70% on a
  fast one.

The absolute check applies only on CI (`CI` set): the baseline is a CI runner's, and a
developer machine may be slower. Locally the run prints the numbers and applies the
relative gate.

## Re-recording the baseline

When the workload or the engine changes on purpose:

1. Open the *Benchmarks* job of a few recent green runs on `main`, read their `rows/s` lines,
   and note which runner class each is (the two speeds are easy to tell apart).
2. Copy one slow-runner run's results into `tests/bench/baseline.json`: the job writes them
   to `bench-results.json` in the baseline's own format (run
   `BENCH_RESULTS=bench-results.json uv run pytest -m bench tests/bench -s` to see it
   locally), and the job summary shows the file. Keep `rows` unchanged unless the workload
   changed.
3. Update the table above, and say why in the pull request.
