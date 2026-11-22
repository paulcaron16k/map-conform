---
type: decision_log
title: "Decision 0005 — Emit SDK _sdc_* exactly; document target requirement"
description: "Emit the seven _sdc_* columns with SDK names and values; SDK targets must set add_record_metadata: true."
resource: creating-a-better-mapper-guidance.md
tags: [architecture, decision, active]
timestamp: 2026-11-22T19:00:00Z
sources:
  - path: creating-a-better-mapper-guidance.md
---

# Decision 0005 — Emit SDK _sdc_* exactly; document target requirement

Parent: [Wiki Index](../index.md) · Related: [Architecture overview](../architecture/overview.md)

Status: **Accepted** (2026-11-21, planning quiz). **Amended** 2026-11-22: off unless `add_record_metadata`.

## Context
- These columns should be added once, upstream, and also for BATCH.
- The SDK source was checked (`sinks/core.py` `_remove_sdc_metadata_from_schema`,
  `target_base.py`). With `add_record_metadata: false`, the default, an SDK target **removes**
  all seven columns from both schema and records. With `true`, it overwrites them.

## Decision
- Emit `_sdc_extracted_at`, `_sdc_received_at`, `_sdc_batched_at`, `_sdc_deleted_at`,
  `_sdc_sequence`, `_sdc_table_version` and `_sdc_sync_started_at`, with SDK-exact semantics,
  declared in SCHEMA.
- **Document only**: SDK targets must set `add_record_metadata: true`, and the values they
  then overwrite are approximately the same.
- No rename escape hatch and no target patches.
- **No SDK change will be proposed.** The Singer specification and the SDK own their `_sdc_*`
  behaviour (decided 2026-11-21, Q5).
- `_sdc_batched_at`: for BATCH it is the **input file's last-modified time**; for RECORD it is
  the **mapper start time**, so the whole run is one batch (decided 2026-11-21, Q2).

## Consequences
- `map-conform doctor` warns when a downstream SDK target lacks the flag.
- BATCH files carry the columns too. The SDK target BATCH path neither strips nor adds them,
  but the SCHEMA it holds will have them removed unless the flag is set.

## Amendment (2026-11-22): `add_record_metadata`, default false
The owner decided that the columns follow one switch, named like the SDK targets' setting:
`add_record_metadata` (default **false**), for RECORD and BATCH alike. It replaces
`defaults.metadata: sdc | none` (which defaulted to adding them), can be set as a plugin
setting or per stream in the spec, and is not changed by `stream_maps`. Without it the tap's
own `_sdc_*` properties are left out too, as SDK targets do.
