---
type: plan
title: "Roadmap and WBS"
description: "Phases P0-P6, epics E1-E11 and how they map to gh agile issues."
resource: docs/plan-wbs.md
tags: [management, planning, active]
timestamp: 2026-11-21T00:00:00Z
sources:
  - path: docs/plan-wbs.md
  - path: bin/create-agile-issues.py
---

# Roadmap and WBS

Parent: [Wiki Index](../index.md)

The authoritative plan is [docs/plan-wbs.md](../../docs/plan-wbs.md) (path:docs/plan-wbs.md).
Issues are filed by [bin/create-agile-issues.py](../../bin/create-agile-issues.py) with key
`MAPC`.

| Phase | Epics | Points |
|---|---|---|
| P0 Foundations | E1 | 13 |
| P1 Spec & names | E2, E3 | 32 |
| P2 RECORD engine | E4, E5, E7 | 62 |
| P3 Expressions, UDFs & stream-map parity | E6, E12 | 51 |
| P4 BATCH engine | E8 | 35 |
| P5 Bridges, docs & release | E9, E10 | 21 |
| P6 Adoption | E11 | 6 |

Each phase ends with verification and an explicit approval from the owner.

## Open questions

| # | Question | Status |
|---|---|---|
| Q1 | uuid in BATCH | Resolved: Parquet UUID logical type ([ADR-0011](../decisions/0011-uuid-in-batch.md)) |
| Q2 | `_sdc_batched_at` | Resolved: BATCH input file mtime; RECORD mapper start |
| Q3 | filter names | Resolved: conformed |
| Q4 | transliteration table: vendor or dependency | Open: decide when licence restrictions are known (before WBS 3.1) |
| Q5 | upstream SDK proposal for `_sdc_*` | Closed: no |
