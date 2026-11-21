---
type: component
title: "Spec loader"
description: "Conform spec model, strict loading, inheritance by presence, glob resolution, JSON Schema generation."
resource: map_conform/spec/
tags: [engineering, config, draft]
timestamp: 2026-11-21T00:00:00Z
sources:
  - path: docs/detailed-design.md
---

# Spec loader

Parent: [Wiki Index](../index.md) · Related: [Detailed design](../../docs/detailed-design.md)

> Status: **draft**. This describes the designed system. No code exists yet.

## Responsibilities

- Load YAML or JSON from `spec_path`, deep-merging the inline `spec` over it.
- Substitute `${var}` from `spec_vars` and `${env:NAME}` from the environment.
- **Strict** parse into frozen dataclasses. Unknown keys are errors, reported with their full
  path.
- **Inheritance by presence**:
  - order: `defaults` → matching globs, least to most specific → exact name;
  - objects merge and lists replace.
- Generate the JSON Schema from the model. The shipped file is
  `map_conform/map-conform-spec.schema.json`, and a test fails when it is stale.

## Why a file

Meltano passes plugin config through environment variables, each limited to ~128 KiB. Real
specs with many streams exceed that, so the spec is a file (detailed design §1).

See the [conform spec schema page](../schemas/conform-spec.md) for the grammar.
