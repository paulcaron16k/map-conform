# map-conform — Executive overview

Status: 0.1.0 and 0.2.0 are released (2026-11-23); phases P0–P5 are done and P6's stories are
done (2026-11-24): the contract's reviewer snippet is published and in target-ducklake's review
rules, and map-conform's RECORD output lands clean in DuckLake with the target's cleanup off.

## The problem

Each warehouse target in a Singer/Meltano pipeline gets data in whatever shape the source
produced. CSV and spreadsheet sources are the worst case, where every value is a string:
`" $1,234.50 "`, `"3/7/24 4:05 PM"`, `"#N/A"`, `"Yes"`, column names like `Order Date (UTC)`
and `customerID`.

So every target grows its own cleanup layer: timestamp parsing, number grammars, boolean words,
name conforming, metadata columns. Those layers:

- **duplicate** each other: surveyed targets each built their own coercion module;
- **disagree** on the details: `12.7` is truncated to `12` on one load path and rounded to
  `13` on another, and a bare `number` becomes DECIMAL(38,9) in one target and a double in
  another;
- **skip BATCH**: the SDK's fast BATCH path bypasses all per-record cleanup, so the fastest
  data is also the dirtiest;
- **cost review time**: every new target attracts the same cleanup suggestions in code
  review, each implemented a little differently.

The usual alternative, a cleanup layer in dbt, is one goal among several to avoid. It is SQL
only, its macros have to work across every warehouse a project targets (so the same parsing
is written per dialect, or cut down to what all dialects share), and it runs after the raw
data has landed, mess and personal data included. A mapper in Python has none of those
limits: exact decimals, real date parsing, Unicode-aware names, masking before anything is
stored, and one implementation for every target.

## The solution

**map-conform** is one open-source Meltano mapper that does all of it, once, between tap and
target.

1. **Cleans values** while casting strings to a declared type: currency, thousands
   separators, parenthesised negatives, null tokens, non-ISO and spreadsheet-serial dates,
   epoch times, time zones, boolean words.
1. **Conforms names** of streams, columns and nested members so they are legal in every
   target: snake_case, ASCII, 63 characters, reserved-word safe, clash-checked.
1. **Casts to declared types**, never inferred, with precise decimals and explicit
   timestamp-with-zone vs without.
1. **Prefixes and aliases streams.**
1. **Adds `_sdc_*` metadata** with the SDK's exact semantics, in one place.
1. **Handles BATCH at columnar speed**: parquet in, Arrow (or polars) kernels for the casts
   and text steps that have them, parquet out. The other steps, expressions and policies run
   per row, with the same result as RECORD.

Behaviour is driven by a **conform spec file**. The spec is a versioned YAML/JSON file, so it
avoids Meltano's ~128 KiB environment-variable limit. It offers declarative builtins
(`{type: "decimal(12,2)", parse: {parens_negative: true}}`), reusable macros, a safe
expression language with conditionals, and registered Python functions for anything else.

## The outcome

- **Targets get simpler.** A target built for map-conform writes and owns table semantics
  (merge, dedupe, partitioning, evolution). It does not clean. A published **Clean-Landing
  Contract** says exactly what a target may assume, and code reviewers are told to stop
  adding cleanup to targets.
- **One behaviour everywhere.** The same CSV gives the same values in DuckDB, Iceberg,
  Postgres or any other target.
- **BATCH becomes first-class.** Clean, declared-schema parquet flows end to end.
- **It interoperates.** It exports column types to Zamboni table-config and imports from Singer
  catalogs.

## Scope and non-goals

| In | Out |
| -- | -- |
| Name, type and value conforming; metadata; BATCH transform; everything SDK stream maps do (alias, filter, split/copy streams, drop, expressions, faker, flattening), and SDK `stream_maps` settings accepted unchanged; masking/hashing at parity with pipelinewise-transform-field | Loading, merging, deduplicating or partitioning (target concerns) |
| Declared-schema validation and dead-letter rejects | Data-quality rule engines, cross-row checks, joins |
| Importing from a Singer catalog; Zamboni `columns` bridge | Table maintenance (Zamboni's job) |

## Plan at a glance

| Phase | Delivers | Exit | Status |
| -- | -- | -- | -- |
| P0 Foundations | Repo scaffolded from the SDK cookiecutter, CI, wiki, docs | CI is green and the package installs | Done |
| P1 Spec & names | The spec model, loader, JSON Schema and CLI `spec validate`; the name conformer | Golden tests for naming | Done |
| P2 RECORD engine | Type system, cast builtins, the RECORD path, `_sdc_*`, on_error/reject | The CSV corpus lands clean through target-jsonl | Done |
| P3 Expressions, UDFs & stream-map parity | Expression language, conditionals, macros, UDF registry; SDK `stream_maps` drop-in; masking parity | Conditional examples and SDK stream-map test cases pass | Done |
| P4 BATCH engine | Arrow plan, parquet/JSONL I/O, splicing of row-wise columns, polars extra | RECORD and BATCH outputs are identical; benchmarks | Done |
| P5 Bridges & release | Zamboni/catalog bridge, `doctor`, docs, a reference Meltano project, PyPI 0.1.0, Meltano Hub listing | Published; a reference pipeline runs | Done, except the Hub listing |
| P6 Adoption | Clean-Landing Contract adopted in targets; duplicate cleanup removed | Targets pass with cleanup disabled | RECORD passes; BATCH waits on two target bugs; no cleanup removed yet |

Details: [plan-wbs.md](plan-wbs.md).

## Key risks

| Risk | Mitigation |
| -- | -- |
| Stock SDK targets strip `_sdc_*` unless `add_record_metadata: true` | Documented in setup and in the contract; checked by `map-conform doctor` |
| Expression language becomes a security hole | Sandboxed evaluator; Python UDFs from module paths need an explicit opt-in |
| RECORD and BATCH drift apart | One compiled plan; parity tests over the whole corpus |
| Spreadsheet date ambiguity (`3/7/24`) | Formats are explicit and per column, tried in the order listed; nothing is guessed from the data |
