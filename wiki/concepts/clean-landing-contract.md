---
type: concept
title: Clean-Landing Contract
description: "What a target may assume about SCHEMA, RECORD and BATCH output from map-conform, and the reviewer instruction for targets."
resource: map_conform/types/to_jsonschema.py
tags: [engineering, contract, draft]
timestamp: 2026-11-22T12:00:00Z
sources:
  - path: docs/detailed-design.md
  - path: creating-a-better-mapper-guidance.md
---

# Clean-Landing Contract

Parent: [Wiki Index](../index.md) · Related: [Wire encoding ADR](../decisions/0007-wire-encoding.md) ·
[Naming ADR](../decisions/0008-naming-defaults.md) · [_sdc_ ADR](../decisions/0005-sdc-metadata.md)

> Status: **draft**. The RECORD path delivers this contract as of P2 (types, values,
> names, `_sdc_*`); BATCH delivers it from P4. Changing it needs an ADR.

Every guarantee below has a contract test in `tests/contract/` (planned: WBS 4.3, 5.8, 8.2).

## 1. Names

| Guarantee | Detail |
|---|---|
| Grammar | Stream, column and struct-member names match `^[a-z_][a-z0-9_]*$` (with the default `case: snake`) |
| Length | At most `max_length`, default 63 |
| Reserved | Not a reserved word in ANSI, Postgres or DuckDB |
| Unique | Unique within a stream (and within a struct) under case folding |
| References | `key_properties`, `bookmark_properties` and `required` use the conformed names |

## 2. SCHEMA

- Each property has exactly one non-null JSON type, plus `"null"` when it is nullable.
- No `anyOf`, `oneOf`, `allOf` or `$ref`.
- Type metadata is canonical (see the [type table](../components/type-system-and-builtins.md)):
  - `format`: `date-time`, `date`, `time`, `uuid`
  - `x-sql-datatype`: canonical name (a hint only)
  - decimals: `{"type":["string","null"],"format":"x-singer.decimal","precision":p,"scale":s}`
  - integer width: `minimum`/`maximum`
  - binary: `contentEncoding: base64`
  - json: string with `x-sql-datatype: json`
- `_sdc_*` columns are declared (see §4).

## 3. RECORD values

| Declared type | Value on the wire |
|---|---|
| `timestamptz` | ISO-8601 UTC, `YYYY-MM-DDTHH:MM:SS.ffffffZ` |
| `timestamp` | ISO-8601, no offset |
| `date` / `time` | ISO-8601 |
| `decimal(p,s)` | string, exactly `s` fraction digits, at most `p` digits, never NaN or Inf |
| `int*` | JSON integer within the declared bounds |
| `float*` | finite JSON number, or null |
| `boolean` | JSON boolean |
| `string` | string, trimmed by default; `""` only when `empty_string_for_string: keep` |
| `uuid` | lowercase canonical with dashes |
| `binary` | base64 (strict) |
| `json` | JSON text |
| `struct` / `list` | typed nested values that follow these same rules |

- No empty string appears in a non-string column.
- No property is missing: a declared column is always present, possibly as null.
- `time_extracted` and `version` are preserved from the input.

## 4. Metadata

- The seven SDK `_sdc_*` columns are present, with SDK semantics.
- `_sdc_batched_at` is the input file's last-modified time for BATCH, and the mapper start
  time for RECORD.
- SDK targets **must** set `add_record_metadata: true`, or they strip the columns.

## 5. BATCH

- Files are parquet (default, zstd) or JSONL.
- The parquet schema equals the declared Arrow schema:
  - `decimal128(p,s)`
  - `timestamp[us, UTC]`
  - `timestamp[us]`
  - `date32`
  - `time64[us]`
  - `json` as string
  - `uuid` as `fixed_len_byte_array(16)` with the Parquet UUID logical type (Arrow `arrow.uuid`),
    unless the spec sets `uuid_as: string` ([ADR-0011](../decisions/0011-uuid-in-batch.md))
- Each file in the manifest belongs to the stream named in the message.

## 6. What a target still owns

Table semantics:
- keys, merge/upsert and in-batch dedupe;
- ACTIVATE_VERSION handling;
- partitioning;
- schema evolution against an *existing* table, e.g. TRY_CAST checks against older column
  types;
- storage type mapping (a direct lookup, no hint parsing).

## 7. Reviewer instruction (for target repos)

> This target receives data through map-conform and relies on its Clean-Landing Contract.
> Assume names are conformed, types are declared and values are already cast. Do **not**
> suggest or add value cleanup, string parsing, timestamp normalisation, decimal quantisation,
> name conforming, or `_sdc_*` handling in this target. A target may still validate cheaply
> (assert, not repair) and must still own table semantics (keys, merge, dedupe, schema
> evolution, partitioning). If clean data is not being delivered, file the gap against
> map-conform.
