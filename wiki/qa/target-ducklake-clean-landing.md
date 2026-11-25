---
type: resource
title: "target-ducklake with its cleanup off"
description: "WBS 11.2: map-conform's output into target-ducklake with the target's cleanup options off; what lands, what failed and was fixed, what is still open, and how it compares with target-postgres and target-snowflake."
resource: tests/e2e/test_target_ducklake.py
tags: [qa, testing, contract, active]
timestamp: 2026-11-25T18:00:00Z
sources:
  - path: tests/e2e/test_target_ducklake.py
  - path: tests/e2e/lake_rows.py
  - path: wiki/concepts/clean-landing-contract.md
---

# target-ducklake with its cleanup off

Parent: [Wiki Index](../index.md) · Related: [Clean-Landing Contract](../concepts/clean-landing-contract.md) ·
[Test strategy](test-strategy.md)

WBS 11.2 (MAPC-68). Target: the paulcaron16k fork of target-ducklake (branch `xflow_dev`),
DuckDB 1.5.2, with a SQLite catalog and local storage. First run 2026-11-24 at `ba226b0`;
re-run and reviewed 2026-11-25, after the target moved both paths onto DuckDB staging
(DUCKLKD-119 for BATCH, DUCKLKD-157 for RECORD), with the fixes of DUCKLKD-160.

## Method

The messy orders export (`tests/fixtures/streams/`) goes through map-conform with the spec of
the target-jsonl e2e test, plus a `json` column and a `decimal(50,10)` column, then into
target-ducklake with every cleanup option off and validation on:

| target-ducklake setting | Value | Why |
| -- | -- | -- |
| `type_source` | unset | map-conform casts the values |
| `conform_column_names` | `false` | map-conform conforms the names |
| `auto_cast_timestamps` | `false` | map-conform declares the formats |
| `value_type_checking` | `strict` | a value the column would round fails, not repaired |
| `validate_records` | `true` | records are asserted against the SCHEMA |
| `add_record_metadata` | `true` | keeps the `_sdc_*` columns (contract §4) |
| `default_target_schema` | `raw` | see *Things a pipeline must set* |

The lake is read back (path:tests/e2e/lake_rows.py) and compared with what the mapper wrote:
every column's DuckDB type, and every value of every row, except the four `_sdc_*` columns the
Singer SDK in the target sets itself. path:tests/e2e/test_target_ducklake.py runs it three
ways, RECORD messages and BATCH files in parquet and JSONL, against a pinned commit;
`MAP_CONFORM_TARGET_DUCKLAKE=<checkout>` runs it against a local checkout instead.

## Results

**All three land clean** at the pinned commit: 12 rows, every column in its declared type,
every value as the mapper wrote it.

| Column | DuckDB type | | Column | DuckDB type |
| -- | -- | -- | -- | -- |
| `order_id` | BIGINT | | `qty` | INTEGER |
| `order_date`, `ship_date` | DATE | | `unit_price` | DECIMAL(12,4) |
| `amount` | DECIMAL(12,2) | | `created_at_utc` | TIMESTAMP WITH TIME ZONE |
| `discount` | DECIMAL(6,4) | | `tracking_uuid` | UUID |
| `paid` | BOOLEAN | | `line` | JSON |
| `amount_wide` | DECIMAL(38,9) | | others | VARCHAR |

How it got there:

| Date, target commit | RECORD | Parquet BATCH | JSONL BATCH |
| -- | -- | -- | -- |
| 2026-11-24, `ba226b0` | clean | fails: uuid has "no JSON form" (DUCKLKD-152); decimals fail `validate_records` (DUCKLKD-153) | not run |
| 2026-11-25, `2f2a405` (DuckDB BATCH path) | clean | wide decimal loads 1234.5 as 20711473152; `json` stored as a JSON string of its text | `json` stored as a JSON string |
| 2026-11-25, DUCKLKD-160 | clean | clean | clean |

The `2f2a405` failures loaded wrong values with no error. Neither the target's equivalence
tests (whose Parquet files are typed as the Singer SDK infers them) nor the first version of
this test (no `json`, no decimal over 38 digits) had such a column.

## Review of the target at `2f2a405`

Three reviews: the BATCH path, the RECORD path (old against new on about 25 differential
probes), and a comparison with MeltanoLabs target-postgres and target-snowflake.

**Fixed in DUCKLKD-160**, all silent wrong values on BATCH:

- a Parquet `decimal256` column is read by pyarrow as exact text and cast as text is
  (DuckDB's reader turns it into a wrong DOUBLE); one inside a struct or list is refused;
- text in a JSON column whose property is a string is the JSON it holds, as for records;
- a directory named like a hive partition (`day=…/`, `id=7/`) no longer adds or overrides
  a column;
- a manifest path's `*`, `?` and `[` name that file, not a glob of others;
- a percent-encoded `file://` URL is decoded when only the decoded path exists.

**Open, for target-ducklake's board:**

| Path | Finding | Impact |
| -- | -- | -- |
| BATCH | a JSONL row missing a key property loads with a NULL key; RECORD raises | silent, keyed streams |
| BATCH | a zero-row Parquet file without the key column is refused | loud |
| BATCH | a tz-aware Parquet timestamp into a naive TIMESTAMP column stores UTC wall time; RECORD drops the offset | parity, not map-conform's types |
| BATCH | `record_count` counts rows after the key dedup | metrics |
| BATCH | reads from object storage aren't retried, the load is | transient failures |
| RECORD | nested or flattened TIMESTAMPTZ leaves no longer accept ISO forms only Python reads (`20240101T100000Z`), while the README still promises them | loud; messy taps only |
| RECORD | integer and boolean columns now accept `0x10`, `0b101`, `yes`, `t` | silent widening |
| RECORD | invalid JSON in a new hinted JSON column fails at the insert without naming the column | message |
| both | each staging connection gets the lake's full `memory_limit`, so parallel drains can use several times it | memory |
| both | a retried `BEGIN…COMMIT` after an IO error that hid a successful commit duplicates an append | rare |

**For map-conform's output the target is now sufficient**: every type the contract's §5
lists loads exactly by RECORD, Parquet and JSONL, checked by this test and by the reviews'
probes (uuid at the top level and in structs, time, naive and UTC timestamps, binary,
decimal128, lists of decimals, structs). The open items above touch messy taps or edge
cases, not the contract's types, except the JSONL missing-key case, which map-conform never
produces (its files always carry every column).

## Compared with target-postgres and target-snowflake

| | target-ducklake | target-postgres | target-snowflake |
| -- | -- | -- | -- |
| RECORD load | JSON lines staged by DuckDB: flatten, cast, dedupe in SQL | Python per record, `INSERT` (COPY optional) into a temp table | Python per record, gzip JSONL, PUT + `COPY`/`MERGE` with casts |
| BATCH | native, JSONL and Parquet read by DuckDB, drained after earlier records | SDK default: files read back into Python | native for JSONL; Parquet not implemented |
| `number` | DECIMAL(38,9) | unbounded NUMERIC | DOUBLE |
| Duplicate keys | last row wins, deterministic; NULL keys match | last in a dict; NULL keys never match | `SEQ8()` order, not guaranteed; NULL keys never match |
| Type change in an existing table | cast, each batch checked first | refused | `ALTER` where Snowflake allows it |
| Overwrite | staged, replaced at the end, STATE held | not supported | truncate at the start |

target-ducklake is ahead on BATCH, dedup and type-change safety, and keeps the most work out
of Python. It is behind target-postgres on decimal precision (DECIMAL(38,9) for an unsized
`number`; map-conform always sizes its decimals, so its output isn't affected) and on
atomicity (DDL is committed before the data).

## What the target could still drop

None of the target's cleanup options can simply be deleted: it serves pipelines without
map-conform too, and each is off by default or a no-op on clean input (`type_source`,
`conform_column_names`, `auto_cast_timestamps`, `convert_tz_to_utc`). The cost that mattered,
BATCH files re-read row by row through Python, is gone with DUCKLKD-119. What is left per
record is the SDK's validation and date parsing and one JSON line, which DUCKLKD-157 has
reduced; skipping them for a fully typed SCHEMA is worth doing only if profiling shows it.

## Things a pipeline must set

- **Stream names.** The target splits a stream name on `-` into schema and table. map-conform
  conforms `public-users` to `public_users`, so the split never applies; set
  `default_target_schema`, or the stream fails with "No schema name found".
- **`add_record_metadata: true`** on the target, or it drops map-conform's `_sdc_*` columns.
  With it on, the SDK in the target rewrites `_sdc_received_at`, `_sdc_batched_at`,
  `_sdc_sequence` and `_sdc_sync_started_at`; `_sdc_extracted_at`, `_sdc_table_version` and
  `_sdc_deleted_at` are kept from the messages.
- **Decimals wider than 38 digits** load into DuckDB's DECIMAL(38, s) with fewer fraction
  digits, with a warning, and a value the narrower column would round follows
  `value_type_checking`. That is a storage limit, not cleanup; declare such columns within 38
  digits.
