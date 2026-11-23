---
type: component
title: "Name conformer"
description: "Deterministic pipeline that makes stream, column and nested names legal in every target."
resource: map_conform/naming/
tags: [engineering, naming, active]
timestamp: 2026-11-23T18:00:00Z
sources:
  - path: map_conform/naming/conform.py
  - path: map_conform/naming/translit.py
  - path: map_conform/naming/reserved.py
  - path: map_conform/naming/streams.py
  - path: map_conform/naming/nested.py
  - path: map_conform/naming/flatten.py
  - path: map_conform/naming/shape.py
  - path: docs/detailed-design.md
---

# Name conformer

Parent: [Wiki Index](../index.md) · Related: [Detailed design](../../docs/detailed-design.md)

## Pipeline (defaults from [ADR-0008](../decisions/0008-naming-defaults.md))

`map_conform/naming/conform.py`:

1. NFKC.
2. ASCII:
   - transliterate with the bundled table ([ADR-0012](../decisions/0012-bundled-transliteration-table.md),
     `map_conform/naming/translit.py`, Unicode 16.0.0, Latin/Greek/Cyrillic);
   - multi-letter capitals are title-cased, or all caps beside another capital (`ΑΡΙΘΜΟΣ` →
     `arithmos`);
   - characters outside the table are dropped.
3. Split camelCase and acronyms (snake only). A plural acronym stays whole: `customerIDs` →
   `customer_ids`.
4. Case: snake/lower, upper or preserve.
5. Characters outside the allowed set → `_`. Separators are not losses; `%`, `$` and `#` are.
6. Collapse `_` and trim it from the ends.
7. Leading digit: `_` prefix, SDK letter (`0`→`a`), or error.
8. Empty → `col_<n>`.
9. Reserved word → `_` suffix (`map_conform/naming/reserved.py`). The default lists are
   PostgreSQL, DuckDB and Snowflake; `ansi` is opt-in.
10. Longer than `max_length` (63, at least 8) → head + `_` + 6 hex digits of the SHA-256 of
    the whole name.

Steps 6–10 repeat until the name is a fixed point. `conform_all` checks collisions under case
folding: an error, or `_2`, `_3`, … Genuine names win.

## Streams and nested members

- `map_conform/naming/streams.py`:
  - an alias is checked, never silently conformed;
  - otherwise the source key or tap name, split, conformed, then prefixed.
- `map_conform/naming/nested.py`:
  - struct members (CTypes and tap-schema objects) are conformed at every depth, through
    lists;
  - collisions are checked per struct;
  - `rename_value` renames record values.

## Golden cases

`tests/fixtures/corpus/names.csv` has 38 cases, including every design §5 example:

| Source | Output |
|---|---|
| `Order Date (UTC)` | `order_date_utc` |
| `customerID` | `customer_id` |
| `HTTPServerURL` | `http_server_url` |
| `2023 Revenue` | `_2023_revenue` |
| `Ünïcode Näme` | `unicode_name` |
| `select` | `select_` |
| `ΑΡΙΘΜΟΣ` | `arithmos` |

## Properties (tested with Hypothesis)

- The output always matches the grammar.
- Conforming is idempotent under randomised configurations.
- The output is unique per stream, or an error is raised.

## The `naming: sdk` preset

`naming: sdk` (short for `{preset: sdk}`) reproduces the SDK's SQL `conform_name` byte for
byte, for migrations. Only `on_collision` still applies. It is checked against the SDK's own
function on the golden names and on generated names (`tests/naming/test_sdk_preset.py`).
Translated `stream_maps` use it by default.

## Flattening

`nested: flatten` re-implements the SDK's flattening, key shortening included
(`map_conform/naming/flatten.py`). The flattened keys are then conformed like any name, so
the default `collapse: true` turns the `__` separator into `_`. A column's `flatten: true`
flattens just that column, from its `shape` or else from the tap's schema, whatever `nested`
is; `flatten: false` keeps a column whole under `nested: flatten`.

## Declared shapes

`map_conform/naming/shape.py`. A column's `shape` (a JSON Schema, inline or a file next to
the spec) alone decides its type, or its flattened leaf columns, so the output does not
follow the tap's schema when it drifts. At run time each value is conformed to the shape
first: members the shape does not declare are dropped, counted (`members_dropped`) and
logged once per stream; a member's `default` (`null`, `{}`, `[]`) fills it when it is
missing, null or empty.
