---
type: component
title: "Name conformer"
description: "Deterministic pipeline that makes stream, column and nested names legal in every target."
resource: map_conform/naming/
tags: [engineering, naming, draft]
timestamp: 2026-11-21T00:00:00Z
sources:
  - path: docs/detailed-design.md
---

# Name conformer

Parent: [Wiki Index](../index.md) · Related: [Detailed design](../../docs/detailed-design.md)

> Status: **draft**. This describes the designed system. No code exists yet.

## Pipeline (defaults from [ADR-0008](../decisions/0008-naming-defaults.md))

1. NFKC
2. Transliterate to ASCII with the bundled table ([ADR-0012](../decisions/0012-bundled-transliteration-table.md))
3. Split camelCase and acronyms
4. Lowercase
5. `[^a-z0-9_]` → `_`
6. Collapse `_` and trim it from the ends
7. Leading digit → `_` prefix
8. Empty → `col_<n>`
9. Reserved word → `_` suffix
10. Longer than 63 → head + `_` + 6-hex hash
11. Collision check under case folding

## Golden cases

| Source | Output |
|---|---|
| `Order Date (UTC)` | `order_date_utc` |
| `customerID` | `customer_id` |
| `HTTPServerURL` | `http_server_url` |
| `2023 Revenue` | `_2023_revenue` |
| `Ünïcode Näme` | `unicode_name` |
| `select` | `select_` |

## Preset `naming: sdk`

Reproduces the SDK's SQL `conform_name` byte for byte: strip, lowercase, `.`/`-`/space → `_`,
leading digit → letter. It exists for migrating tables that were already loaded that way.

## Properties (tested with Hypothesis)

- idempotent: `conform(conform(x)) == conform(x)`;
- the output always matches the grammar;
- the output is unique per stream, or an error is raised.
