---
type: schema
title: "Plugin settings"
description: "Meltano/--config settings for map-conform (kept small; the spec lives in a file)."
resource: map_conform/settings.py
tags: [config, interface, active]
timestamp: 2026-11-22T10:00:00Z
sources:
  - path: map_conform/settings.py
  - path: meltano.yml
---

# Plugin settings

Parent: [Wiki Index](../index.md)

The `Settings` dataclass (path:map_conform/settings.py) is the source:
- the mapper's `config_jsonschema` (what `--about` lists) is generated from it;
- `meltano.yml` declares the same settings, and a test keeps the two equal.

| Setting | Default | Meaning |
|---|---|---|
| `spec_path` | — | Conform spec file |
| `spec` | — | Inline spec, merged over the file |
| `spec_vars` | `{}` | `${var}` values |
| `strict` | false | Undeclared columns are an error; warnings are errors |
| `allow_python_udfs` | false | Allow module-path UDFs |
| `batch_output.mode` | batch | batch \| record |
| `batch_output.format` | parquet | parquet \| jsonl |
| `batch_output.compression` | per format | zstd for parquet, gzip for jsonl |
| `batch_output.storage.root` / `.params` | input dir | fsspec URL and options |
| `batch_output.delete_input` | false | Delete input files once they are processed |
| `batch_output.row_group_size` | 131072 | Rows per parquet row group, and per processing chunk |
| `reject.storage` / `reject.format` | `./.map-conform/rejects` / jsonl | Dead-letter sink |
| `metrics_path` | — | Per-stream metrics JSON |

- **Start-up.** The spec is loaded and validated when the mapper starts. With no spec, the
  mapper conforms with the default rules.
- **Planned (E12).** The SDK-compatible `stream_maps`, `stream_map_config`, `faker_config`
  and `flattening_*` settings will be accepted and translated into the spec
  ([ADR-0010](../decisions/0010-stream-map-superset.md)). Until then the config schema
  rejects them.
