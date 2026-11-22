# Creating a better mapper — guidance

> Status: planning record (2026-11-21). This is the founding brief for **map-conform**.
> The docs set in [`docs/`](docs/) elaborates it; the knowledge base in [`wiki/`](wiki/index.md)
> tracks it as it evolves. Where they disagree, the newest dated decision in
> [`wiki/decisions/`](wiki/decisions/) wins.

## 1. Purpose

A Meltano/Singer **inline mapper** that sits between any tap and any target and makes the
stream *land cleanly*: by the time a SCHEMA, RECORD or BATCH message reaches the target,
names are legal, types are declared, values are cast, and metadata is present. Targets then
write; they do not clean.

```
tap ──SCHEMA/RECORD/BATCH──▶ map-conform ──clean SCHEMA/RECORD/BATCH──▶ target
                                 ▲
                         conform spec (file)
```

The mapper does five jobs, in one place:

| # | Job | Example |
| -- | -- | -- |
| a | **Value cleanup** while casting from string to a declared type | `" $1,234.50 "` → `1234.50`; `"3/7/24 4:05 PM"` → `2024-03-07T16:05:00Z`; `"#N/A"` → null |
| b | **Name conforming** of streams and columns, legal in every target | `Order Date (UTC)` → `order_date_utc`; `customerID` → `customer_id` |
| c | **Type casting and coercion** to a declared, not inferred, type | `"1"`/`"yes"`/`"Y"` → `true`; `"00123"` → `123` (int64) |
| d | **Stream prefixing / aliasing** | `orders` → `raw_shop_orders` |
| e | **`_sdc_*` metadata**, exactly as the SDK would add it, once, upstream | `_sdc_extracted_at`, `_sdc_table_version`, … |

And one non-functional job: **BATCH handled at columnar speed**. A BATCH message (parquet
preferred, JSONL supported) is transformed with Arrow (optionally Polars), and only the
columns that need Python-level logic are taken through the per-record path.

### 1.1 Why

Every target today re-implements a slightly different subset of the same cleanup (survey in
§3). The duplication is expensive and the differences are bugs: the same CSV lands with
different values depending on the target. Worse, the Singer SDK's own BATCH path skips *all*
per-record cleanup, so BATCH data is the least clean data in the system.

**The rule this project exists to enable:** *a target may assume the data lands clean.*
When reviewing a target (human or AI reviewer), do not add value cleanup, coercion or name
conforming to the target. Point to the [Clean-Landing Contract](wiki/concepts/clean-landing-contract.md)
instead; if the contract is missing a guarantee, fix it here.

## 2. Name

**`map-conform`** — PyPI `map-conform`, module `map_conform`, executable `map-conform`,
Meltano plugin `map-conform` (namespace `map_conform`). Alternatives considered:
`uni-mapper` (generic, unsearchable), `ca-bien-mapper` (memorable, opaque), `map-tidy`
(weaker on the declared-contract idea). "Conform" names the job: conform names, types and
values to a declared contract. See [ADR-0001](wiki/decisions/0001-name-and-licence.md).

Licence Apache-2.0, Python ≥ 3.11, scaffolded from the Singer SDK mapper cookiecutter
(hatchling + hatch-vcs, ruff, mypy, pytest, tox-uv, GitHub Actions trusted publishing).

## 3. Survey: what existing systems do

Six systems were read. The tables list what each does to SCHEMA, RECORD and BATCH, so the
mapper can do the union *once*, correctly. Private code was surveyed for behaviour only; no
private code or names are reproduced.

### 3.1 Systems surveyed

| System | Kind | Public |
| -- | -- | -- |
| Singer SDK `InlineMapper` / `PluginMapper` (stream maps, flattening) | library | yes |
| `meltano-map-transformer` | mapper (thin wrapper over SDK stream maps) | yes |
| `pipelinewise-transform-field` | mapper (masking/hashing) | yes |
| A private lowercase-keys mapper | mapper (lowercase + stream prefix) | no — behaviour only |
| `target-ducklake` | target (DuckDB / DuckLake) | yes |
| A private Iceberg target (uses Zamboni table-config for partitioning) | target | no — behaviour only |
| Zamboni table-config | table layout & maintenance spec | yes |

### 3.2 Name conforming

| Behaviour | SDK SQL `conform_name` | lowercase-keys mapper | target-ducklake | Iceberg target |
| -- | -- | -- | -- | -- |
| Default on? | in SQL sinks | yes | **no** (opt-in `conform_column_names`) | yes |
| Lowercase | ✓ | ✓ (only this) | ✓ | ✓ |
| Strip chars outside `[A-Za-z0-9_\-.\s]` (drops non-ASCII) | ✓ | – | ✓ | ✓ |
| `.`, `-`, space → `_` | ✓ | – | ✓ | ✓ |
| camelCase → snake_case | – | – | – | – |
| Leading digit | → letter (0→a …) | – | → letter | → letter |
| Reserved words | – | – (TODO) | – | logged only |
| Max length / truncation | – | – | 63 for Postgres catalog, `_i` suffix | – |
| Clash detection | – | **silent overwrite** | error | error |
| Nested member names | – | – | – | – |
| Stream/table names | – | lowercase + prefix | split on `-` → schema/table | conform |
| Applied to `required`, `key_properties` | partial | **`required` missed** | ✓ | ✓ |

**Takeaway.** Nobody splits camelCase, nobody handles reserved words, nobody conforms nested
member names, and the private mapper silently merges `Id` and `ID`.

### 3.3 Type mapping (JSON Schema → storage type)

| JSON Schema | target-ducklake | Iceberg target |
| -- | -- | -- |
| `integer` | INTEGER if bounds fit int32, else BIGINT | long (int via hints or bounds) |
| `number` | DECIMAL(38,9) default; honours non-standard `precision`/`scale` | double (float via hints) |
| `string` + `x-singer.decimal` + p,s | DECIMAL(p,s); else VARCHAR | decimal(p,s); invalid → string |
| `x-sql-datatype` hints | many, validated against JSON type | some (decimal, int widths, float, uuid, tz flavour) |
| `date-time` | TIMESTAMPTZ default (configurable) | timestamptz default; naive via hint |
| `date` / `time` / `uuid` | DATE / TIME / UUID | date / time / uuid |
| `contentEncoding: base64` | BLOB | binary |
| object with props | STRUCT (or flatten / JSON) | struct |
| object w/o props, array w/o items | JSON | string holding JSON text |
| `anyOf`/`oneOf` | first non-null branch | **string + warning (not handled)** |
| several non-null types | VARCHAR | string |

**Takeaway.** Every target hand-rolls hint parsing, and they disagree (e.g. bare `number` is
DECIMAL(38,9) in one and double in the other). A single declared type with a single canonical
JSON-Schema rendering removes the guessing.

### 3.4 Value cleanup and coercion on RECORD

| Cleanup | SDK target base | target-ducklake | Iceberg target | Mappers |
| -- | -- | -- | -- | -- |
| ISO timestamp parse (`fromisoformat`), top-level only | ✓ (error on failure) | via SDK | via SDK | – |
| Non-ISO timestamp formats (`strptime`) | – | opt-in `type_source` + `x-parse-format` | opt-in `type_source` | – |
| Epoch → timestamp | – | – (never loads) | – | – |
| Excel/Sheets serial dates | – | – | – | – |
| Naive timestamp assumed UTC | – | ✓ for TIMESTAMPTZ | ✓ | – |
| Offset → UTC | – | ✓ (opt-in for TIMESTAMP) | ✓ | – |
| Empty/whitespace → null | – | `type_source` only | `type_source` only | – |
| Null tokens (`N/A`, `#N/A`, `NULL`, `-`) | – | – | – | – |
| Currency/thousands stripping | – | `type_source` (validated groups) | `type_source` (crude regex) | – |
| Parenthesised negatives `(5)` | – | rejected | – | – |
| Boolean words (`yes/y/t/1`…) | – | `type_source` | `type_source` | – |
| int from `"12.0"` / fraction | – | truncate (type_source) / round half-up (staging) | `int(float())` truncation | – |
| Decimal quantize to scale | – | ROUND_HALF_UP | `Decimal(str(v))` | – |
| NaN/Inf | – | passes into float/JSON, fails decimal/int | unhandled | – |
| JSON text → object for object columns | – | ✓ | – | – |
| object/array → JSON text | – | ✓ (keeps all digits) | ✓ (`default=str`) | SDK flattening |
| base64 strict decode | – | ✓ | ✓ | – |
| `on_error` policy | ERROR/MAX/NULL for dates | raise/null/string | raise/null/string | **pipelinewise swallows errors** |
| Masking / hashing | – | – | – | pipelinewise (SET-NULL, HASH, MASK-\*) |
| Undeclared fields | kept | kept | **silently dropped** | – |

**Takeaway.** Two targets each built a `type_source` coercion layer, with different number
grammars and different integer rounding. That is exactly the duplicate-but-different logic
this project removes.

### 3.5 `_sdc_*` metadata

| Column | JSON type | Value (SDK) |
| -- | -- | -- |
| `_sdc_extracted_at` | date-time | message `time_extracted` |
| `_sdc_received_at` | date-time | now (UTC) |
| `_sdc_batched_at` | date-time | batch start, else now |
| `_sdc_deleted_at` | date-time | preserved from the record |
| `_sdc_sequence` | integer | `round(time.time()*1000)` (not unique within a ms) |
| `_sdc_table_version` | integer | message `version` |
| `_sdc_sync_started_at` | integer | target start, epoch ms |

**Behaviour that matters (verified in SDK source):** with `add_record_metadata: false`, the
default, an SDK target **removes all seven columns from the schema and from every record**
(`singer_sdk/sinks/core.py` `_remove_sdc_metadata_from_schema`, `target_base.py`). With
`true` it **overwrites** them with its own values. Both targets above add workarounds to keep a
tap-declared `_sdc_deleted_at`. The SDK BATCH path applies neither stripping nor adding.

**Decision ([ADR-0005](wiki/decisions/0005-sdc-metadata.md)).** map-conform emits the
SDK names and values exactly, declared in SCHEMA. Downstream SDK targets **must set
`add_record_metadata: true`** to keep them; the values they then overwrite are approximately
equal. This is documented, not worked around.

### 3.6 BATCH

| System | BATCH behaviour |
| -- | -- |
| SDK `InlineMapper` | `map_batch_message` raises `NotImplementedError` |
| meltano-map-transformer | inherits the raise, so **any BATCH crashes the pipeline** |
| pipelinewise-transform-field | unknown message type, so it crashes |
| lowercase-keys mapper | renames the stream but **not the file contents** (silent corruption) |
| SDK tap encoders | JSONL is always gzip; parquet Arrow schema is **inferred from data**, not from JSON Schema; tap-side batches bypass stream maps |
| SDK target base | `read_table().to_pylist()`: no maps, no metadata, no validation, no timestamp parsing |
| target-ducklake | reads parquet in chunks and converts **every value back to JSON form**, then runs the RECORD path |
| Iceberg target | parquet → `to_pylist()` → dict → Arrow again; **skips all per-record cleanup** |

**Takeaway.** No component in the ecosystem transforms BATCH columnar data. map-conform is the
first: Arrow in, Arrow out, declared schema.

### 3.7 Mapper-specific defects to avoid

- meltano-map-transformer overwrites `time_extracted` with `now()`, which corrupts
  `_sdc_extracted_at`, and drops `bookmark_properties` (it reads `bookmark_keys`).
- SDK stream-map type inference is by **expression prefix** (`int(` → integer); `int(x) if x else None` is typed string, and values are never coerced to the inferred type.
- SDK stream-map runtime errors (`None.split`) crash the run; there is no per-record policy.
- There is no "apply to every column" operator, so per-column conforming is impossible
  through stream maps.
- pipelinewise-transform-field: `equals: 0` is ignored (truthiness bug), single-digit `n`
  only, exceptions swallowed so masking failures leak PII, ACTIVATE_VERSION dropped on flush.

### 3.8 Zamboni table-config

The table-config is a **physical layout and maintenance** spec: partition and partition
evolution, ordering/z-order, retention, file sizing, and `write` (mode, identifier fields,
append-only, full-refresh). Its `columns` block is `{name: "free-form type string"}` with no
vocabulary, precision/scale structure, nullability, renames or docs, and nothing acts on it.
Its *engineering* patterns are worth copying: strict parsing (unknown keys rejected),
inheritance by presence (objects merge, lists replace), JSON Schema generated from frozen
dataclasses with a staleness test, and catalog-embedded authoring (`x-iceberg`).

**Decision ([ADR-0003](wiki/decisions/0003-own-spec-with-zamboni-bridge.md)).** map-conform owns a
**logical** spec (names, types, values). It ships a bridge that *exports* each column's
canonical type into Zamboni `columns`, and that *imports* from a Singer catalog or an
existing Zamboni file. The physical and logical concerns stay separate, as Zamboni intends.

### 3.9 Features that must be kept (stream maps and masking)

map-conform **replaces nothing without an equivalent**. It is a better stream map, not a
narrower one ([ADR-0010](wiki/decisions/0010-stream-map-superset.md); the full mapping table is
in [detailed design §15](docs/detailed-design.md#15-stream-map-compatibility)).

| Feature | Source | map-conform |
| -- | -- | -- |
| Stream alias, filter, key override, glob matching | SDK stream maps | `alias`, `filter`, `key_properties`, glob keys |
| Split or copy a stream (`__source__`) | SDK stream maps | `source` on a new output-stream key |
| Drop streams or properties, `__else__` | SDK stream maps | `drop`, top-level `else`, `undeclared: drop` |
| Expressions with `record`, `self`, `config`, `md5`, `sha256`, `uuid4`, `datetime`, `json` | SDK stream maps | same names, plus a richer library |
| `fake` (Faker) with seed and locale | SDK stream maps | `fake` function and builtin step, `defaults.faker` |
| Flattening (depth, separator, key length) | SDK | `nested: flatten`, same algorithm |
| SET-NULL, HASH, HASH-SKIP-FIRST-n, MASK-DATE, MASK-NUMBER, MASK-HIDDEN, MASK-STRING-SKIP-ENDS-n | pipelinewise-transform-field | builtins, with SCHEMA kept consistent |
| Conditional masking (`when` equals / regex) | pipelinewise-transform-field | `when` expr on a column or step |
| Nested field paths | pipelinewise-transform-field | `fields: {path: …}` |
| Validate config against a catalog | pipelinewise-transform-field | `spec validate --catalog` |

**Drop-in.** The SDK settings (`stream_maps`, `stream_map_config`, `faker_config`,
`flattening_*`) are accepted unchanged and translated into the spec. Undeclared expression
types use the SDK's inference rules, so outputs match. `spec import --stream-maps` migrates a
config to a native spec.

## 4. Design principles

1. **Declared, not inferred.** Every output column has one declared type. If the spec does not
   declare it, the tap's SCHEMA is the declaration. Nothing is guessed from values.
1. **Clean once, upstream.** Any cleanup a target would need is a bug in this project.
1. **Fail loud by default.** `on_error: raise`. A data engineer fixes the cleanup or drops the
   column. Opt-in alternatives are `null`, `keep` (when the declared type is string) and
   `reject` (rows go to a dead-letter file).
1. **Builtins first, expressions second, Python third.** Most columns need one short
   declarative cleanup. Expressions cover the ad-hoc cases, and registered Python functions
   (UDFs) cover the rest.
1. **Columnar when it can be, row-wise only where it must.** BATCH stays Arrow. A
   non-vectorisable column is computed row-wise and spliced back into the Arrow table.
1. **The same plan for both paths.** RECORD and BATCH execute the same compiled plan, so they
   give the same result. A test suite enforces this (parity tests).
1. **Config by file.** Meltano passes plugin config through the environment, with a ~128 KiB
   per-variable limit. The spec is a YAML/JSON file referenced by path (`spec_path`), with
   `spec` inline only for small cases.
1. **Strict, versioned, self-describing spec.** Unknown keys are rejected, and the JSON Schema
   is generated from code. `map-conform spec validate|explain|export` lets users check it.

## 5. The conform spec (summary)

The full reference is in [docs/detailed-design.md §3](docs/detailed-design.md#3-the-conform-spec),
and the schema page is in [wiki/schemas/conform-spec.md](wiki/schemas/conform-spec.md).

```yaml
version: 1
defaults:                          # inherited by every stream; objects merge, lists replace
  naming: {case: snake, ascii: transliterate, max_length: 63,
           reserved_words: suffix, on_collision: error}
  values: {trim: true, null_tokens: ["", "NULL", "N/A", "#N/A", "-"]}
  timestamp: {assume_tz: UTC}
  on_error: raise
  metadata: sdc                    # the seven SDK _sdc_* columns
  undeclared: conform              # conform | drop | error

macros:                            # named, parameterised transform chains
  money: [{strip_chars: "$€£, "}, {cast: decimal, parens_negative: true}]

udfs:                              # Python functions; module paths need allow_python_udfs: true
  fiscal_week: "my_pkg.udfs:fiscal_week"

streams:
  "sheets-*":                      # glob; the most specific match wins
    prefix: raw_sheets_
  orders:
    alias: raw_shop_orders
    key_properties: [order_id]
    filter: "status != 'TEST'"
    columns:
      "Order ID":   {name: order_id, type: int64, nullable: false}
      "Total":      {type: "decimal(18,2)", transform: money}
      "Order Date": {type: timestamptz,
                     parse: {formats: ["%m/%d/%Y %I:%M %p", excel_serial, iso], tz: America/New_York}}
      "Shipped?":   {type: boolean, true_values: [Y, yes, shipped]}
      "Payload":    {type: json}
      "SSN":        {drop: true}
      week:         {type: int32, expr: "fiscal_week(order_date)"}   # derived column
      "Amount":
        type: "decimal(12,2)"
        transform:
          case:
            - when: is_number(value)
              then: {cast: decimal}
            - when: is_string(value)
              then: [money]
            - else: {on_error: reject}
```

## 6. What targets receive: the Clean-Landing Contract (summary)

The full text is in [wiki/concepts/clean-landing-contract.md](wiki/concepts/clean-landing-contract.md).
A target built against map-conform may assume all of the following.

- **Names.** Stream names, column names and nested member names match
  `^[a-z_][a-z0-9_]*$`, are at most `max_length` long, are not reserved words, and are unique
  under case folding. `key_properties`, `required` and `bookmark_properties` use the conformed
  names.
- **Schema.** Every property has exactly one non-null JSON type, plus `null` if it is
  nullable. There is no `anyOf`/`oneOf`. Type metadata is canonical:
  - `format: date-time | date | time | uuid`
  - `x-sql-datatype` naming the canonical type
  - decimals as `{"type":"string","format":"x-singer.decimal","precision":p,"scale":s}`
  - integer widths as `minimum`/`maximum`
- **Values.**
  - `timestamptz`: ISO-8601 UTC with `Z` and 6 fraction digits.
  - `timestamp` (naive): ISO without an offset.
  - `date`, `time`: ISO.
  - Decimals: strings already quantized to the scale, never NaN.
  - Integers: JSON integers in range.
  - Floats: finite, or null.
  - Booleans: JSON booleans.
  - `json` columns: JSON *text*.
  - Declared `struct`/`list`: typed nested values with conformed member names.
  - No empty strings where the type is not string.
- **Metadata.** The seven `_sdc_*` columns are present in SCHEMA and RECORD, with SDK semantics.
- **BATCH.** Files are parquet (or JSONL) whose Arrow schema is the declared schema exactly.
  Decimals are `decimal128(p,s)`, `timestamptz` is `timestamp[us, UTC]`, and `json` is `string`.

**Reviewer instruction (copy into target repos' `CLAUDE.md` / review prompts):**

> This target receives data through map-conform and relies on the Clean-Landing Contract
> (link). Assume names are conformed, types are declared and values are already cast. Do
> **not** suggest or add value cleanup, string parsing, timestamp normalisation, decimal
> quantisation, name conforming, or `_sdc_*` handling in this target. A target may still
> validate cheaply (assert, not repair) and must still own table semantics (keys, merge,
> dedupe, schema evolution, partitioning). If clean data is not being delivered, file the
> gap against map-conform.

## 7. Decisions taken in planning (quiz record)

| # | Question | Decision |
| -- | -- | -- |
| 1 | Name | `map-conform` |
| 2 | Licence / Python | Apache-2.0 / ≥ 3.11 (amended from 3.10 after its end of life) |
| 3 | How transforms are written | Declarative builtins with kwargs, a safe `expr` language with conditionals, and registered Python UDFs |
| 4 | Config format | Own versioned spec, with a bridge to Zamboni `columns` and to Singer catalogs |
| 5 | BATCH engine | pyarrow core; polars as an optional extra |
| 6 | `_sdc_*` | SDK names and values exactly; targets need `add_record_metadata: true` (documented only) |
| 7 | Cast failure default | `on_error: raise`; also `null`, `keep` and `reject` (dead-letter) |
| 8 | Decimal on the wire | `string` + `x-singer.decimal` + precision/scale (few targets honour `x-sql-datatype`) |
| 9 | Nested data | Declared struct/list wins; default `json` emitted as JSON text; optional flattening |
| 10 | Undeclared columns | Conform them using the tap SCHEMA type; `strict` makes them an error |
| 11 | Naming defaults | snake_case, ASCII transliteration, 63 characters, reserved words get `_` appended, clash is an error |
| 12 | Tracking | gh agile, key `MAPC`, 2-week sprints, public repo created after review |
| 13 | Stream maps | Superset: every SDK stream-map and pipelinewise masking feature kept; SDK settings accepted unchanged and translated |
| 14 | UUID in BATCH | Parquet `fixed_len_byte_array(16)` with the UUID logical type (verified with pyarrow + DuckDB); string in RECORD |
| 15 | `_sdc_batched_at` | BATCH: input file last-modified time; RECORD: mapper start time |
| 16 | `filter` / `when` names | Conformed names |
| 17 | Transliteration table | Bundled: generated from pinned Unicode decompositions plus a curated supplement; no GPL source ([ADR-0012](wiki/decisions/0012-bundled-transliteration-table.md)) |
| 18 | SDK `_sdc_*` proposal | None. The Singer spec and the SDK own that behaviour |
| 19 | Excel serial 60 | An error: Lotus's 1900-02-29 never existed; serials below 60 count from 1899-12-31 |
| 20 | `half_up` rounding | Halves round away from zero (`-12.5` → `-13`) |

## 8. Where to go next

- [docs/exec-overview.md](docs/exec-overview.md): the one-page pitch.
- [docs/architecture-hld.md](docs/architecture-hld.md): components and message flow.
- [docs/detailed-design.md](docs/detailed-design.md): the spec grammar, the type system,
  builtins, expressions, UDFs, and the BATCH engine.
- [docs/plan-wbs.md](docs/plan-wbs.md): phases, the WBS, and the initiative, epics and stories.
- [wiki/index.md](wiki/index.md): the knowledge base.
