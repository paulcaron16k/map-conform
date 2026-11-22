---
type: playbook
title: "Test strategy"
description: "Test layers, corpora, parity and contract tests, benchmarks."
resource: tests/
tags: [qa, testing, draft]
timestamp: 2026-11-22T05:00:00Z
sources:
  - path: docs/detailed-design.md
  - path: tests/fixtures/README.md
---

# Test strategy

Parent: [Wiki Index](../index.md)

> Status: **draft**. Built so far (P0): the fixtures, the wiki claim tests and the P0
> pass-through tests. The other layers arrive with their phases.

| Layer | What | Where |
|---|---|---|
| Unit | builtins, conformer, CType, spec loader | `tests/unit/` |
| Property | conformer idempotence, grammar and uniqueness; cast round-trips (Hypothesis) | `tests/property/` |
| Corpus | `input → expected \| !null \| !error` tables: dates (25+ formats), currencies, locales, null tokens, booleans, uuids, names | `tests/fixtures/corpus/*.csv` (built) |
| Parity | every corpus case through the row and columnar executors; outputs must be equal | `tests/parity/` |
| Contract | emitted SCHEMA validates emitted RECORDs; parquet schema == `to_arrow(plan)` | `tests/contract/` |
| E2E | `meltano run tap-csv map-conform target-jsonl`; target-ducklake with its cleanup off | `tests/e2e/` |
| Fixtures | generated fixtures are current; streams, catalogs and BATCH files are valid and agree | `tests/test_fixtures.py` (built) |
| Wiki | links and anchors resolve; documented modules and citations exist on active pages; no orphans; the log accounts for every page | `tests/wiki/` (built) |
| Bench | RECORD rows/s; BATCH rows/s; regression gate | `tests/bench/` |

The gates (per the owner's rules) are tests on every supported Python, ruff lint and format,
mypy and ty, and pre-commit, all green before any phase is called done.
