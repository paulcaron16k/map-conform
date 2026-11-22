# map-conform — Executive overview

## The problem

Each warehouse target in a Singer/Meltano pipeline gets data in whatever shape the source
produced. CSV and spreadsheet sources are the worst case, where every value is a string:
`" $1,234.50 "`, `"3/7/24 4:05 PM"`, `"#N/A"`, `"Yes"`, column names like `Order Date (UTC)`
and `customerID`.

So every target grows its own cleanup layer: timestamp parsing, number grammars, boolean words,
name conforming, metadata columns. Those layers:

- **duplicate** each other: two surveyed targets each built a near-identical coercion module;
- **disagree** on the details: one target truncates `12.7` to `12` while another rounds it to
  `13`, and a bare `number` becomes DECIMAL(38,9) in one target and a double in another;
- **skip BATCH**: the SDK's fast BATCH path bypasses all per-record cleanup, so the fastest
  data is also the dirtiest;
- **cost review time**: every new target attracts the same cleanup suggestions in code
  review, each implemented a little differently.

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
1. **Handles BATCH at columnar speed**: parquet in, Arrow transforms, parquet out. The data
   becomes Python objects only for the columns that need it.

Behaviour is driven by a **conform spec file**. The spec is a versioned YAML/JSON file, so it
avoids Meltano's ~128 KiB environment-variable limit. It offers declarative builtins
(`{cast: decimal, strip_chars: "$,"}`), reusable macros, a safe expression language with
conditionals, and registered Python functions for anything else.

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

| Phase | Delivers | Exit |
| -- | -- | -- |
| P0 Foundations | Repo scaffolded from the SDK cookiecutter, CI, wiki, docs | CI is green and the package installs |
| P1 Spec & names | The spec model, loader, JSON Schema and CLI `spec validate`; the name conformer | Golden tests for naming |
| P2 RECORD engine | Type system, cast builtins, the RECORD path, `_sdc_*`, on_error/reject | The CSV corpus lands clean through target-jsonl |
| P3 Expressions, UDFs & stream-map parity | Expression language, conditionals, macros, UDF registry; SDK `stream_maps` drop-in; masking parity | Conditional examples and SDK stream-map test cases pass |
| P4 BATCH engine | Arrow plan, parquet/JSONL I/O, splicing of row-wise columns, polars extra | RECORD and BATCH outputs are identical; benchmarks |
| P5 Bridges & release | Zamboni/catalog bridge, Meltano Hub listing, PyPI 0.1.0 | Published; a reference pipeline runs |
| P6 Adoption | Clean-Landing Contract adopted in targets; duplicate cleanup removed | Targets pass with cleanup disabled |

Details: [plan-wbs.md](plan-wbs.md).

## Key risks

| Risk | Mitigation |
| -- | -- |
| Stock SDK targets strip `_sdc_*` unless `add_record_metadata: true` | Documented in setup and in the contract; checked by `map-conform doctor` |
| Expression language becomes a security hole | Sandboxed evaluator; Python UDFs from module paths need an explicit opt-in |
| RECORD and BATCH drift apart | One compiled plan; parity tests over the whole corpus |
| Spreadsheet date ambiguity (`3/7/24`) | Formats are explicit and per column; ambiguity raises rather than guessing |
