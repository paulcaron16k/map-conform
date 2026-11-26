---
type: plan
title: "Roadmap and WBS"
description: "Phases P0-P6, epics E1-E12 and how they map to gh agile issues."
resource: docs/plan-wbs.md
tags: [management, planning, active]
timestamp: 2026-11-25T18:00:00Z
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
| P5 Bridges, docs & release | E9, E10 | 21 | Done 2026-11-23 except 10.4, the Meltano Hub PR, which waits for field testing (PRs #121–#127; 0.1.0 on PyPI; 0.2.0, with the post-release fixes, on 2026-11-23) |
| P6 Adoption | E11 | 6 | Stories done 2026-11-24: 11.1 reviewer snippet, 11.3 target-ducklake's review rules, 11.2 [target-ducklake with its cleanup off](../qa/target-ducklake-clean-landing.md) (RECORD and BATCH land clean, after target fixes DUCKLKD-152, 153, 160) |

Each phase ends with verification and an explicit approval from the owner.

After the release, a review of the docs by fresh readers (a new user, an accuracy audit
against the code, a new maintainer) led to fixes tracked under E10: `spec validate` compiles
plans (MAPC-128), vectorised flags (129), offline tests (130), reference tables (131), BATCH
engine triage (132), docs as built (138), column `flatten` (141), user docs (140), and this
wiki sync and maintainer docs (144, 145). Their changes are in the changelog's Unreleased
section.

## Open questions

| # | Question | Status |
|---|---|---|
| Q1 | uuid in BATCH | Resolved: Parquet UUID logical type ([ADR-0011](../decisions/0011-uuid-in-batch.md)) |
| Q2 | `_sdc_batched_at` | Resolved: BATCH input file mtime; RECORD mapper start |
| Q3 | filter names | Resolved: conformed |
| Q4 | transliteration table: vendor or dependency | Resolved: bundled, generated table ([ADR-0012](../decisions/0012-bundled-transliteration-table.md)) |
| Q5 | upstream SDK proposal for `_sdc_*` | Closed: no |
