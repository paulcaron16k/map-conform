# map-conform — Architecture and high-level design

Related: [exec overview](exec-overview.md) · [detailed design](detailed-design.md) ·
[plan](plan-wbs.md) · [guidance](../creating-a-better-mapper-guidance.md)

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

## 2. Quality attributes

| Attribute | Target |
|---|---|
| Correctness | Same output for RECORD and BATCH; output always valid against the emitted SCHEMA |
| RECORD throughput | ≥ 50k rows/s for a 20-column all-builtin stream on one core (orjson I/O) |
| BATCH throughput | ≥ 1M rows/s for an all-vectorisable stream; memory bounded by a row-group-sized chunk |
| Safety | Expression sandbox; UDFs from module paths need an explicit opt-in; no `eval` of user strings |
| Operability | Clear errors naming stream, column, row number and value; metrics; a `doctor` command |
| Compatibility | Python 3.10–3.13; singer-sdk compatible range pinned; Meltano ≥ 3 |

## 3. Component view

```
map_conform/
├── mapper.py          ConformMapper(InlineMapper): message dispatch, lifecycle
├── settings.py        plugin settings (spec_path, spec, batch_output, allow_python_udfs, …)
├── spec/              ── the conform spec ──
│   ├── model.py         frozen dataclasses (Spec, Defaults, StreamSpec, ColumnSpec, …)
│   ├── load.py          YAML/JSON load, strict parse, inheritance by presence, glob resolution
│   ├── jsonschema.py    JSON Schema generated from the model (and a staleness test)
│   └── bridge/          catalog import, Zamboni columns export/import, stream_maps import
├── naming/            ── name conformer ──
│   ├── conform.py       pipeline: transliterate → split camel → case → replace → collapse → digits → reserved → length
│   └── reserved/        reserved-word lists per dialect (data files)
├── types/             ── the canonical type system ──
│   ├── canonical.py     CType (int16…decimal(p,s)…timestamptz…struct/list/json)
│   ├── from_jsonschema.py  tap SCHEMA property → CType (undeclared columns)
│   ├── to_jsonschema.py    CType → canonical JSON Schema property (the contract)
│   └── to_arrow.py         CType → pyarrow DataType
├── transforms/        ── builtins ──
│   ├── registry.py      Transform protocol, kwargs schema, scalar + optional arrow impls
│   ├── text.py          trim, strip_chars, null_tokens, regex_replace, case, normalize_unicode …
│   ├── numeric.py       cast int/float/decimal, parens_negative, percent, round, clamp …
│   ├── temporal.py      parse formats, excel_serial, epoch, assume_tz, to_utc …
│   ├── boolean.py, json_.py, binary.py
│   ├── privacy.py       hash, mask, set_null, redact_date, mask_number, mask_hidden, tokenize, fake
├── compat/            stream_maps → spec translator (SDK names, prefix type inference, flattening)
├── expr/              ── expression language ──
│   ├── parser.py        safe AST subset (simpleeval-compatible superset)
│   ├── functions.py     is_* predicates, coalesce, parse_datetime, ensure_utc, re_*, math …
│   └── compile.py       expr → closure (row) / arrow expression where possible
├── udf/               registry: entry points `map_conform.functions`, spec `udfs:` module paths
├── plan/              ── compiled plan ──
│   ├── compile.py       StreamSpec + tap SCHEMA → StreamPlan (ordered ColumnPlans + output schema)
│   ├── row.py           execute a plan on one record (dict → dict)
│   └── columnar.py      execute a plan on a pyarrow.RecordBatch (vectorised + splice)
├── batch/             manifest read/write, parquet & JSONL readers/writers, storage (fsspec)
├── metadata.py        _sdc_* columns, exactly as the SDK sets them
├── errors.py          ConformError (stream, column, row, value, rule), on_error, reject sink
├── metrics.py         per-stream counters (rows in/out, nulls made, rejects, casts by rule)
└── cli.py             map-conform (mapper) + `spec validate|explain|export|import`, `doctor`
```

## 4. Message flow

| Message | Handling |
|---|---|
| **SCHEMA** | Resolve the StreamSpec (by glob), then compile a StreamPlan: conform names, decide each column's CType (spec, or tap SCHEMA when undeclared), bind transforms, and check the plan (clashes, unknown functions, type-incompatible transforms). Emit the conformed SCHEMA with canonical types, `_sdc_*` and renamed `key_properties`/`bookmark_properties`. Cache the plan per stream. |
| **RECORD** | `plan.row(record)`, then the metadata. Emit the record with `time_extracted` and `version` preserved. `on_error` decides what happens on a failure: raise, null, keep or reject. Rows dropped by `filter` are counted. |
| **BATCH** | For each manifest file: read in chunks (parquet `iter_batches`, JSONL by line blocks), run `plan.columnar(batch)`, and write a new file with the declared Arrow schema to `batch_output.storage`. Emit one BATCH with the new manifest. Optionally (`batch_output.mode: record`) emit RECORDs instead, for targets without BATCH support. |
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
parquet/JSONL file ─▶ RecordBatch chunk ─▶ ColumnPlan kind?
                                             ├─ vectorised ─▶ pyarrow.compute kernels (or polars expr)
                                             └─ row-wise   ─▶ to_pylist(that column [+ deps]) ─▶ row executor ─▶ pa.array(type)
                                           ─▶ assemble Table with declared schema ─▶ write parquet ─▶ manifest
```

A column is **vectorised** if every step of its chain has an Arrow implementation. Otherwise it
is **row-wise**: only that column and the columns its `expr`/UDF reads are converted to Python.
Rows rejected by any column are removed with a mask and written to the reject sink.

## 5. Key design decisions

| Decision | Choice | ADR |
|---|---|---|
| Name and licence | `map-conform`, Apache-2.0, Python ≥ 3.10 | [0001](../wiki/decisions/0001-name-and-licence.md) |
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

## 6. Deployment in Meltano

```yaml
plugins:
  mappers:
    - name: map-conform
      pip_url: map-conform            # [polars] extra optional
      executable: map-conform
      settings:
        - {name: spec_path, kind: string}
        - {name: allow_python_udfs, kind: boolean}
      config:
        spec_path: ${MELTANO_PROJECT_ROOT}/conform/orders.yml
      mappings:
        - name: conform-orders
          config:
            spec_path: ${MELTANO_PROJECT_ROOT}/conform/orders.yml
  loaders:
    - name: target-ducklake
      config:
        add_record_metadata: true     # keep the _sdc_* columns map-conform emits
# meltano run tap-csv conform-orders target-ducklake
```

## 7. Interfaces

| Interface | Direction | Contract |
|---|---|---|
| Singer messages in | tap → mapper | Singer spec + SDK BATCH manifest |
| Singer messages out | mapper → target | [Clean-Landing Contract](../wiki/concepts/clean-landing-contract.md) |
| Conform spec | user → mapper | [conform-spec schema](../wiki/schemas/conform-spec.md), JSON Schema shipped in the package |
| UDF API | user code → mapper | `@udf` decorator / entry point `map_conform.functions` |
| Zamboni bridge | mapper ↔ Zamboni | canonical type → Zamboni `columns` string |
| Reject sink | mapper → storage | JSONL/parquet: original row, stream, column, rule, error |
