---
type: component
title: "Metadata, errors and metrics"
description: "SDK-exact _sdc_* columns, ConformError and on_error policies, reject sink, rate thresholds, metrics."
resource: map_conform/metadata.py
tags: [engineering, observability, active]
timestamp: 2026-11-22T12:00:00Z
sources:
  - path: map_conform/metadata.py
  - path: map_conform/errors.py
  - path: map_conform/rejects.py
  - path: map_conform/metrics.py
  - path: docs/detailed-design.md
---

# Metadata, errors and metrics

Parent: [Wiki Index](../index.md) · Related: [Detailed design](../../docs/detailed-design.md)

## `_sdc_*` ([ADR-0005](../decisions/0005-sdc-metadata.md))

`map_conform/metadata.py` matches the Singer SDK exactly. A test calls the SDK's own
`Sink._add_sdc_metadata_to_record` and `_add_sdc_metadata_to_schema`.

| Column | Value |
|---|---|
| extracted_at | message `time_extracted` |
| received_at | now, UTC `isoformat()` |
| batched_at | RECORD: mapper start; BATCH (P4): input file last-modified |
| deleted_at | the record's own value, conformed to UTC |
| sequence | `round(time.time()*1000)` |
| table_version | message `version` |
| sync_started_at | mapper start, epoch ms |

- The tap's own `_sdc_*` properties feed these columns, not ordinary columns.
- Downstream SDK targets need `add_record_metadata: true`.

## Errors ([ADR-0006](../decisions/0006-error-policy.md))

- **`ConformError`** (`map_conform/errors.py`) names the stream, column, row, value and rule,
  and says what to do about it.
- **`on_error`** is one of:
  - `raise`, the default;
  - `null`, except that a null in a `nullable: false` column is always an error;
  - `keep`, for string and json columns only;
  - `reject`.
- **Rejected rows** go to `map_conform/rejects.py`'s sink:
  `<reject.storage>/<stream>/<run id>.jsonl|.parquet`, with the error and the whole raw record.
- **Thresholds.** `max_reject_rate` and `max_null_rate` (Defaults keys, so per stream) are
  checked before each STATE passes and at end of input. Going over one fails the run.

## Metrics

`map_conform/metrics.py` keeps per-output-stream counters:
- `rows_in`, `rows_out`, `rows_rejected`, `rows_nulled`, `values_kept`;
- `errors` by (column, rule).

They are logged at the end of the run, and written to `metrics_path` when set. Filtered rows
(P3) and row-wise BATCH columns (P4) are added with those features.
