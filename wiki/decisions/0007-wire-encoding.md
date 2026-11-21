---
type: decision_log
title: "Decision 0007 — Wire encoding of decimals, JSON and nested data"
description: "Decimals as string x-singer.decimal with precision/scale; json columns as JSON text; declared struct/list emitted typed."
resource: creating-a-better-mapper-guidance.md
tags: [architecture, decision, active]
timestamp: 2026-11-21T00:00:00Z
sources:
  - path: creating-a-better-mapper-guidance.md
---

# Decision 0007 — Wire encoding of decimals, JSON and nested data

Parent: [Wiki Index](../index.md) · Related: [Architecture overview](../architecture/overview.md)

Status: **Accepted** (2026-11-21, planning quiz)

## Context
Few targets honour `x-sql-datatype`, and those that do implement it differently.

## Decision
- `decimal(p,s)` is emitted as `{"type":["string","null"],"format":"x-singer.decimal","precision":p,"scale":s}`,
  with the value as a string already quantized to `s`. In BATCH it is `decimal128(p,s)`.
- `json` is emitted as JSON **text**.
- A declared `struct<…>` or `list<T>` is emitted as typed nested values with conformed member
  names.
- Undeclared objects and arrays follow `nested: json | flatten | keep`, with `json` as the
  default.
- `x-sql-datatype` is still emitted as a hint, but it is never the only carrier of meaning.

## Consequences
- Decimals are exact through any JSON reader.
- Targets have to map `x-singer.decimal`. Both surveyed targets already do.
