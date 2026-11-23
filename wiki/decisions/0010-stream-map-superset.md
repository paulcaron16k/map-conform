---
type: decision_log
title: "Decision 0010 — A superset of SDK stream maps, including masking"
description: "Everything SDK stream maps and pipelinewise-transform-field can do has a native equivalent; SDK stream_maps settings are accepted unchanged."
resource: docs/detailed-design.md
tags: [architecture, decision, active]
timestamp: 2026-11-23T18:00:00Z
sources:
  - path: docs/detailed-design.md
---

# Decision 0010 — A superset of SDK stream maps, including masking

Parent: [Wiki Index](../index.md) · Related: [Architecture overview](../architecture/overview.md)

Status: **Accepted** (2026-11-21, planning review). **Amended** 2026-11-22: compatibility defaults.

## Context
The first draft of the plan replaced stream maps rather than extending them. It dropped
features people rely on:
- `__source__` stream splitting and copying;
- `__else__`;
- property removal;
- `fake`, `md5`/`sha256`;
- flattening settings;
- pipelinewise-style masking with `when` conditions and nested `field_paths`.

map-conform must be a *better* stream map, and must not lose any functionality.

## Decision
- **Every SDK stream-map feature has a native spec equivalent.** The mapping table is in
  detailed design §15:
  - stream-level `source`;
  - top-level `else`;
  - column `drop`;
  - `alias` as an expression;
  - SDK expression names and functions kept as aliases;
  - `fake` and `defaults.faker`;
  - SDK flattening semantics.
- **Compatibility mode.** The SDK settings `stream_maps`, `stream_map_config`, `faker_config`
  and `flattening_*` are accepted unchanged and translated into the spec. The native spec
  wins. Undeclared expression types use the SDK's prefix inference, with an INFO note, so the
  output matches meltano-map-transformer. The implicit cast and `on_error` still apply.
- **Masking parity with pipelinewise-transform-field.** Every one of its types is a builtin.
  A `when` expression can be put on a column or on any step, and `fields` applies transforms
  to nested paths.
- `filter` and `when` see **conformed** names (decided 2026-11-21, Q3).
- `map-conform spec import --stream-maps` migrates an existing config to a native spec.

## Consequences
- map-conform can drop in for meltano-map-transformer.
- Known upstream defects are not reproduced:
  - `time_extracted` overwritten;
  - `bookmark_properties` dropped;
  - errors swallowed;
  - the `equals: 0` truthiness bug;
  - single-digit `n` only;
  - ACTIVATE_VERSION dropped.
- A parity test suite runs the SDK's stream-map cases.

## Amendment (2026-11-22): compatibility defaults
Running the SDK's own mapper tests through both mappers showed that map-conform's defaults
(snake_case naming, conformed stream names, JSON text for nested values, trimming and null
tokens) changed the output of unchanged `stream_maps` settings. With
`stream_maps` set, these defaults now apply unless the spec sets them:
`naming: sdk`, `stream.name: preserve`, `nested: keep`, and
`values: {trim: false, null_tokens: []}`. The `_sdc_*` columns follow `add_record_metadata`
alone (ADR-0005). A project moving from meltano-map-transformer
keeps its output, and the parity suite (`tests/compat/`) checks every SDK test case.
The remaining differences, such as canonical timestamps and exact decimals, are deliberate
and listed in detailed design §15.
