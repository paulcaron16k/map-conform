---
type: playbook
title: map-conform wiki
description: "Catalog of the map-conform knowledge base."
resource: wiki/
tags: [docs, active]
timestamp: 2026-11-24T14:00:00Z
sources:
  - path: creating-a-better-mapper-guidance.md
  - path: docs/
---

# map-conform wiki

> Status: **0.1.0 released** (2026-11-23). Pages tagged `active` describe the running code;
> `draft` would mark a page describing a design not built yet.
> Maintenance rules: [Wiki maintenance](runbooks/wiki-maintenance.md) · Change log: [log.md](log.md)

## Start here

1. [README](../README.md) and the [cookbook](../docs/cookbook.md): what it does, in use
2. [Clean-Landing Contract](concepts/clean-landing-contract.md): what targets may assume
3. [Architecture overview](architecture/overview.md): where the code is
4. [Contributing](../CONTRIBUTING.md) and [Dev environment](runbooks/dev-environment.md): how to change it
5. [Guidance (founding brief)](../creating-a-better-mapper-guidance.md): the original intent, kept as a record

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
| [Type system & builtins](components/type-system-and-builtins.md) | component | `types/`, `transforms/`, `expr/`, `udfs.py` |
| [Execution engines](components/execution-engines.md) | component | `plan/`, `batch/` |
| [Metadata & errors](components/metadata-and-errors.md) | component | `metadata.py`, `errors.py`, `rejects.py`, `metrics.py` |
| [CLI and tools](components/cli-and-tools.md) | component | `cli.py`, `doctor.py`, `spec/check.py`, `spec/bridge.py`, `plan/validate.py` |

## Interfaces

| Page | Type | Covers |
|---|---|---|
| [Clean-Landing Contract](concepts/clean-landing-contract.md) | concept | Output guarantees for targets |
| [Conform spec](schemas/conform-spec.md) | schema | Spec file grammar; every key is in the [spec reference](../docs/spec-reference.md) |
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
| [target-ducklake with its cleanup off](qa/target-ducklake-clean-landing.md) | resource | WBS 11.2: what lands, what fails, what the target could remove |
| [Dev environment](runbooks/dev-environment.md) | runbook | Local setup, checks, generated files, checklists |
| [Release](runbooks/release.md) | runbook | Cutting a release to PyPI |
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
| Adding a step, setting or type | Dev environment (checklists) → Type system & builtins |
| Releasing | Release runbook |
