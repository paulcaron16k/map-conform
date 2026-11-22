---
type: component
title: "Execution engines and BATCH I/O"
description: "Plan compiler, row executor, columnar (Arrow/polars) executor, BATCH manifest and file I/O."
resource: map_conform/plan/
tags: [engineering, performance, draft]
timestamp: 2026-11-22T18:00:00Z
sources:
  - path: docs/detailed-design.md
---

# Execution engines and BATCH I/O

Parent: [Wiki Index](../index.md) · Related: [Detailed design](../../docs/detailed-design.md)

> Status: **draft**.
>
> - **Built (P2):** the plan compiler (`map_conform/plan/compile.py`) and the row executor
>   (`map_conform/plan/row.py`), wired into the mapper. RECORD streams are conformed end to end.
> - **Built (P3):** derived columns computed in dependency order, the stream `filter`, and
>   SDK flattening of records (`map_conform/naming/flatten.py`).
> - **Not yet:** the columnar BATCH executor (P4). BATCH messages are refused with a clear
>   message until then.

## Plan

Compiled once per SCHEMA. A `StreamPlan` holds:
- ordered `ColumnPlan`s, each with name, CType, sources, bound steps, `vectorised`, `reads`,
  `on_error`, `nullable` and `default`;
- the output JSON Schema;
- the output Arrow schema.

## Row executor

- Composed closures, with a fast path when the value already has the target type.
- Used for RECORD, and for row-wise columns inside BATCH.

## Columnar executor ([ADR-0004](../decisions/0004-batch-engine.md))

- Vectorised columns run as `pyarrow.compute` chains, or as polars expressions with the
  `[polars]` extra.
- Row-wise columns convert only their `reads` set with `to_pylist`, run the row closure, and
  are rebuilt with `pa.array(type=)`.
- `case` is lowered to masks plus `case_when`.
- Rejects become a mask, and the rejected rows go to the reject sink.

## BATCH I/O

- Manifest URIs are read through fsspec: parquet with `iter_batches`, JSONL in line blocks with
  explicit string types.
- Output is parquet (zstd) by default, written with the declared schema, one output file per
  input file.
- `batch_output.mode: record` emits RECORDs instead.

## Parity

Every corpus case runs through both executors, and the outputs must match in canonical JSON
form.
