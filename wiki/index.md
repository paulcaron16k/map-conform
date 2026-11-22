---
type: playbook
title: map-conform wiki
description: "Catalog of the map-conform knowledge base."
resource: wiki/
tags: [docs, active]
timestamp: 2026-11-21T00:00:00Z
sources:
  - path: creating-a-better-mapper-guidance.md
  - path: docs/
---

# map-conform wiki

> Status: **planning**. Pages tagged `draft` describe the designed system; no code exists yet.
> Maintenance rules: [Wiki maintenance](runbooks/wiki-maintenance.md) · Change log: [log.md](log.md)

## Start here

1. [Guidance (founding brief)](../creating-a-better-mapper-guidance.md)
2. [Clean-Landing Contract](concepts/clean-landing-contract.md)
3. [Architecture overview](architecture/overview.md)

## Architecture & design

| Page | Type | Covers |
|---|---|---|
| [Architecture overview](architecture/overview.md) | architecture_doc | Layers, message handling |
| [Survey of existing systems](concepts/existing-systems-survey.md) | concept | What the existing mappers and targets do and lack |
| [Decisions 0001–0012](decisions/0001-name-and-licence.md) | decision_log | Planning-quiz ADRs (see the list below) |

Decisions:
- [0001 Name & licence](decisions/0001-name-and-licence.md)
- [0002 Transform authoring](decisions/0002-transform-authoring.md)
- [0003 Own spec + Zamboni bridge](decisions/0003-own-spec-with-zamboni-bridge.md)
- [0004 BATCH engine](decisions/0004-batch-engine.md)
- [0005 _sdc_ metadata](decisions/0005-sdc-metadata.md)
- [0006 Error policy](decisions/0006-error-policy.md)
- [0007 Wire encoding](decisions/0007-wire-encoding.md)
- [0008 Naming defaults](decisions/0008-naming-defaults.md)
- [0009 Undeclared columns](decisions/0009-undeclared-columns.md)
- [0010 Stream-map superset & masking](decisions/0010-stream-map-superset.md)
- [0011 UUID in BATCH](decisions/0011-uuid-in-batch.md)
- [0012 Bundled transliteration table](decisions/0012-bundled-transliteration-table.md)

## Components

| Page | Type | Covers |
|---|---|---|
| [Spec loader](components/spec-loader.md) | component | `map_conform/spec/` |
| [Name conformer](components/name-conformer.md) | component | `map_conform/naming/` |
| [Type system & builtins](components/type-system-and-builtins.md) | component | `types/`, `transforms/`, `expr/`, `udf/` |
| [Execution engines](components/execution-engines.md) | component | `plan/`, `batch/` |
| [Metadata & errors](components/metadata-and-errors.md) | component | `metadata.py`, `errors.py`, `metrics.py` |

## Interfaces

| Page | Type | Covers |
|---|---|---|
| [Clean-Landing Contract](concepts/clean-landing-contract.md) | concept | Output guarantees for targets |
| [Conform spec](schemas/conform-spec.md) | schema | Spec file grammar |
| [Plugin settings](schemas/plugin-settings.md) | schema | Meltano settings |

## Delivery

| Page | Type | Covers |
|---|---|---|
| [Roadmap](plans/roadmap.md) | plan | Phases, epics, open questions |
| [CI/CD](ci-cd/pipeline.md) | ci_cd | Workflows |

## Quality & operations

| Page | Type | Covers |
|---|---|---|
| [Test strategy](qa/test-strategy.md) | playbook | Test layers and gates |
| [Benchmarks](qa/benchmarks.md) | metric | Throughput baseline and the CI regression gate |
| [Dev environment](runbooks/dev-environment.md) | runbook | Local setup |
| [Wiki maintenance](runbooks/wiki-maintenance.md) | runbook | Wiki rules |

## Conventions & reference

| Page | Type | Covers |
|---|---|---|
| [Glossary](glossary.md) | glossary | Terms |

## Reading paths

| Task | Path |
|---|---|
| Building a target | Contract → Wire encoding ADR → _sdc_ ADR |
| Writing a spec | Conform spec → Type system & builtins → Name conformer |
| Implementing BATCH | Execution engines → BATCH ADR → Test strategy (parity) |
