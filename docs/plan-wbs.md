# map-conform — Plan, work breakdown structure and phases

Related: [exec overview](exec-overview.md) · [HLD](architecture-hld.md) ·
[detailed design](detailed-design.md)

Tracking uses `gh agile` on `paulcaron16k/map-conform`, with key `MAPC` and 2-week sprints.

The tracker hierarchy is **Initiative → Epic → Story**. The WBS codes below (`1.2.3`) appear
in every issue title suffix and in the `FR` field, so the two can be traced to each other.

- [`bin/create-agile-issues.py`](../bin/create-agile-issues.py) files the whole structure. It
  is idempotent: it skips titles that already exist.
- Points: 1, 2, 3, 5 or 8.

**Phase gates.** Each phase ends with verification (tests, lint, type-check, docs/wiki sync)
and an explicit approval before the next phase starts.

## Initiative

**MAPC — map-conform: clean landing for Singer pipelines.** Make one mapper responsible for
names, types, values and metadata, so that targets can assume clean data. *Acceptance:*
0.1.0 is on PyPI and listed on Meltano Hub; a reference pipeline lands a messy CSV and parquet
BATCH cleanly into DuckLake with target cleanup disabled; and the Clean-Landing Contract is
referenced by at least one target's review rules.

## Phases

| Phase | Epics | Exit criteria |
| -- | -- | -- |
| **P0 Foundations** | E1 | Cookiecutter scaffold committed; CI (lint, type, test, build) green on 3.10–3.14; wiki and docs in place; pre-commit and wiki lint working |
| **P1 Spec & names** | E2, E3 | Spec loads strictly with inheritance; JSON Schema generated, with a staleness test; `spec validate/schema`; conformer passes golden and property tests |
| **P2 RECORD engine** | E4, E5, E7 | Type system and builtins; RECORD path end to end; `_sdc_*`; on_error/reject; CSV corpus lands clean via target-jsonl |
| **P3 Expressions, UDFs & stream-map parity** | E6, E12 | Safe expr, `case`, macros, UDF registry; SDK `stream_maps` settings accepted unchanged; SDK stream-map test cases pass in compatibility mode; pipelinewise masking parity |
| **P4 BATCH engine** | E8 | Columnar executor; parquet/JSONL I/O; splice; polars extra; parity suite green; benchmarks recorded |
| **P5 Bridges, docs & release** | E9, E10 | Catalog/Zamboni bridge; `doctor`, `explain`; user docs; 0.1.0 on PyPI; Meltano Hub PR |
| **P6 Adoption** | E11 | Contract published; target review rules updated; duplicate cleanup removed from targets with tests |

## WBS — epics and stories

### E1 Foundations (P0) — 1

| WBS | Story | Pts | Acceptance |
| -- | -- | -- | -- |
| 1.1 | Scaffold from the SDK mapper cookiecutter (hatchling, hatch-vcs, ruff, mypy, pytest, tox-uv); package `map_conform`, executable `map-conform` | 3 | `uv run map-conform --about` works; generated mapper replaced with an `InlineMapper` pass-through that **also passes BATCH through** |
| 1.2 | CI workflows: lint, type, test matrix 3.10–3.13, build, zizmor; trusted publishing configured but disabled | 3 | CI green on PR |
| 1.3 | Pre-commit: ruff, mypy, wiki frontmatter linter (`bin/wiki-lint-frontmatter.py`), mdformat excluding `wiki/` | 2 | Hook rejects bad frontmatter |
| 1.4 | Wiki claim tests: links resolve, documented modules exist | 2 | `pytest tests/wiki` green |
| 1.5 | Test fixtures: messy CSV/XLSX-derived corpus, sample catalogs, parquet BATCH fixtures | 3 | Fixtures documented in `tests/fixtures/README.md` |

### E2 Conform spec (P1) — 2

| WBS | Story | Pts | Acceptance |
| -- | -- | -- | -- |
| 2.1 | Spec dataclass model (frozen) for Defaults, StreamSpec, ColumnSpec, Chain, Macro | 5 | Model round-trips; unknown keys rejected |
| 2.2 | Loader: YAML/JSON, `${var}` / `${env:}` substitution, inheritance by presence, glob specificity | 5 | Inheritance tests (objects merge, lists replace) |
| 2.3 | JSON Schema generator, shipped schema, staleness test | 3 | `map-conform spec schema` prints it; test fails when stale |
| 2.4 | Plugin settings (`spec_path`, `spec`, `spec_vars`, `strict`, `allow_python_udfs`, batch_output, reject) and `meltano.yml` | 2 | Settings documented; spec via file avoids the env limit |
| 2.5 | CLI `spec validate` (with `--catalog`) and `spec explain` | 3 | Validate reports every error with its path |

### E3 Name conformer (P1) — 3

| WBS | Story | Pts | Acceptance |
| -- | -- | -- | -- |
| 3.1 | Conform pipeline steps 1–8 (NFKC, transliterate, camel split, case, replace, collapse, digit, empty) | 5 | Golden table passes |
| 3.2 | Reserved-word data files (ANSI, Postgres, DuckDB) and policy | 2 | `select` → `select_` |
| 3.3 | Length limit with hash truncation; collision detection (error/suffix) under case folding | 3 | Property tests: idempotent, grammar, unique |
| 3.4 | Stream naming: conform, prefix, alias, split | 2 | `sheets-Orders 2024` → `raw_sheets_orders_2024` |
| 3.5 | Nested member conforming in struct shapes | 2 | Nested golden tests |

### E4 Type system (P2) — 4

| WBS | Story | Pts | Acceptance |
| -- | -- | -- | -- |
| 4.1 | CType parser and model (all rows of the type table, aliases, `decimal(p,s)`, struct/list) | 3 | Parse/print round-trip |
| 4.2 | Tap SCHEMA → CType (hints, anyOf, multi-type, x-singer.decimal) | 5 | Table-driven tests over SDK-style schemas |
| 4.3 | CType → canonical JSON Schema (contract) | 3 | Snapshot tests; decimals emitted as x-singer.decimal |
| 4.4 | CType → Arrow type | 2 | Tests for each type |

### E5 Builtins and RECORD engine (P2) — 5

| WBS | Story | Pts | Acceptance |
| -- | -- | -- | -- |
| 5.1 | Transform protocol, registry, kwargs validation, pre/post type checking, implicit cast | 5 | Bad kwargs fail at compile with their path |
| 5.2 | Text builtins | 3 | Corpus green |
| 5.3 | Numeric cast grammar (currency, locales, parens, percent, rounding policies) | 5 | Corpus green; int-from-fraction errors by default |
| 5.4 | Temporal cast (strptime list, ISO lenient, excel serial 1900/1904, epoch units, tz, DST policy) | 8 | 25+ format corpus; DST ambiguity tests |
| 5.5 | Boolean, uuid, binary, json casts | 3 | Corpus green |
| 5.6 | Privacy builtins (hash, mask, set_null, redact_date) | 2 | Matches pipelinewise semantics, minus its bugs |
| 5.7 | Plan compiler (ColumnPlan, deps, collisions, output SCHEMA) | 5 | `spec explain` shows the plan |
| 5.8 | Row executor and mapper wiring (SCHEMA/RECORD/STATE/ACTIVATE_VERSION; keys and bookmarks renamed; time_extracted preserved) | 5 | E2E via target-jsonl |
| 5.9 | Undeclared-column policy (conform/drop/error) and `strict` | 2 | Tests for each mode |

### E6 Expressions, conditionals, macros, UDFs (P3) — 6

| WBS | Story | Pts | Acceptance |
| -- | -- | -- | -- |
| 6.1 | Safe expression compiler (AST whitelist → closures) and SDK stream-map compatibility | 5 | SDK stream-map expression corpus passes; escape attempts rejected |
| 6.2 | Function library (predicates, coercion, temporal, text, numeric, misc) | 5 | Documented by `map-conform functions` |
| 6.3 | `case` step with when/then/else; ternary | 3 | Conditional examples pass |
| 6.4 | Macros with params | 2 | `money`, `sheet_date` examples |
| 6.5 | UDF decorator, entry points, module-path loading behind `allow_python_udfs` | 5 | Sample UDF package in tests |
| 6.6 | Derived columns and `filter` | 3 | Dependency order tests |

### E7 Metadata, errors, metrics (P2) — 7

| WBS | Story | Pts | Acceptance |
| -- | -- | -- | -- |
| 7.1 | `_sdc_*` columns, SDK-exact | 3 | Parity test against SDK `_add_sdc_metadata_to_record` |
| 7.2 | ConformError with full context; on_error raise/null/keep | 3 | Messages name stream, column, row and value |
| 7.3 | Reject sink (JSONL/parquet) and rate thresholds | 3 | Rejected rows written; threshold fails the run |
| 7.4 | Metrics (log lines + `metrics_path`) | 2 | Counters asserted in tests |
| 7.5 | `add_record_metadata` (default false) replaces `defaults.metadata`, for RECORD and BATCH (added 2026-11-22, done in #114) | 2 | No `_sdc_*` by default; per-stream override; `stream_maps` does not change it |

### E8 BATCH engine (P4) — 8

| WBS | Story | Pts | Acceptance |
| -- | -- | -- | -- |
| 8.1 | BATCH manifest read/write over fsspec; storage settings | 3 | Local and memory-fs tests |
| 8.2 | Parquet chunked reader/writer with declared Arrow schema | 3 | Output schema equals `to_arrow(plan)` |
| 8.3 | JSONL reader (explicit string types) and writer | 3 | gzip and plain |
| 8.4 | Arrow implementations of vectorisable builtins | 8 | Parity corpus green |
| 8.5 | Row-wise splice for non-vectorisable columns; reject masks | 5 | Mixed plans pass parity |
| 8.6 | `case` lowering to `case_when` | 3 | Conditional parity |
| 8.7 | `[polars]` extra and engine selection | 5 | Parity with the polars engine |
| 8.8 | `batch_output.mode: record` fallback; `delete_input` | 2 | E2E with a non-BATCH target |
| 8.9 | Benchmarks and CI regression gate | 3 | Baseline recorded in the wiki |
| 8.10 | Flattening from a declared JSON spec: stable SCHEMA and types; missing or empty members as `null`, `{}` or `[]` (JSON Schema `default`); undeclared members dropped, counted and logged (added 2026-11-22; first in P4) | 5 | Tap schema drift leaves the output SCHEMA unchanged; each empty-value form tested in RECORD and BATCH |

### E9 Bridges and tooling (P5) — 9

| WBS | Story | Pts | Acceptance |
| -- | -- | -- | -- |
| 9.1 | `spec import --catalog` (drafts a spec from a catalog) | 3 | Generated spec validates |
| 9.2 | Zamboni `columns` export/import | 3 | Round-trip with a Zamboni v2 file |
| 9.3 | `doctor`: meltano.yml checks (`add_record_metadata`, spec path, UDF opt-in) | 3 | Flags a missing `add_record_metadata` |

### E10 Docs and release (P5) — 10

| WBS | Story | Pts | Acceptance |
| -- | -- | -- | -- |
| 10.1 | User docs: README, spec reference, cookbook (CSV, spreadsheets, epoch, masking) | 5 | Every cookbook example is tested |
| 10.2 | Reference Meltano project (`examples/`) with tap-csv → map-conform → target-ducklake | 3 | `meltano run` in CI |
| 10.3 | Release 0.1.0 to PyPI (trusted publishing), changelog | 2 | `pip install map-conform` works |
| 10.4 | Meltano Hub plugin definition PR | 2 | PR opened |

### E11 Adoption: clean-landing targets (P6) — 11

| WBS | Story | Pts | Acceptance |
| -- | -- | -- | -- |
| 11.1 | Publish the Clean-Landing Contract page and a reviewer snippet | 2 | Linked from the README |
| 11.2 | target-ducklake: run the E2E suite with `type_source`/conforming off; list what can be removed | 3 | Report in the wiki |
| 11.3 | Add a "trust upstream" note to the target review rules in owned targets | 1 | Rules merged |

### E12 Stream-map parity and masking (P3) — 12

| WBS | Story | Pts | Acceptance |
| -- | -- | -- | -- |
| 12.1 | `stream_maps` translator: settings, globs, `__alias__`, `__filter__`, `__key_properties__`, `__else__`, `null`/`__NULL__`, `stream_map_config` | 5 | Translated spec equals the hand-written native spec for each feature |
| 12.2 | SDK prefix type inference for undeclared expression columns in compatibility mode, with warnings | 2 | Output SCHEMA matches the SDK mapper's |
| 12.3 | Stream-level `source`: split or copy a tap stream into several output streams | 3 | Copy and split examples; STATE order kept |
| 12.4 | Faker: `fake` function and step, `defaults.faker` seed/locale, `[faker]` extra | 2 | Seeded runs are reproducible |
| 12.5 | Masking parity: `mask_number`, `mask_hidden`, `tokenize`, hash algorithms, `skip_first` with any n; SCHEMA kept consistent (`set_null` makes the column nullable) | 3 | Every pipelinewise type has a passing test, including the cases where pipelinewise is buggy |
| 12.6 | `when` on a column or step (falsy literals compared correctly); `fields` for nested paths | 5 | `equals: 0` case; nested mask in struct and json |
| 12.7 | SDK flattening semantics, including `max_key_length` key shortening | 3 | Matches SDK flattening output |
| 12.8 | `spec import --stream-maps` migration with explicit inferred types | 2 | Round trip: import, then run, gives the same output |
| 12.9 | SDK stream-map parity suite (the SDK's own mapper test cases) | 3 | Green in CI |
| 12.10 | SDK naming preset (`naming: sdk`) reproducing the SDK's `conform_name` (ADR-0008) | 2 | Byte-for-byte equal to the SDK on the golden names and on generated names |

## Dependencies

```
E1 ─▶ E2 ─▶ E3
      E2 ─▶ E4 ─▶ E5 ─▶ E6 ─▶ E12
                   E5 ─▶ E7
          E5,E6,E7,E12 ─▶ E8 ─▶ E9 ─▶ E10 ─▶ E11
```

## Estimate

| Phase | Points |
| -- | -- |
| P0 | 13 |
| P1 | 32 |
| P2 | 64 |
| P3 | 53 |
| P4 | 40 |
| P5 | 21 |
| P6 | 6 |
| **Total** | **229** |

At ~20 points per 2-week sprint this is about 11 sprints. A first usable alpha, RECORD only
(P0–P2), comes after about 6 sprints.
