---
type: playbook
title: "Test strategy"
description: "Test layers, corpora, parity and contract tests, benchmarks."
resource: tests/
tags: [qa, testing, active]
timestamp: 2026-11-24T14:00:00Z
sources:
  - path: docs/detailed-design.md
  - path: tests/fixtures/README.md
---

# Test strategy

Parent: [Wiki Index](../index.md)

> Status: **active**. Every layer is built (P0–P4): unit, property, corpus, contract
> round-trip, SDK parity, row/columnar parity, E2E, wiki and benchmarks.

| Layer | What | Where |
|---|---|---|
| Unit | builtins, conformer, CType, spec loader, plan, executor | `tests/` by package: `tests/spec`, `tests/naming`, `tests/types`, `tests/transforms`, `tests/plan` (built) |
| Property | conformer idempotence, grammar and uniqueness; the `naming: sdk` preset and flattening keys equal the SDK's (Hypothesis) | `tests/naming/test_length_collisions.py`, `tests/naming/test_sdk_preset.py`, `tests/naming/test_flatten.py` (built) |
| Expressions | sandbox escapes and exhaustion refused; every SDK test expression evaluates as the SDK's simpleeval does (differential) | `tests/expr/` (built) |
| SDK parity | every SDK mapper test case through the SDK's `PluginMapper` and map-conform; equal up to documented differences | `tests/compat/` (built) |
| Corpus | `input → expected \| !null \| !error` tables: dates (25+ formats), currencies, locales, null tokens, booleans, uuids, names | `tests/fixtures/corpus/*.csv` (built) |
| Parity | every corpus case, generated values, `case` and polars through the row and columnar executors; tables, rejects, errors and metrics must be equal | `tests/parity/` (built) |
| Contract | contract SCHEMA reads back to the same CType; snapshot of every type's SCHEMA; parquet schema == `to_arrow(plan)` (P4) | `tests/types/test_type_mappings.py` (built) |
| E2E | the messy CSV fixture through `map-conform` into the published target-jsonl; into target-ducklake, pinned, with its cleanup off ([report](target-ducklake-clean-landing.md)) | `tests/e2e/` |
| Fixtures | generated fixtures are current; streams, catalogs and BATCH files are valid and agree | `tests/test_fixtures.py` (built) |
| Wiki | links and anchors resolve; documented modules and citations exist on active pages; no orphans; the log accounts for every page | `tests/wiki/` (built) |
| Contract | the mapper's own output keeps the Clean-Landing Contract | `tests/test_contract.py` (built) |
| Bench | RECORD rows/s; BATCH rows/s; regression gate ([Benchmarks](benchmarks.md)) | `tests/bench/` (built) |

The gates are the [definition of done](../runbooks/dev-environment.md#definition-of-done):
tests on every supported Python, ruff lint and format, mypy and ty, and pre-commit, all
green before a change is called done.
