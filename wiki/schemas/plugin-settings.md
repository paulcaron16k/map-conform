---
type: schema
title: "Plugin settings"
description: "Meltano/--config settings for map-conform (kept small; the spec lives in a file)."
resource: map_conform/settings.py
tags: [config, interface, active]
timestamp: 2026-11-23T18:00:00Z
sources:
  - path: map_conform/settings.py
  - path: meltano.yml
---

# Plugin settings

Parent: [Wiki Index](../index.md)

Every setting, with its type, default and meaning, is in the generated
[spec reference](../../docs/spec-reference.md#plugin-settings); this page records how the
settings are kept in step.

- **Source.** The `Settings` dataclass (path:map_conform/settings.py). The mapper's
  `config_jsonschema` (what `--about` lists) is generated from it, and so is the reference.
- **meltano.yml** (the repo root's) declares every setting by name, with a `kind`, `label`
  and `description` written by hand; a test checks that the names match `Settings`
  (path:tests/test_settings.py).
- **plugin-definition.yml**, the Meltano Hub entry, is rendered from `meltano.yml` and the
  mapper's `--about` by `uv run bin/render-hub-definition.py`; a test fails when it is stale
  (path:tests/test_hub_definition.py).
- **Groups.** The spec (`spec_path`, `spec`, `spec_vars`), policy (`strict`,
  `allow_python_udfs`, `add_record_metadata`), BATCH output (`batch_output.*`), rejects
  (`reject.*`), `metrics_path`, and the SDK-compatible `stream_maps`, `stream_map_config`,
  `faker_config` and `flattening_*`, which are translated into a spec at start-up
  ([ADR-0010](../decisions/0010-stream-map-superset.md)).
- **Layering.** `add_record_metadata` and the SDK settings become the spec's base defaults:
  the spec's own `defaults` and stream rules win over them.
- **Start-up.** Settings and spec are validated when the mapper starts, before any input. With
  no spec, the mapper conforms with the default rules.
- **Meltano** passes any key in a mapping's `config`, declared or not; declaring a setting
  matters for `meltano config` and environment variables.

Adding a setting: see the checklist in [Dev environment](../runbooks/dev-environment.md#adding-a-setting).
