---
type: decision_log
title: "Decision 0011 — UUID as Parquet UUID logical type in BATCH"
description: "uuid columns are written to parquet as fixed_len_byte_array(16) with the UUID logical type; RECORD keeps the canonical string."
resource: docs/detailed-design.md
tags: [architecture, decision, active]
timestamp: 2026-11-23T16:00:00Z
sources:
  - path: docs/detailed-design.md
---

# Decision 0011 — UUID as Parquet UUID logical type in BATCH

Parent: [Wiki Index](../index.md) · Related: [Architecture overview](../architecture/overview.md)

Status: **Accepted** (2026-11-21, planning review)

## Context
Parquet's UUID logical type annotates `fixed_len_byte_array(16)`, and Iceberg stores uuid as
`fixed[16]`. This was checked on 2026-11-21: pyarrow 26 writes the `arrow.uuid` extension type
as `fixed_len_byte_array(16) (UUID)`, and DuckDB reads it back as `UUID`.

## Decision
- In BATCH, a `uuid` column is `arrow.uuid` in memory and parquet FLBA(16) with the UUID
  logical type on disk.
- RECORD (JSON) keeps the canonical lowercase dashed string with `format: uuid`.
- A string encoding for readers without UUID logical-type support was planned as `uuid_as:
  string`; in 0.1.0 it exists only inside `to_arrow` and is not a setting.

## Consequences
- Files are 16 bytes per value instead of 36, and sort and compare natively.
- Targets reading BATCH through `to_pylist()` receive `bytes`/`UUID` objects. The
  [contract](../concepts/clean-landing-contract.md) says so.
