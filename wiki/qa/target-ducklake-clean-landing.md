---
type: resource
title: "target-ducklake with its cleanup off"
description: "WBS 11.2: map-conform's output into target-ducklake with the target's cleanup options off; what lands, what fails, and what the target could remove."
resource: tests/e2e/test_target_ducklake.py
tags: [qa, testing, contract, active]
timestamp: 2026-11-24T14:00:00Z
sources:
  - path: tests/e2e/test_target_ducklake.py
  - path: tests/e2e/lake_rows.py
  - path: wiki/concepts/clean-landing-contract.md
---

# target-ducklake with its cleanup off

Parent: [Wiki Index](../index.md) · Related: [Clean-Landing Contract](../concepts/clean-landing-contract.md) ·
[Test strategy](test-strategy.md)

WBS 11.2 (MAPC-68), 2026-11-24. Target: the paulcaron16k fork of target-ducklake, branch
`xflow_dev` at `ba226b0` (DuckDB 1.5.2, Singer SDK 0.46.4), with a SQLite catalog and local
storage.

## Method

The messy orders export (`tests/fixtures/streams/`) goes through map-conform with the spec of
the target-jsonl e2e test, then into target-ducklake with every cleanup option off and
validation on:

| target-ducklake setting | Value | Why |
| -- | -- | -- |
| `type_source` | unset | map-conform casts the values |
| `conform_column_names` | `false` | map-conform conforms the names |
| `auto_cast_timestamps` | `false` | map-conform declares the formats |
| `value_type_checking` | `strict` | a value the column would round fails, not repaired |
| `validate_records` | `true` | records are asserted against the SCHEMA |
| `add_record_metadata` | `true` | keeps the `_sdc_*` columns (contract §4) |
| `default_target_schema` | `raw` | see *Stream names* below |

The lake is then read back (path:tests/e2e/lake_rows.py) and compared with what the mapper
wrote: every column's DuckDB type, and every value of every row, except the four `_sdc_*`
columns the Singer SDK in the target sets itself. Both runs are the e2e tests in
path:tests/e2e/test_target_ducklake.py, which pin the target's commit.

## Results

**RECORD: lands clean.** All 12 rows, every column in its declared type, every value as the
mapper wrote it:

| Column | DuckDB type | | Column | DuckDB type |
| -- | -- | -- | -- | -- |
| `order_id` | BIGINT | | `qty` | INTEGER |
| `order_date`, `ship_date` | DATE | | `unit_price` | DECIMAL(12,4) |
| `amount` | DECIMAL(12,2) | | `created_at_utc` | TIMESTAMP WITH TIME ZONE |
| `discount` | DECIMAL(6,4) | | `tracking_uuid` | UUID |
| `paid` | BOOLEAN | | others | VARCHAR |

**Parquet BATCH: fails, on two target bugs.** target-ducklake reads a BATCH parquet file back
into JSON forms and sends each row through its RECORD path:

- a `uuid` column (Arrow `arrow.uuid`, [ADR-0011](../decisions/0011-uuid-in-batch.md)) fails
  the stream: "A BATCH Parquet value of type UUID has no JSON form" (DUCKLKD-152);
- with `validate_records: true`, a decimal column fails validation: the SDK is handed a
  Python `Decimal` where the SCHEMA declares a string with `x-singer.decimal` (DUCKLKD-153).

With the uuid column declared `string` and validation off, the BATCH lake equals the RECORD
lake, value for value. The BATCH test is marked `xfail(strict=True)`, so it fails, as a
reminder to remove the mark, once both fixes are in the pinned commit.

## What target-ducklake could remove

From reading the target's code at `ba226b0` (file:line references are to that commit). On
map-conform's output these options do nothing, or only cost time:

| Target code | Setting (default) | With map-conform |
| -- | -- | -- |
| `type_source` / `on_error` (type_source.py) | unset | redundant: values are already cast |
| `conform_column_names` (conform.py) | `false` | redundant: names already pass `conform_name` unchanged |
| `auto_cast_timestamps` (flatten.py:61-91) | `false` | redundant; turned on, it could retype a column map-conform kept as text |
| `convert_tz_to_utc` (parquet_utils.py:338) | `false` | redundant: `timestamptz` values are UTC |
| unsized `x-singer.decimal` → VARCHAR (connector.py:213) | always | never reached: map-conform sends precision and scale |
| JSON text in object/array columns (flatten.py:473) | always, with a struct or list property | `json` columns are strings, so it ignores them, but it still copies and walks every record |
| `value_type_checking` rounding, number/text coercion (parquet_utils.py) | `permissive` | per-value no-ops on quantised values; could be assertions |
| SDK date-time parse, UTC re-render (parquet_utils.py:387) | always | per-value parse and re-render of text that is already canonical |

None of these can simply be deleted: the target also serves pipelines without map-conform,
and every one is off by default or a no-op on clean input. The useful changes are
performance changes, not removals:

- **BATCH files go back through the RECORD path row by row** (batch_files.py, target.py),
  with every per-value step above. A map-conform parquet file already has the staging types
  and could be staged nearly as is. That is DUCKLKD-119 (Arrow-native fast path), which
  would also remove DUCKLKD-152 and DUCKLKD-153's code path.
- The per-record and per-value no-ops could be skipped when a stream's SCHEMA is fully
  typed. That is worth doing only if profiling shows the cost.

## What the target keeps

The contract's §6: keys, merge, in-batch dedupe, ACTIVATE_VERSION, partitioning, staging
against existing tables (insert_casts.py), the case-fold name clash check (an assertion),
base64 → BLOB decoding, and `x-sql-datatype` → DuckDB type mapping. `flatten_max_level` and
`nested_types` are storage-shape choices; flattening (`> 0`) makes `a__b` names that
map-conform has not checked, so a pipeline that wants flat columns should flatten in
map-conform (`nested: flatten`).

## Things a pipeline must set

- **Stream names.** The target splits a stream name on `-` into schema and table. map-conform
  conforms `public-users` to `public_users`, so the split never applies; set
  `default_target_schema`, or the stream fails with "No schema name found".
- **`add_record_metadata: true`** on the target, or it drops map-conform's `_sdc_*` columns.
  With it on, the SDK in the target rewrites `_sdc_received_at`, `_sdc_batched_at`,
  `_sdc_sequence` and `_sdc_sync_started_at`; `_sdc_extracted_at`, `_sdc_table_version` and
  `_sdc_deleted_at` are kept from the messages.
- **Decimals wider than 38 digits** are capped to DuckDB's DECIMAL(38, s) with fewer fraction
  digits, and values are re-rounded with a warning (parquet_utils.py:76). That is a storage
  limit, not cleanup; declare such columns within 38 digits.
