---
type: architecture_doc
title: "Architecture overview"
description: "Context, components and message flow of map-conform."
resource: map_conform/
tags: [architecture, draft]
timestamp: 2026-11-21T00:00:00Z
sources:
  - path: docs/architecture-hld.md
---

# Architecture overview

Parent: [Wiki Index](../index.md) · Related: [Detailed design](../../docs/detailed-design.md)

> Status: **draft**. This describes the designed system. No code exists yet.

The authoritative design is [docs/architecture-hld.md](../../docs/architecture-hld.md)
(path:docs/architecture-hld.md). This page summarises it for navigation.

| Layer | Package | Page |
|---|---|---|
| Mapper and dispatch | `map_conform/mapper.py` | this page |
| Conform spec | `map_conform/spec/` | [Spec loader](../components/spec-loader.md) |
| Names | `map_conform/naming/` | [Name conformer](../components/name-conformer.md) |
| Types, builtins, expr, UDF | `map_conform/types/`, `transforms/`, `expr/`, `udf/` | [Type system & builtins](../components/type-system-and-builtins.md) |
| Plan and executors, BATCH I/O | `map_conform/plan/`, `batch/` | [Execution engines](../components/execution-engines.md) |
| Metadata, errors, metrics | `metadata.py`, `errors.py`, `metrics.py` | [Metadata & errors](../components/metadata-and-errors.md) |

## Message handling

| Message | Effect |
|---|---|
| SCHEMA | Compile the StreamPlan; emit the conformed, declared SCHEMA including `_sdc_*` |
| RECORD | Row executor + metadata; preserve `time_extracted` and `version` |
| BATCH | Columnar executor per file; new manifest (or RECORDs when `batch_output.mode: record`) |
| STATE | Pass through, in order |
| ACTIVATE_VERSION | Rename the stream, pass through |
