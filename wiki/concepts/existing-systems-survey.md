---
type: concept
title: Survey of existing mappers and targets
description: "What existing Singer mappers and targets do to SCHEMA, RECORD and BATCH, and which of it map-conform absorbs."
resource: creating-a-better-mapper-guidance.md
tags: [engineering, research, active]
timestamp: 2026-11-23T16:00:00Z
sources:
  - path: creating-a-better-mapper-guidance.md
---

# Survey of existing mappers and targets

Parent: [Wiki Index](../index.md) · Related: [Clean-Landing Contract](clean-landing-contract.md)

The full tables are in [the guidance document §3](../../creating-a-better-mapper-guidance.md#3-survey-what-existing-systems-do)
(path:creating-a-better-mapper-guidance.md). This page records the conclusions that drive the
design.

| Finding | Consequence for map-conform |
|---|---|
| No mapper coerces strings to declared types | Core feature (E5) |
| Targets build their own coercion layers, with different number grammars and rounding | One grammar, with an explicit `rounding` policy |
| No one splits camelCase, handles reserved words or conforms nested names | Naming pipeline (E3) |
| A mapper that only lowercases keys can silently merge `Id` and `ID` | Collision is an error |
| SDK stream maps infer types from expression prefixes, and runtime errors crash the run | Declared types; ConformError + `on_error` |
| meltano-map-transformer overwrites `time_extracted` and drops `bookmark_properties` | Preserve both (WBS 5.8) |
| pipelinewise-transform-field swallows exceptions, ignores `equals: 0`, and drops ACTIVATE_VERSION | Fail loud; tests for falsy conditions; pass ACTIVATE_VERSION |
| SDK targets strip `_sdc_*` unless `add_record_metadata: true` | Documented requirement; `doctor` check |
| Every BATCH consumer converts parquet to dicts, and the SDK BATCH path skips cleanup | Columnar executor (E8) |
| SDK parquet encoder infers its Arrow schema from data | Output written with the declared Arrow schema |
| Zamboni `columns` is an unstructured type string | Own spec + export bridge (E9) |
| Users rely on stream-map features (`__source__`, `__else__`, `fake`, flattening) and on pipelinewise masking with `when` | Superset with a compatibility mode (E12, [ADR-0010](../decisions/0010-stream-map-superset.md)) |

## Verified facts (with the source checked)

- SDK `Sink.__init__` calls `_remove_sdc_metadata_from_schema()` when `add_record_metadata` is
  false, and `Target._process_record_message` calls `_remove_sdc_metadata_from_record`
  (path:singer_sdk/sinks/core.py, singer_sdk/target_base.py, SDK at commit 8363ee56).
- SDK `InlineMapper.map_batch_message` raises `NotImplementedError`
  (path:singer_sdk/mapper_base.py).
