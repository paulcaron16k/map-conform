---
type: component
title: "Spec loader"
description: "Conform spec model, strict loading, inheritance by presence, glob resolution, JSON Schema generation, catalog checks."
resource: map_conform/spec/
tags: [engineering, config, active]
timestamp: 2026-11-22T10:00:00Z
sources:
  - path: map_conform/spec/model.py
  - path: map_conform/spec/load.py
  - path: map_conform/spec/check.py
  - path: docs/detailed-design.md
---

# Spec loader

Parent: [Wiki Index](../index.md) · Related: [Detailed design](../../docs/detailed-design.md) ·
[Conform spec](../schemas/conform-spec.md)

## Modules

| Module | Does |
|---|---|
| `map_conform/spec/model.py` | Frozen dataclasses: `Spec`, `Defaults`, `StreamSpec`, `ColumnSpec`, `FieldSpec`; `parse_spec` |
| `map_conform/spec/steps.py` | `Chain`, `CallStep`, `ExprStep`, `CaseStep`, `Macro` |
| `map_conform/spec/_struct.py` | One set of type hints drives strict parsing, dumping and the JSON Schema |
| `map_conform/spec/load.py` | Read YAML/JSON, merge the inline spec, substitute variables, resolve streams |
| `map_conform/spec/jsonschema.py` | The generated schema; shipped as `map_conform/map-conform-spec.schema.json` |
| `map_conform/spec/check.py` | `spec validate --catalog` and `spec explain`; the column naming the plan reuses |
| `map_conform/plan/validate.py` | `spec validate` compiles every plan, with or without a catalog |

## Behaviour

- **Strict parse.** Unknown keys are errors, bools are not ints, and every problem is
  reported in one pass with its path, e.g. `streams["Orders Export"].columns["Order ID"].type`.
- **YAML 1.2 scalars** (path:map_conform/spec/load.py). `yes`/`no`/`on`/`off`/`NO`, `1:30`
  and dates stay strings, and a duplicate key is an error. PyYAML's global loader is
  untouched.
- **Substitution**:
  - `${name}` from `spec_vars`, `${env:NAME}` from the environment, and `:-default` as a
    fallback;
  - `$${` writes a literal `${`;
  - a macro's own params are left for expansion;
  - unknown names are reported with their paths.
- **Inheritance by presence**:
  - order: `defaults` → matching globs (case-sensitive), least to most specific → exact name;
  - objects merge (including columns, per key) and lists replace;
  - `source` keys are new output streams that inherit from `defaults` only;
  - `else: drop` drops unmatched streams.
- **Step grammar.** In mapping form, the first key other than `when` names the step.
- **Start-up.** The mapper loads and validates the spec before reading input. Problems
  surface as Singer SDK config errors (logged with their paths, exit 1).

## Why a file

Meltano passes plugin config through environment variables, each limited to ~128 KiB. Real
specs with many streams exceed that, so the spec is a file (detailed design §1). A test loads
a 128+ KiB spec through `spec_path`.

See the [conform spec schema page](../schemas/conform-spec.md) for the grammar.
