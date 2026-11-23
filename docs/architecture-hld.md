# map-conform — Architecture and high-level design

Related: [exec overview](exec-overview.md) · [detailed design](detailed-design.md) ·
[plan](plan-wbs.md) · [guidance](../creating-a-better-mapper-guidance.md)

Status: describes 0.1.0 as built.

## 1. Context

```
            ┌──────────────┐  SCHEMA / RECORD / STATE /       ┌──────────────┐
  source ──▶│     tap      │  ACTIVATE_VERSION / BATCH ──────▶│  map-conform │
            └──────────────┘          (stdin)                 └──────┬───────┘
                                                                     │ clean SCHEMA / RECORD /
                                       conform spec (file) ─────────▶│ STATE / ACTIVATE_VERSION /
                                       UDF modules / entry points ──▶│ BATCH (new files)
                                                                     ▼
            batch storage (file://, s3://, gs:// … via fsspec) ◀──▶ ┌──────────────┐
                                                                    │    target    │
                                                                    └──────────────┘
```

map-conform is a Singer **inline mapper**: a process that reads Singer messages on stdin and
writes Singer messages on stdout. Meltano runs it between a tap and a target as a `mappings:`
entry. It is built on the Singer SDK's `InlineMapper`. It does **not** use the SDK's
`PluginMapper` (stream maps) at runtime, because that design infers types from expression
prefixes and cannot express per-column cleanup. It is nevertheless a **functional superset** of
stream maps: every stream-map feature has a native equivalent, and the SDK `stream_maps`,
`stream_map_config`, `faker_config` and `flattening_*` settings are accepted unchanged through a
compatibility translator ([ADR-0010](../wiki/decisions/0010-stream-map-superset.md)).

Why a mapper, rather than cleanup in each target or in dbt: one goal among several is to
avoid a dbt cleanup layer, which is SQL only, needs macros written to work across every
warehouse a project targets, and runs after the raw data (and any personal data) has
landed. In Python, upstream of every target, the cleanup is written once, with exact
decimals, real date parsing, Unicode-aware names and masking before storage.

## 2. Quality attributes

| Attribute | Target |
| -- | -- |
| Correctness | Same output for RECORD and BATCH (parity suite); output always valid against the emitted SCHEMA |
| Throughput | Measured, not targeted: on CI, about 17k rows/s for RECORD, 23k for row-wise BATCH and 110k for columnar BATCH on the benchmark stream; a gate fails a large regression ([benchmarks](../wiki/qa/benchmarks.md)). The design goals of 50k and 1M rows/s are not met: RECORD I/O uses the SDK's JSON handling, and columnar BATCH still builds each row for the row-wise parts |
| Memory | BATCH is read and written in row-group-sized chunks |
| Safety | Expression sandbox; UDFs from module paths need an explicit opt-in; no `eval` of user strings |
| Operability | Clear errors naming stream, column, row number and value; metrics; rejects; `spec validate`, `spec explain` and `doctor` |
| Compatibility | Python 3.11–3.14; singer-sdk compatible range pinned; Meltano ≥ 4 |

## 3. Component view

```
map_conform/
├── mapper.py          MapConformMapper(InlineMapper): message dispatch, lifecycle, metrics
├── settings.py        plugin settings (spec_path, spec, add_record_metadata, batch_output, …)
├── cli.py             map-conform (the mapper) + `spec validate|explain|schema|import|export`,
│                      `doctor`, `functions`
├── doctor.py          checks a Meltano project's use of map-conform
├── spec/              ── the conform spec ──
│   ├── model.py         frozen dataclasses (Spec, Defaults, StreamSpec, ColumnSpec, FieldSpec)
│   ├── steps.py         Chain, CallStep, ExprStep, CaseStep, Macro
│   ├── _struct.py       strict parsing, dumping and JSON Schema from type hints
│   ├── load.py          YAML/JSON load, variables, inheritance by presence, glob resolution
│   ├── check.py         checks against a catalog; `spec explain`
│   ├── jsonschema.py    the shipped JSON Schema (generated; a test fails when stale)
│   ├── reference.py     docs/spec-reference.md (generated; a test fails when stale)
│   ├── stream_maps.py   SDK stream_maps/flattening settings → spec (compatibility mode)
│   ├── importer.py      `spec import --stream-maps`
│   ├── bridge.py        `spec import --catalog`, `spec export --zamboni`
│   └── zamboni.py       Zamboni table-config (version 2) read/write
├── naming/            ── names ──
│   ├── conform.py       transliterate → split camel → case → replace → collapse → digits → reserved → length
│   ├── translit.py      the bundled transliteration table (ascii-table.json)
│   ├── reserved.py      reserved words per dialect (data files in reserved/)
│   ├── streams.py       output stream names
│   ├── nested.py        member names inside structs
│   ├── flatten.py       SDK-compatible flattening
│   └── shape.py         declared shapes for nested columns
├── types/             ── the canonical type system ──
│   ├── canonical.py     CType (int16…decimal(p,s)…timestamptz…struct/list/json)
│   ├── from_jsonschema.py  tap SCHEMA property → CType (undeclared columns)
│   ├── to_jsonschema.py    CType → canonical JSON Schema property (the contract)
│   ├── to_arrow.py         CType → pyarrow DataType
│   ├── wire.py             Python values → RECORD values
│   └── jsontext.py         JSON text with exact decimals
├── transforms/        ── builtins ──
│   ├── registry.py      Transform (scalar implementation, kwargs, stages) and Registry
│   ├── builtins.py      the registry of every builtin and cast, with their docs
│   ├── text.py, numeric.py, temporal.py, casts.py, nested.py, privacy.py, fake.py
│   ├── vector.py        Arrow kernels for the vectorised casts and text steps
│   └── polars_vector.py polars kernels (`engine: polars`)
├── expr/              ── expression language ──
│   ├── compiler.py      safe AST subset → closures, names resolved at compile time
│   ├── sandbox.py       allowed types, attributes and limits
│   ├── functions.py     the function library (predicates, coercion, temporal, text, …)
│   └── sdk.py           SDK stream-map expression names
├── udfs.py            UDFs: entry points `map_conform.functions`, spec `udfs:` module paths
├── plan/              ── compiled plan ──
│   ├── compile.py       StreamSpec + tap SCHEMA → StreamPlan (ordered ColumnPlans + output schema)
│   ├── chain.py         a column's steps → ops, with stage (type) tracking
│   ├── ops.py           the run-time ops (steps, expressions, case, guards, fields, shapes)
│   ├── row.py           execute a plan on one record (dict → dict)
│   ├── vector.py        which columns vectorise, and their vector chains
│   ├── lower.py         `case`/`when` conditions → Arrow masks
│   └── validate.py      `spec validate` compiles every plan
├── batch/             ── BATCH ──
│   ├── engine.py        per manifest file: columnar or row-wise, output files or RECORDs
│   ├── columnar.py      the columnar executor (vector chains + row-wise splice)
│   ├── arrow.py         rows ↔ Arrow with the declared schema
│   └── files.py         fsspec manifest I/O, parquet and JSONL readers/writers
├── metadata.py        _sdc_* columns, exactly as the SDK sets them
├── errors.py          ConformError (stream, column, row, value, rule) and on_error
├── rejects.py         the reject sink (JSONL or parquet)
└── metrics.py         per-stream counters (rows in/out/rejected/nulled/filtered, values
                       kept, members dropped, errors by column and rule)
```

## 4. Message flow

| Message | Handling |
| -- | -- |
| **SCHEMA** | Resolve the StreamSpec (by glob), then compile a StreamPlan: conform names, decide each column's CType (spec, or tap SCHEMA when undeclared), bind transforms, and check the plan (clashes, unknown functions, type-incompatible transforms). Emit the conformed SCHEMA with canonical types, `_sdc_*` when `add_record_metadata` is set, and renamed `key_properties`/`bookmark_properties`. Cache the plan per stream. |
| **RECORD** | `plan.row(record)`, then the metadata. Emit the record with `time_extracted` and `version` preserved. `on_error` decides what happens on a failure: raise, null, keep or reject. Rows dropped by `filter` are counted. |
| **BATCH** | For each manifest file: parquet in and parquet out runs the columnar executor over row-group batches; anything else (JSONL in or out, `batch_output.mode: record`, shapes, flattening, `engine: row`) runs each row through the row executor. Output files carry the declared Arrow schema and go to `batch_output.storage`; one BATCH message per output stream lists them. With `batch_output.mode: record`, RECORDs are emitted instead, for targets without BATCH support. The log says which engine ran and why. |
| **STATE** | Pass through unchanged and in order (bookmarks stay keyed by tap names). Flushed only after every preceding output message is written. |
| **ACTIVATE_VERSION** | Rename the stream and pass through. |

### 4.1 RECORD path

```
record ──▶ for each ColumnPlan: source value ─▶ pre (string) ─▶ cast ─▶ post ─▶ validate ─▶ out[name]
             │ (declared, derived, or undeclared-conform)          │ failure
             ▼                                                     ▼
           filter? ──drop──▶ metrics                          on_error: raise | null | keep | reject
```

### 4.2 BATCH path

```
parquet file ─▶ RecordBatch ─▶ vectorised columns: Arrow (or polars) kernels ─▶ values + todo mask
                     │
                     └──────▶ every row: row executor, skipping the vectorised columns
                              except their todo rows; expressions, filter, policies, _sdc_*
                ─▶ splice ─▶ Table with the declared schema ─▶ write parquet ─▶ manifest
```

A column is **vectorised** when every step of its chain has a kernel and no expression or
filter reads it. A kernel claims only the rows where it is known to agree with the scalar
code, and marks the rest *todo*; those run through the row executor and are spliced back.
Every row still passes through the row executor for the other columns, so rejects, the first
error and the metrics are exactly the RECORD path's. JSONL BATCH files run row by row.

## 5. Key design decisions

| Decision | Choice | ADR |
| -- | -- | -- |
| Name and licence | `map-conform`, Apache-2.0, Python ≥ 3.11 | [0001](../wiki/decisions/0001-name-and-licence.md) |
| Transform authoring | Builtins + macros, safe `expr`, Python UDFs | [0002](../wiki/decisions/0002-transform-authoring.md) |
| Config | Own spec file; Zamboni/catalog bridge | [0003](../wiki/decisions/0003-own-spec-with-zamboni-bridge.md) |
| BATCH engine | pyarrow core, polars optional | [0004](../wiki/decisions/0004-batch-engine.md) |
| `_sdc_*` | SDK names and values; targets set `add_record_metadata: true` | [0005](../wiki/decisions/0005-sdc-metadata.md) |
| Errors | `on_error: raise` default; null, keep, reject | [0006](../wiki/decisions/0006-error-policy.md) |
| Wire types | decimal as `x-singer.decimal` string; json as text; declared nested wins | [0007](../wiki/decisions/0007-wire-encoding.md) |
| Naming defaults | snake, ASCII, 63, reserved words get `_`, clash is an error | [0008](../wiki/decisions/0008-naming-defaults.md) |
| Undeclared columns | Conform using tap SCHEMA; `strict` makes them an error | [0009](../wiki/decisions/0009-undeclared-columns.md) |
| Stream maps | Superset of SDK stream maps and pipelinewise masking; SDK settings accepted unchanged | [0010](../wiki/decisions/0010-stream-map-superset.md) |
| UUID in BATCH | Parquet FLBA(16) with UUID logical type | [0011](../wiki/decisions/0011-uuid-in-batch.md) |
| Transliteration | Bundled table generated from pinned Unicode data plus a curated supplement | [0012](../wiki/decisions/0012-bundled-transliteration-table.md) |

## 6. Deployment in Meltano

```yaml
plugins:
  mappers:
    - name: map-conform
      namespace: map_conform          # needed while it is a custom plugin
      pip_url: map-conform            # [polars] extra optional
      executable: map-conform
      settings:                       # declare the settings you set (plugin-definition.yml has all)
        - {name: spec_path, kind: string}
        - {name: add_record_metadata, kind: boolean}
      mappings:
        - name: conform-orders
          config:
            spec_path: conform/orders.yml
            add_record_metadata: true   # add the _sdc_* columns
  loaders:
    - name: target-ducklake
      config:
        add_record_metadata: true     # keep the _sdc_* columns map-conform emits
# meltano run tap-csv conform-orders target-ducklake
```

## 7. Interfaces

| Interface | Direction | Contract |
| -- | -- | -- |
| Singer messages in | tap → mapper | Singer spec + SDK BATCH manifest |
| Singer messages out | mapper → target | [Clean-Landing Contract](../wiki/concepts/clean-landing-contract.md) |
| Conform spec | user → mapper | [conform-spec schema](../wiki/schemas/conform-spec.md), JSON Schema shipped in the package |
| UDF API | user code → mapper | `@udf` decorator / entry point `map_conform.functions` |
| Zamboni bridge | mapper ↔ Zamboni | canonical type → Zamboni `columns` string |
| Reject sink | mapper → storage | `<reject.storage>/<stream>/<run id>.jsonl` (or parquet): stream, row number, column, rule, error, value, the raw record, time |
| Metrics | mapper → log / file | INFO line per stream at the end of the run; `metrics_path` writes them as JSON |
