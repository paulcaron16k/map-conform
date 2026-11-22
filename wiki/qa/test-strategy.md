---
type: playbook
title: "Test strategy"
description: "Test layers, corpora, parity and contract tests, benchmarks."
resource: tests/
tags: [qa, testing, draft]
timestamp: 2026-11-22T12:00:00Z
sources:
  - path: docs/detailed-design.md
  - path: tests/fixtures/README.md
---

# Test strategy

Parent: [Wiki Index](../index.md)

> Status: **draft**. Built so far (P0-P2): unit, property (naming), corpus, contract
> round-trip, E2E and wiki layers. Parity (BATCH) and benchmarks arrive with P4.

| Layer | What | Where |
|---|---|---|
| Unit | builtins, conformer, CType, spec loader, plan, executor | `tests/` by package: `tests/spec`, `tests/naming`, `tests/types`, `tests/transforms`, `tests/plan` (built) |
| Property | conformer idempotence, grammar and uniqueness (Hypothesis) | `tests/naming/test_length_collisions.py` (built) |
| Corpus | `input → expected \| !null \| !error` tables: dates (25+ formats), currencies, locales, null tokens, booleans, uuids, names | `tests/fixtures/corpus/*.csv` (built) |
| Parity | every corpus case through the row and columnar executors; outputs must be equal | `tests/parity/` |
| Contract | contract SCHEMA reads back to the same CType; snapshot of every type's SCHEMA; parquet schema == `to_arrow(plan)` (P4) | `tests/types/test_type_mappings.py` (built) |
| E2E | the messy CSV fixture through `map-conform` into the published target-jsonl (built); target-ducklake with its cleanup off (later) | `tests/e2e/` |
| Fixtures | generated fixtures are current; streams, catalogs and BATCH files are valid and agree | `tests/test_fixtures.py` (built) |
| Wiki | links and anchors resolve; documented modules and citations exist on active pages; no orphans; the log accounts for every page | `tests/wiki/` (built) |
| Bench | RECORD rows/s; BATCH rows/s; regression gate | `tests/bench/` |

The gates (per the owner's rules) are tests on every supported Python, ruff lint and format,
mypy and ty, and pre-commit, all green before any phase is called done.
