---
type: schema
title: "Plugin settings"
description: "Meltano/--config settings for map-conform (kept small; the spec lives in a file)."
resource: map_conform/settings.py
tags: [config, interface, draft]
timestamp: 2026-11-21T00:00:00Z
sources:
  - path: docs/detailed-design.md
---

# Plugin settings

Parent: [Wiki Index](../index.md)

> Status: **draft**. This describes the designed system. No code exists yet.

| Setting | Default | Meaning |
|---|---|---|
| `spec_path` | — | Conform spec file |
| `spec` | — | Inline spec, merged over the file |
| `spec_vars` | `{}` | `${var}` values |
| `strict` | false | Undeclared columns are an error; warnings are errors |
| `allow_python_udfs` | false | Allow module-path UDFs |
| `batch_output.mode` | batch | batch \| record |
| `batch_output.format` | parquet | parquet \| jsonl |
| `batch_output.compression` | zstd | |
| `batch_output.storage.root` / `.params` | input dir | fsspec URL and options |
| `batch_output.delete_input` | false | Delete input files once they are processed |
| `batch_output.row_group_size` | 131072 | Rows per parquet row group, and per processing chunk |
| `reject.storage` / `reject.format` | `./.map-conform/rejects` / jsonl | Dead-letter sink |
| `metrics_path` | — | Per-stream metrics JSON |
| `stream_maps`, `stream_map_config`, `faker_config`, `flattening_*` | — | SDK-compatible; translated into the spec ([ADR-0010](../decisions/0010-stream-map-superset.md)) |

Source: detailed design §1 (path:docs/detailed-design.md).
