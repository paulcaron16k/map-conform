---
type: architecture_doc
title: "Architecture overview"
description: "Context, components and message flow of map-conform."
resource: map_conform/
tags: [architecture, active]
timestamp: 2026-11-23T18:00:00Z
sources:
  - path: docs/architecture-hld.md
---

# Architecture overview

Parent: [Wiki Index](../index.md) · Related: [Detailed design](../../docs/detailed-design.md)

The full module tree, the message flow and the BATCH path are in
[docs/architecture-hld.md](../../docs/architecture-hld.md) (path:docs/architecture-hld.md),
which describes 0.1.0 as built. This page maps the packages to their wiki pages.

| Layer | Package | Page |
|---|---|---|
| Mapper and dispatch | `map_conform/mapper.py`, `map_conform/settings.py` | this page |
| Conform spec | `map_conform/spec/` | [Spec loader](../components/spec-loader.md) |
| Names | `map_conform/naming/` | [Name conformer](../components/name-conformer.md) |
| Types, builtins, expr, UDFs | `map_conform/types/`, `map_conform/transforms/`, `map_conform/expr/`, `map_conform/udfs.py` | [Type system & builtins](../components/type-system-and-builtins.md) |
| Plan and executors, BATCH I/O | `map_conform/plan/`, `map_conform/batch/` | [Execution engines](../components/execution-engines.md) |
| Metadata, errors, rejects, metrics | `map_conform/metadata.py`, `map_conform/errors.py`, `map_conform/rejects.py`, `map_conform/metrics.py` | [Metadata & errors](../components/metadata-and-errors.md) |
| CLI, `doctor`, validate, bridges | `map_conform/cli.py`, `map_conform/doctor.py`, `map_conform/plan/validate.py` | [CLI and tools](../components/cli-and-tools.md) |

## Message handling

| Message | Effect |
|---|---|
| SCHEMA | Compile the StreamPlan; emit the conformed, declared SCHEMA (with `_sdc_*` when `add_record_metadata` is set) |
| RECORD | Row executor + metadata; preserve `time_extracted` and `version` |
| BATCH | Parquet in and out: the columnar executor, then the row executor for the rest; other files row by row; new manifest (or RECORDs when `batch_output.mode: record`) |
| STATE | Pass through, in order |
| ACTIVATE_VERSION | Rename the stream, pass through |
