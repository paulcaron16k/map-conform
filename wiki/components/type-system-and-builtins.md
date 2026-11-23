---
type: component
title: "Type system, builtins, expressions and UDFs"
description: "Canonical CType vocabulary, builtin transform catalogue, expression language and UDF registry."
resource: map_conform/types/
tags: [engineering, types, active]
timestamp: 2026-11-23T18:00:00Z
sources:
  - path: docs/detailed-design.md
---

# Type system, builtins, expressions and UDFs

Parent: [Wiki Index](../index.md) · Related: [Detailed design](../../docs/detailed-design.md)

> Status: **active**.
>
> - **Built (P2):** the CType system (`map_conform/types/`), every builtin and cast
>   (`map_conform/transforms/`), macros, and the chain compiler (`map_conform/plan/chain.py`).
> - **Built (P3):** the expression language (`map_conform/expr/`), `case`, `when` and
>   `fields` (`map_conform/plan/ops.py`), UDFs (`map_conform/udfs.py`), masking parity and
>   Faker, and stream-map compatibility (`map_conform/spec/stream_maps.py`).
> - **Built (P4):** Arrow and polars kernels for some casts and text steps
>   (`map_conform/transforms/vector.py`, `map_conform/transforms/polars_vector.py`); see
>   [Execution engines](execution-engines.md). `map-conform functions` lists which.

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
   (detailed design §6). Each declares kwargs, the stages it accepts and produces, and a
   scalar implementation; vector kernels live in separate tables, keyed by step name or
   cast kind.
2. **Macros.** Named, parameterised chains of steps.
3. **`expr`.** An AST-whitelisted Python subset, compiled to closures, a superset of SDK
   stream-map expressions. Names resolve at compile time; columns are their conformed values.
   The library has predicates (`is_string`, `is_datetime`, …), coercions, temporal and text
   helpers (`map-conform functions` lists them). Conditionals are the `case` step form or
   a ternary inside an expression. The sandbox
   (`map_conform/expr/sandbox.py`) bounds attributes, modules and sizes.
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
paths. Every pipelinewise type has a test, including where pipelinewise is buggy
(`tests/transforms/test_masking.py`).

## Stream-map compatibility

`map_conform/spec/stream_maps.py` translates the SDK settings (`stream_maps`,
`stream_map_config`, `faker_config`, `flattening_*`) into the spec, with compatibility
defaults that keep meltano-map-transformer's output ([ADR-0010](../decisions/0010-stream-map-superset.md)).
Every case of the SDK's own mapper tests passes through both mappers with the same result,
up to documented differences (`tests/compat/`). The full table is in detailed design §15.

**The implicit cast.** Every chain ends with a cast to the declared type, so `expr` results
are coerced. Only translated stream maps infer a type from an expression's prefix
(`infer_type: sdk`), as the SDK does.
