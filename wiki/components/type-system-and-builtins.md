---
type: component
title: "Type system, builtins, expressions and UDFs"
description: "Canonical CType vocabulary, builtin transform catalogue, expression language and UDF registry."
resource: map_conform/types/
tags: [engineering, types, draft]
timestamp: 2026-11-22T12:00:00Z
sources:
  - path: docs/detailed-design.md
---

# Type system, builtins, expressions and UDFs

Parent: [Wiki Index](../index.md) · Related: [Detailed design](../../docs/detailed-design.md)

> Status: **draft**.
>
> - **Built (P2):** the CType system (`map_conform/types/`), every builtin and cast
>   (`map_conform/transforms/`), macros, and the chain compiler (`map_conform/plan/chain.py`).
> - **Not yet:** `expr`, `case`, `when` and UDFs (P3), stream-map compatibility (P3), and
>   `mask_number`, `mask_hidden`, `tokenize`, `fake` and nested `fields` (E12).

## Canonical types

The full table is in detailed design §4.

| CType | JSON Schema (contract) | Arrow |
|---|---|---|
| boolean | boolean | bool |
| int16 / int32 / int64 | integer + bounds | int16/32/64 |
| float32 / float64 | number | float32/64 |
| decimal(p,s) | string `x-singer.decimal` + precision/scale | decimal128(p,s) |
| string(n) | string (+maxLength) | string |
| date / time | string date / time | date32 / time64[us] |
| timestamp / timestamptz | string date-time + `x-sql-datatype` | timestamp[us] / timestamp[us, UTC] |
| uuid / binary / json | uuid / base64 / string json-text | arrow.uuid / binary / string |
| struct<…> / list<T> | object / array | struct / list |

## Transform tiers ([ADR-0002](../decisions/0002-transform-authoring.md))

1. **Builtins.** Text, numeric, temporal, boolean/json/binary/uuid and privacy transforms
   (detailed design §6). Each declares kwargs, type constraints, and a scalar implementation
   plus an optional Arrow one.
2. **Macros.** Named, parameterised chains of steps.
3. **`expr`.** An AST-whitelisted Python subset, a superset of SDK stream-map expressions.
   It provides predicates (`is_string`, `is_datetime`, …), coercions and temporal helpers,
   with `case` when/then/else.
4. **UDFs.** Registered with `@udf`, by entry point `map_conform.functions`, or by module path
   behind `allow_python_udfs`.

## Masking and privacy ([ADR-0010](../decisions/0010-stream-map-superset.md))

| Builtin | pipelinewise equivalent |
|---|---|
| `set_null` | SET-NULL |
| `hash` (`skip_first`) | HASH, HASH-SKIP-FIRST-n |
| `redact_date` | MASK-DATE |
| `mask_number` | MASK-NUMBER |
| `mask_hidden` | MASK-HIDDEN |
| `mask` (`keep_first`, `keep_last`) | MASK-STRING-SKIP-ENDS-n |
| `tokenize`, `fake` | none (`fake` is in SDK stream maps) |

A `when` expression on a column or step applies masking conditionally. `fields` reaches nested
paths.

## Stream-map compatibility

`map_conform/compat/` translates the SDK settings (`stream_maps`, `stream_map_config`,
`faker_config`, `flattening_*`) into the spec. The full table is in detailed design §15.

**The implicit cast.** Every chain ends with a cast to the declared type, so `expr` results
are coerced. Nothing is inferred from an expression's prefix.
