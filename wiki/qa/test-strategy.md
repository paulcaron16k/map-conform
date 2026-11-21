---
type: playbook
title: "Test strategy"
description: "Test layers, corpora, parity and contract tests, benchmarks."
resource: tests/
tags: [qa, testing, draft]
timestamp: 2026-11-21T00:00:00Z
sources:
  - path: docs/detailed-design.md
---

# Test strategy

Parent: [Wiki Index](../index.md)

> Status: **draft**. This describes the designed system. No code exists yet.

| Layer | What | Where |
|---|---|---|
| Unit | builtins, conformer, CType, spec loader | `tests/unit/` |
| Property | conformer idempotence, grammar and uniqueness; cast round-trips (Hypothesis) | `tests/property/` |
| Corpus | `input → expected \| error` tables: dates (25+ formats), currencies, locales, null tokens, booleans | `tests/corpus/*.yml` |
| Parity | every corpus case through the row and columnar executors; outputs must be equal | `tests/parity/` |
| Contract | emitted SCHEMA validates emitted RECORDs; parquet schema == `to_arrow(plan)` | `tests/contract/` |
| E2E | `meltano run tap-csv map-conform target-jsonl`; target-ducklake with its cleanup off | `tests/e2e/` |
| Wiki | links resolve; documented modules exist | `tests/wiki/` |
| Bench | RECORD rows/s; BATCH rows/s; regression gate | `tests/bench/` |

The gates (per the owner's rules) are tests, ruff lint and format, and mypy, all green before
any phase is called done.
