---
type: plan
title: "Roadmap and WBS"
description: "Phases P0-P6, epics E1-E12 and how they map to gh agile issues."
resource: docs/plan-wbs.md
tags: [management, planning, active]
timestamp: 2026-11-22T21:00:00Z
sources:
  - path: docs/plan-wbs.md
  - path: bin/create-agile-issues.py
---

# Roadmap and WBS

Parent: [Wiki Index](../index.md)

The authoritative plan is [docs/plan-wbs.md](../../docs/plan-wbs.md) (path:docs/plan-wbs.md).
Issues are filed by [bin/create-agile-issues.py](../../bin/create-agile-issues.py) with key
`MAPC`.

| Phase | Epics | Points | Status |
|---|---|---|---|
| P0 Foundations | E1 | 13 | Done 2026-11-22 (PRs #80, #81, #83–#85) |
| P1 Spec & names | E2, E3 | 32 | Done 2026-11-22 (PRs #87–#96) |
| P2 RECORD engine | E4, E5, E7 | 64 | Done 2026-11-22 (PRs #98–#105; 7.5 in #114) |
| P3 Expressions, UDFs & stream-map parity | E6, E12 | 53 | Done 2026-11-22 (PRs #106–#111) |
| P4 BATCH engine | E8 | 40 | Done 2026-11-22 (PRs #115–#120) |
| P5 Bridges, docs & release | E9, E10 | 21 | Next |
| P6 Adoption | E11 | 6 | |

Each phase ends with verification and an explicit approval from the owner.

## Open questions

| # | Question | Status |
|---|---|---|
| Q1 | uuid in BATCH | Resolved: Parquet UUID logical type ([ADR-0011](../decisions/0011-uuid-in-batch.md)) |
| Q2 | `_sdc_batched_at` | Resolved: BATCH input file mtime; RECORD mapper start |
| Q3 | filter names | Resolved: conformed |
| Q4 | transliteration table: vendor or dependency | Resolved: bundled, generated table ([ADR-0012](../decisions/0012-bundled-transliteration-table.md)) |
| Q5 | upstream SDK proposal for `_sdc_*` | Closed: no |
