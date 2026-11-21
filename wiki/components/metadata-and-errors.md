---
type: component
title: "Metadata, errors and metrics"
description: "SDK-exact _sdc_* columns, ConformError and on_error policies, reject sink, metrics."
resource: map_conform/metadata.py
tags: [engineering, observability, draft]
timestamp: 2026-11-21T00:00:00Z
sources:
  - path: docs/detailed-design.md
---

# Metadata, errors and metrics

Parent: [Wiki Index](../index.md) · Related: [Detailed design](../../docs/detailed-design.md)

> Status: **draft**. This describes the designed system. No code exists yet.

## `_sdc_*` ([ADR-0005](../decisions/0005-sdc-metadata.md))

| Column | Value |
|---|---|
| extracted_at | message `time_extracted` |
| received_at | now |
| batched_at | BATCH: input file last-modified; RECORD: mapper start |
| deleted_at | preserved |
| sequence | epoch ms |
| table_version | message `version` |
| sync_started_at | mapper start, epoch ms |

Downstream SDK targets need `add_record_metadata: true`.

## Errors ([ADR-0006](../decisions/0006-error-policy.md))

- A `ConformError` names the stream, column, source column, row number, value and rule.
- `on_error` is one of `raise` (default), `null`, `keep` or `reject`.
- `max_reject_rate` and `max_null_rate` set per-stream thresholds.

## Metrics

Per-stream counters:
- rows in, out, filtered and rejected;
- nulls produced by each rule;
- lossy renames;
- row-wise fallbacks in BATCH.

They are written as log lines, and to `metrics_path` when it is set.
