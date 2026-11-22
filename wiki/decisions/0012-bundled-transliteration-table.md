---
type: decision_log
title: "Decision 0012 — Bundled ASCII transliteration table"
description: "The name conformer transliterates with a table generated into the package from Unicode data plus a curated supplement; no runtime dependency and no GPL source."
resource: docs/detailed-design.md
tags: [naming, decision, active]
timestamp: 2026-11-22T06:00:00Z
sources:
  - path: docs/detailed-design.md
---

# Decision 0012 — Bundled ASCII transliteration table

Parent: [Wiki Index](../index.md) · Related: [Naming defaults](0008-naming-defaults.md) ·
[Name conformer](../components/name-conformer.md)

Status: **Accepted** (2026-11-22, owner; resolves open question Q4)

## Context
`naming.ascii: transliterate` turns `Ünïcode Näme` into `unicode_name`. The choice was a
dependency or a table bundled in the package.

- The best-known library, Unidecode, is GPL-2.0-or-later. Depending on it, or copying its
  tables, does not fit an Apache-2.0 package that others embed.
- A conformed name is part of a target's schema, so it must not change between runs. Python's
  own Unicode database differs by version: 14.0 on Python 3.11, 16.0 on 3.14 (checked
  2026-11-22). Deriving mappings at runtime would let the same column get different names
  on different interpreters.

## Decision
- **Bundle** a transliteration table as package data. No runtime dependency.
- **Generate** it with a script in the repository from two inputs:
  1. Unicode decompositions (NFKD, combining marks removed), taken from one pinned Unicode
     version. That version is recorded in the table's header.
  2. A curated supplement written for this project, for characters that do not decompose:
     `ß→ss`, `Æ→AE`, `æ→ae`, `Ø→O`, `Œ→OE`, `Đ→D`, `Ł→L`, `Þ→TH`, `ð→d`, `ı→i`, `ŋ→ng`, plus
     Greek and Cyrillic romanisation.
- **Scope for 0.1:** Latin (Latin-1 Supplement, Extended-A/B, Additional), Greek and
  Cyrillic. A character outside the table is dropped, which is a lossy rename and is logged.
  If nothing is left, the empty-name rule gives `col_<n>`.
- Nothing is copied from GPL-licensed tables. The supplement's provenance (written here) is
  stated in the generator.
- A staleness test fails when the committed table differs from the generator's output.

## Consequences
- Conformed names are identical on every supported Python and platform.
- Changing a mapping changes conformed names, so the table is part of the public naming
  contract: a change needs a changelog entry and goes in a minor release.
- Users can extend or override mappings with a spec option later, without a new release.
- Scripts outside the scope (CJK, Arabic, Hebrew, Indic) are not romanised in 0.1.
  Pipelines with such column names should use `alias` or `ascii: keep`.
- Implemented in WBS 3.1.
