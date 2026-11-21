---
type: decision_log
title: "Decision 0003 — Own conform spec, bridge to Zamboni and catalogs"
description: "map-conform owns a versioned logical spec file; it imports from catalogs and Zamboni and exports column types to Zamboni."
resource: creating-a-better-mapper-guidance.md
tags: [architecture, decision, active]
timestamp: 2026-11-21T00:00:00Z
sources:
  - path: creating-a-better-mapper-guidance.md
---

# Decision 0003 — Own conform spec, bridge to Zamboni and catalogs

Parent: [Wiki Index](../index.md) · Related: [Architecture overview](../architecture/overview.md)

Status: **Accepted** (2026-11-21, planning quiz)

## Context
- Meltano passes plugin config through the environment, and each variable is limited to about
  128 KiB.
- Zamboni table-config is a *physical* layout spec. Its `columns` block is an unstructured
  `{name: type-string}` that nothing reads.
- The stream_maps shape is too cramped for rich column metadata.

## Decision
- A versioned YAML/JSON **conform spec**, referenced by `spec_path`.
- Parsing is strict and inheritance is by presence (the Zamboni pattern).
- The JSON Schema is generated from the dataclasses.
- `spec import` reads a Singer catalog and Zamboni `columns`. `spec export` writes each
  column's canonical type into Zamboni `columns`.

## Consequences
- Logical concerns (names, types, values) and physical concerns (layout, maintenance) stay
  separate.
- There is one canonical type vocabulary, defined in [type system](../components/type-system-and-builtins.md).
