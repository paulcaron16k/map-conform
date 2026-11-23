---
type: schema
title: "Conform spec (v1)"
description: "Grammar of the map-conform conform spec file: top level, defaults, streams, columns, chains, macros, UDFs."
resource: map_conform/spec/model.py
tags: [config, interface, active]
timestamp: 2026-11-23T18:00:00Z
sources:
  - path: docs/detailed-design.md
  - path: map_conform/spec/model.py
---

# Conform spec (v1)

Parent: [Wiki Index](../index.md)

Every key, with its type, default and meaning, is in the generated
[spec reference](../../docs/spec-reference.md), and the behaviour behind them is in detailed
design §3 (path:docs/detailed-design.md). Worked examples are in the
[cookbook](../../docs/cookbook.md). This page is the map.

- **Source.** The frozen dataclasses in `map_conform/spec/model.py` and
  `map_conform/spec/steps.py`. The JSON Schema (`map_conform/map-conform-spec.schema.json`,
  for editor completion) and the reference are generated from them; tests fail when either
  is stale. `map-conform spec validate` is the authority: it also checks CType grammar,
  step and `parse` options, expressions and type flow by compiling the plans.
- **Top level.** `version: 1`, `defaults`, `macros`, `udfs` (module paths need
  `allow_python_udfs`), `streams` (globs over tap stream names, or new output streams with
  `source`), and `else` (`keep` | `drop` for unmatched streams).
- **Defaults.** `naming`, `stream`, `values`, `timestamp`, `boolean`, `on_error`,
  `add_record_metadata`, `undeclared`, `nested`, `flatten`, `faker`, `engine`,
  `max_reject_rate`, `max_null_rate`. A stream rule may set any of them.
- **Columns.** Name, type and nullability; `source`, `expr`, `default`; `transform` and
  `parse`; value overrides; `max_length`, `on_overflow`, `enum`; `drop`, `doc`, `sql_type`;
  `when`; `fields`, `shape`, `flatten`; `engine`; `infer_type`.

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
