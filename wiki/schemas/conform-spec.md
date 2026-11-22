---
type: schema
title: "Conform spec (v1)"
description: "Grammar of the map-conform conform spec file: top level, defaults, streams, columns, chains, macros, UDFs."
resource: map_conform/spec/model.py
tags: [config, interface, active]
timestamp: 2026-11-22T10:00:00Z
sources:
  - path: docs/detailed-design.md
  - path: map_conform/spec/model.py
---

# Conform spec (v1)

Parent: [Wiki Index](../index.md)

The model is `map_conform/spec/model.py`, and the JSON Schema generated from it is
`map_conform/map-conform-spec.schema.json`; editors can use it for completion. `map-conform
spec validate` is the authority, since it also checks CType grammar and step forms. Detailed
design §3 is the reference (path:docs/detailed-design.md).

## Top level

| Key | Meaning |
|---|---|
| `version: 1` | Required; pinned |
| `defaults` | Naming, stream, values, timestamp, boolean, on_error, metadata, undeclared, nested, flatten |
| `macros` | `{name: {params?, steps}}` |
| `udfs` | `{name: "module:attr"}` (needs `allow_python_udfs`) |
| `streams` | `{glob: StreamSpec}` (or a new output-stream name when `source` is set) |
| `else` | `keep` \| `drop`: streams that match no key |

## StreamSpec

| Key | Meaning |
|---|---|
| `alias` | Final stream name (string or `{expr}`) |
| `source` | Makes this key a new output stream projected from a tap stream (split or copy) |
| `prefix` | Stream name prefix |
| `key_properties` | Overrides the tap's keys |
| `filter` | Expression over **conformed** names; a falsy result drops the row |
| `columns` | `{name: ColumnSpec}` |
| `order` | Output column order |
| `drop` | Drop the whole stream |
| any Defaults key | Overrides that default for this stream |

## ColumnSpec

| Key | Meaning |
|---|---|
| `name` | Output name |
| `type` | Declared CType |
| `nullable` | Default true |
| `source` | Source column(s); a list means coalesce |
| `expr` | Derived value |
| `default` | Value when missing or null |
| `transform` | Chain of steps |
| `parse` | Cast kwargs |
| `true_values`, `false_values`, `null_tokens`, `trim`, `on_error` | Column-level overrides |
| `max_length` | String length limit |
| `enum` | Allowed values |
| `drop` | Remove the column |
| `doc` | Documentation, copied to the SCHEMA and the Zamboni export |
| `sql_type` | Overrides the emitted `x-sql-datatype` hint |
| `when` | Apply the chain only where the expression is truthy |
| `fields` | Transforms on nested paths of struct/json columns |

## Step forms

| Form | Example |
|---|---|
| bare name | `trim` |
| `{builtin: kwargs}` | `{strip_chars: "$, "}` |
| macro | `money` |
| `{expr: "..."}` | `{expr: "value.replace('O', '0')"}` |
| `{case: [{when, then}…, {else}]}` | conditional |
| `{udf: kwargs}` | `{fiscal_week: {start_month: 7}}` |

Any mapping-form step may carry `when: <expr>`.

SDK `stream_maps` settings are also accepted and translated (detailed design §15).

## Rules

- Unknown keys are errors; every problem is reported with its path.
- YAML is read with YAML 1.2 scalars: only `true`/`false` are booleans.
- In a mapping step, the first key other than `when` names the step.
- Objects merge and lists replace.
- The most specific glob wins.
- An implicit cast to the declared `type` ends every chain.

## Example

See [guidance §5](../../creating-a-better-mapper-guidance.md#5-the-conform-spec-summary).
