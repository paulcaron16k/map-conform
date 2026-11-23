# map-conform — Detailed design

Related: [HLD](architecture-hld.md) · [plan](plan-wbs.md) · [contract](../wiki/concepts/clean-landing-contract.md)

This document explains how each feature behaves, and why, as built in 0.1.0. Every key, its
type and default is listed in the generated [spec reference](spec-reference.md), which wins
where the two differ; worked examples are in the [cookbook](cookbook.md). Sections written
before a feature was built are marked "As built" where the build differs from the design.

## 1. Plugin settings (Meltano / `--config`)

The plugin settings are kept small on purpose. The real configuration is in the spec file,
so Meltano's ~128 KiB-per-environment-variable limit never applies to it.

The mapper validates the settings and loads the spec when it starts, before reading any
input. Problems are reported the way the Singer SDK reports config errors: each is logged
with its path, and the exit status is 1. With neither `spec_path` nor `spec`, the mapper
conforms with the default rules. The settings are a frozen dataclass
(`map_conform/settings.py`), and `config_jsonschema` is generated from it. `meltano.yml`
declares the same settings, and a test keeps the two in step.

| Setting | Type | Default | Meaning |
| -- | -- | -- | -- |
| `spec_path` | string | — | Path to the conform spec file (YAML or JSON). Relative paths resolve against the current directory, which is the project root under Meltano. |
| `spec` | object | — | An inline spec for small cases. If both are given, `spec` is deep-merged over `spec_path`. |
| `spec_vars` | object | `{}` | Values for `${var}` substitution in the spec, e.g. `prefix`. Environment variables are also visible as `${env:NAME}`. |
| `strict` | boolean | false | Overrides `defaults.undeclared` to `error` and makes warnings errors. |
| `allow_python_udfs` | boolean | false | Allows `udfs:` entries given as module paths. Entry-point UDFs from installed packages are always allowed. |
| `batch_output.mode` | `batch` \| `record` | `batch` | Whether BATCH input is written out as new files (`batch`) or as RECORD messages (`record`). |
| `batch_output.format` | `parquet` \| `jsonl` | `parquet` | Output encoding for BATCH. |
| `batch_output.compression` | `zstd` \| `snappy` \| `gzip` \| `none` | `zstd` (parquet), `gzip` (jsonl) |  |
| `batch_output.storage.root` | string | input file's directory | Where output files go: an fsspec URL (`file://`, `s3://`, …). |
| `batch_output.storage.params` | object | `{}` | fsspec storage options, used to read the manifest files and to write the output. |
| `batch_output.delete_input` | boolean | false | Delete each input file after its output is written. |
| `batch_output.row_group_size` | integer | 131072 | Rows per parquet row group, which is also the size of each processing chunk. |
| `reject.storage` | string | `./.map-conform/rejects` | Where the dead-letter files go. |
| `reject.format` | `jsonl` \| `parquet` | `jsonl` |  |
| `metrics_path` | string | — | Write per-stream metrics as JSON at the end of the run. |
| `add_record_metadata` | boolean | false | Add the seven `_sdc_*` columns to SCHEMA, RECORD and BATCH output. The same as `defaults.add_record_metadata`, which a stream can override. |
| `stream_maps` | object | — | **SDK-compatible.** Accepted unchanged and translated into the spec at startup (§15). The native spec wins where both define a column. |
| `stream_map_config` | object | — | **SDK-compatible.** Exposed as `config` in expressions; merged with `spec_vars`. |
| `faker_config` | object | — | **SDK-compatible.** `{seed, locale}`; same as `defaults.faker`. |
| `flattening_enabled` / `flattening_max_depth` / `flattening_separator` / `flattening_max_key_length` |  | — | **SDK-compatible.** Same as `defaults.nested: flatten` plus `defaults.flatten.*`. |

## 2. CLI

```
map-conform --config CONFIG [--input FILE]          # the mapper (SDK CLI)
map-conform spec validate SPEC [--catalog C] [--var N=V] [--strict] [--allow-python-udfs]  # strict parse, compiled plans
map-conform spec explain SPEC --stream S [--catalog C] [--var N=V] [--json] [--allow-python-udfs]  # rules, output names, columns
map-conform spec schema                              # print the spec's JSON Schema
map-conform spec import --catalog C [--zamboni TC] [--namespace NS] [-o OUT]  # draft a spec from a catalog (+ Zamboni columns)
map-conform spec export SPEC --zamboni TC --catalog C [--namespace NS] [-o OUT]  # write canonical types into Zamboni `columns`
map-conform spec import --stream-maps CONFIG.json [--catalog C] [-o OUT]  # SDK stream_maps (+ flattening) to a native spec
map-conform doctor [--meltano-yml meltano.yml] [--strict]  # check targets have add_record_metadata, etc.
map-conform functions [--json]                       # list builtins, kwargs, the engines that vectorise each
```

`spec validate` reports every problem, each with its path, and exits 1 when there is an
error (or a warning, with `--strict`). With `--catalog` it also checks each catalog stream's
outputs:

- output stream names, including alias legality and collisions between outputs;
- that columns and sources exist (a new column needs `expr`);
- that explicit `name:`s are legal, and output-name collisions;
- that `key_properties` exist and that no key property is dropped;
- `undeclared: error`.

It then compiles every plan, so step and `parse` options, macro calls, expressions and type
flow are checked before a run (`map_conform/plan/validate.py`). With `--catalog`, each
catalog stream's outputs compile against its schema, as the mapper will; a path the catalog
check already faults gets no second finding. Without one, each stream rule compiles
against the tap columns it implies: those it declares, and any name its expressions read or
its `key_properties` list. Steps start from the raw value either way, so only a column's
type depends on the tap; problems in a tap column with no declared `type` (or `shape`) are
warnings, since a string was assumed. A problem with a `parse` option is reported at
`columns.<c>.parse.<key>`.

As built (`map_conform/spec/bridge.py`, `map_conform/spec/zamboni.py`, WBS 9.1–9.2):

- **`spec import --catalog`** drafts a spec: one rule per catalog stream with its key
  properties, and each property as a column with an explicit canonical type (inferred as
  the plan would, objects as `json`) and its description as `doc`. Names are left to the
  conformer. The draft validates against its catalog.
- **`--zamboni TC`** takes column types from a Zamboni table-config (version 2, JSON or
  YAML). The table is matched by the conformed output stream name, columns by output name,
  and `defaults.columns` applies under the table's own. Aliases are read (`long` is
  int64); a type map-conform does not know keeps the catalog's, with a note.
- **`spec export SPEC --zamboni TC --catalog C`** compiles each catalog stream as the mapper
  would and writes `namespaces.<ns>.tables.<output stream>.columns` as
  `{output column: CType}`, with the `_sdc_*` columns when they are added. Everything else
  in the file is kept, a missing table is created, and `-o` writes elsewhere. With several
  namespaces, `--namespace` is required.

**`doctor`** (`map_conform/doctor.py`, WBS 9.3) checks each map-conform mapping in
`meltano.yml` (the mapping's config over the plugin's):

- the settings are valid;
- `spec_path` exists (relative to the project), and the spec, with any `stream_maps`, loads;
- module-path `udfs` have `allow_python_udfs: true` (the setting alone is a note);
- when the mapping adds `_sdc_*` (the setting, or `add_record_metadata` anywhere in the
  spec), each loader after it in a job sets `add_record_metadata: true`, following
  `inherit_from`. With no job using the mapping, every loader is checked.

Errors exit 1, and `--strict` also fails on warnings. Config set only in the environment is
invisible to it, which its messages say.

Rules that match no catalog stream are warnings. An explicit `name:` is never renamed, so a
conformed name that collides with it is an error, even under `on_collision: suffix`.
`spec explain` uses the same column naming as the plan compiler.

## 3. The conform spec

### 3.1 Top level

| Key | Type | Required | Meaning |
| -- | -- | -- | -- |
| `version` | `1` | ✓ | The spec version. Pinned with `const`. |
| `defaults` | Defaults |  | Inherited by every stream. |
| `macros` | `{name: Chain}` |  | Named, parameterised transform chains. |
| `udfs` | `{name: "module:attr"}` |  | Python functions, each made available as a transform and an expression function. |
| `streams` | `{glob: StreamSpec}` |  | Per-stream rules. A key is an fnmatch glob over the **tap's** stream name, or, when the StreamSpec has `source`, the name of a new output stream (§3.2). |
| `else` | `keep` \| `drop` |  | What happens to tap streams that match no key. Default `keep`, which conforms them with the defaults. SDK equivalent: `stream_maps.__else__: null` → `drop`. |

Parsing rules (the Zamboni pattern):

- Unknown keys are an error everywhere.
- `null` is allowed only where documented.
- **Inheritance is by presence.** Objects merge key by key, and lists replace whole. Resolution
  order is `defaults` → each matching glob from least to most specific → the exact name.
  Specificity is (literal characters, glob length).
- Validation runs on the merged result.
- Globs are `fnmatch` patterns, matched case-sensitively. A key whose rules have `source`
  is an output-stream name, not a glob. It inherits from `defaults` only.
- YAML is read with YAML 1.2 core-schema scalars: only `true`/`false` are booleans, so
  `yes`, `no`, `on`, `off` and `NO` stay strings, and `1:30` and dates stay strings. A
  duplicate key is an error.
- Substitution runs on string values after loading and merging: `${name}` comes from
  `spec_vars`, `${env:NAME}` from the environment, and `${name:-default}` /
  `${env:NAME:-default}` supply a fallback. A string that is exactly one `${name}` takes the
  value's type. `$${` writes a literal `${`. Inside a macro, its own `params` are left for
  expansion. An unknown name is an error, reported with its path.
- The JSON Schema is generated from the dataclasses and shipped as
  `map_conform/map-conform-spec.schema.json`. A test fails if the shipped schema is stale.

### 3.2 Defaults and StreamSpec

```yaml
defaults:
  naming:
    preset: map-conform          # map-conform | sdk (the Singer SDK's conform_name, byte for byte)
    case: snake                  # snake | lower | upper | preserve
    split_camel: true            # customerID → customer_id; HTTPServer → http_server
    ascii: transliterate         # transliterate (Ünïcode→Unicode) | strip | keep
    replace_invalid: "_"         # any char outside [a-z0-9_] after casing
    collapse: true               # "__" → "_" ; trim leading/trailing "_"
    leading_digit: prefix        # prefix "_" | letter (SDK: 0→a) | error
    max_length: 63
    truncate: hash               # hash: keep head + "_" + 6-hex of full name | error
    reserved_words: suffix       # suffix "_" | prefix "_" | error | ignore
    reserved_dialects: [postgres, duckdb, snowflake]  # unioned lists, data files; ansi is opt-in
    on_collision: error          # error | suffix (_2, _3 …)
    nested: true                 # also conform struct member names
  stream:
    name: conform                # conform | preserve
    prefix: ""                   # added after conforming
    split: null                  # optional: "-" → emit only last part (tap-catalog-schema-table)
  values:
    trim: true                   # strings
    null_tokens: ["", "NULL", "null", "N/A", "n/a", "#N/A", "NaN", "-"]
    null_tokens_case_sensitive: false
    empty_string_for_string: keep   # keep | null : what "" becomes in a string column
  timestamp:
    assume_tz: UTC               # tz for naive inputs to timestamptz
    output_precision: us
    formats: [iso]               # tried in order; see 6.3
  boolean:
    true_values: [true, t, yes, y, "1", on]
    false_values: [false, f, no, n, "0", off]
  on_error: raise                # raise | null | keep | reject
  add_record_metadata: false     # add the seven _sdc_* columns (RECORD and BATCH)
  undeclared: conform            # conform | drop | error
  nested: json                   # json | flatten | keep   (for undeclared object/array)
  flatten: {separator: "__", max_depth: 1, max_key_length: 255}   # SDK flattening semantics
                                 # (naming.collapse then turns "__" into "_"; set collapse: false to keep it)
  faker: {seed: null, locale: null}   # for `fake` (needs the [faker] extra)
  engine: arrow                  # arrow | polars | row : the BATCH engine (§10.2)
  max_reject_rate: null          # fail the run above this fraction of rejected rows (0-1)
  max_null_rate: null            # fail the run above this fraction of rows nulled by on_error: null

streams:
  <glob>:
    alias: <string>              # final stream name (bypasses stream.name/prefix if given); ${vars} or {expr: ...}
    source: <tap stream>         # makes this key a NEW output stream projected from <tap stream>;
                                 # the tap stream is still emitted unless it is itself dropped
                                 # (SDK __source__: split one stream into several, or copy it)
    prefix: <string>
    key_properties: [..]         # source or conformed names; overrides tap
    filter: <expr>               # falsy → drop row; sees CONFORMED column names
    columns: {<source name or new name>: ColumnSpec}
    order: source | declared     # output column order (default source: the tap's)
    drop: true                   # drop the whole stream
    # plus any Defaults key, overriding for this stream
```

**Output stream names** (`map_conform/naming/streams.py`):

- **`alias`**, if set, is the final name. It is checked, never silently conformed. Under
  `stream.name: conform`, an alias that would conform differently is an error.
- **The base name** is otherwise the `streams` key for a `source` stream, else the tap stream
  name. With `stream.split`, only the part after the last separator is used.
- **The base is conformed** like a column name, or kept with `stream.name: preserve`.
- **The prefix** is the stream's `prefix`, else `stream.prefix`. It is added after
  conforming, and the result is conformed once more, so an illegal prefix is fixed and a
  long name still fits `max_length`. Example: `sheets-Orders 2024` with `prefix: raw_`
  becomes `raw_sheets_orders_2024`.

### 3.3 ColumnSpec

| Key | Type | Meaning |
| -- | -- | -- |
| `name` | string | Output name. It is still checked: an illegal name is an error, never silently conformed. |
| `type` | CType string | The declared output type (§4). Taken from the tap SCHEMA if absent. |
| `nullable` | bool | Default true. If false, a null becomes an error under `on_error`. |
| `source` | string \| list | Source column(s) if different from the key. A list means coalesce in order. |
| `expr` | string | Derived value (§7). Without `source`, it creates a new column. |
| `default` | literal | Used when the value is missing or null after transforms. |
| `transform` | Chain | Steps run before/around the cast (§3.4). |
| `parse` | object | Shorthand for the cast's kwargs, e.g. `{formats: [...], tz: ...}`. |
| `true_values` / `false_values` / `null_tokens` / `trim` / `on_error` |  | Column-level overrides of the defaults. |
| `max_length` | int | For strings: the longest value allowed. |
| `on_overflow` | `error` \| `truncate` | What a longer value does. |
| `enum` | list | Allowed values, checked after the cast. |
| `drop` | bool | Remove the column. Dropping a key property is an error. |
| `doc` | string | Copied to the SCHEMA `description` and to the Zamboni export. |
| `sql_type` | string | Overrides the `x-sql-datatype` hint that is emitted (rarely needed). |
| `when` | expr | Apply the whole chain only to rows where this is truthy; other rows keep the cast value. Sees conformed names. (pipelinewise `when`: `equals` → `col == x`, `regex_match` → `matches(re, col)`; a falsy literal such as `0` is compared correctly.) |
| `shape` | JSON Schema \| path | The column's object or array value, declared (inline, or a `.json` file relative to the spec file). It alone decides the column's type, or its flattened columns, so the output SCHEMA does not follow tap schema drift. Members it does not declare are dropped, counted (`members_dropped`) and logged once per stream; a member's `default` (`null`, `{}`, `[]`) is used when it is missing, null or empty (WBS 8.10, decided 2026-11-22). |
| `flatten` | bool | Flatten this column into `parent__child` columns: from its `shape` when it has one, otherwise from the tap's schema, in which case the column takes only `source` and its leaves (`billing__zip`) may be declared as columns. `false` keeps it whole under `nested: flatten`. Unset: follows `nested: flatten`. |
| `engine` | `arrow` \| `polars` \| `row` | Overrides `defaults.engine` for this column in BATCH. |
| `infer_type` | `sdk` | Without `type`: infer it from `expr` as the SDK mapper does. Set by the stream_maps translation. |
| `fields` | `{path: ColumnSpec-lite}` | For `struct` and `json` columns: transforms on nested members by dotted path (`address.zip`, `items[*].sku`), e.g. masking a nested field. Only `transform`, `when` and `drop` are allowed. (pipelinewise `field_paths`.) |

### 3.4 Chains, steps and macros

A **chain** is one step or a list of steps. A **step** is one of:

| Form | Example |
| -- | -- |
| bare name | `trim` |
| name with kwargs | `{strip_chars: "$, "}` / `{cast: decimal, rounding: half_even}` |
| macro reference | `money` or `{money: {currency: "€"}}` |
| expression | `{expr: "value.replace('O', '0')"}` |
| conditional | `{case: [{when: <expr>, then: <chain>}, …, {else: <chain>}]}` |
| UDF | `{fiscal_week: {start_month: 7}}` |

In mapping form, the **first key other than `when` names the step**. Its value is the
step's argument, and the remaining keys are keyword arguments. For example,
`{cast: decimal, rounding: half_even}` is `cast` with argument `decimal` and the keyword
`rounding`. YAML and JSON keep key order, so this is unambiguous.

Any step in mapping form may also carry `when: <expr>`, so the step applies only to rows where
it is truthy: `{hash: {}, when: "country == 'DE'"}`.

The **implicit cast.** If a chain has no `cast` step, one is appended, configured from the
column's `type` and `parse`. So `{type: "decimal(18,2)"}` alone already gives exact decimal
parsing with the default grammar.

**Pre vs post.** Steps before the cast see the *source* value, often a string. Steps after the
cast see the typed value. The type-checker rejects a step whose input type cannot occur at its
position (e.g. `round` before the cast on a string column).

**Macros** are chains with named parameters:

```yaml
macros:
  money:
    params: {currency: "$"}
    steps: [{strip_chars: "${currency}, "}, {cast: decimal, parens_negative: true}]
  sheet_date:
    steps: [{cast: timestamptz, formats: ["%m/%d/%Y %I:%M %p", "%m/%d/%Y", excel_serial, iso]}]
```

As built (`map_conform/plan/chain.py`, `map_conform/plan/ops.py`):

- **Stages.** An `expr` step's result is untyped (raw). A chain that ends raw gets the
  implicit cast even after an explicit one, so `[cast, {expr: "value * 2"}]` is cast
  again to the column's type.
- **`when` on a step** runs the step only where the condition is truthy. After the cast the
  step must keep the value's type, since other rows skip it. Before the cast every row is
  raw afterwards, and the implicit cast follows. A macro reference may carry `when` too.
- **`case`** compiles every branch from the same stage. Branches that end in different
  types each get the implicit cast, so every row leaves the case as the column's type. A
  row that matches no branch, with no `else`, keeps its value.
- **A column's `expr`** is the chain's first step. With no source it creates a column,
  which needs a declared `type`. The column's own name is not in scope: use `value`.
- **A column's `when`** applies the whole chain (with `fields`) where it is truthy. Other
  rows get only the implicit cast.
- **`fields`** run after the cast, on struct or json columns. Paths are member names joined
  by `.`, with `[*]` for list items. A struct member's chain starts and ends at its
  declared type; `drop` works on json members. Containers on the path are copied, so the
  source record is never changed. A missing member is left alone.
- **Steps as functions.** Builtins (except names the library already has, such as `lower`
  and `round`), `cast(value, "decimal(10,2)", **options)` and macros are callable in
  expressions. Their kwargs are checked when they first run. A bare `{cast: decimal}` in a
  macro called from an expression means the column's type. A macro that reads columns
  cannot be called as a function.
- **Errors** in `when` or `case` conditions name the condition. They follow `on_error` like
  any step failure.
- The design's `money` example had `{parens_negative: true}` as a step; it is a cast option.

## 4. Canonical type system (CType)

| CType | Aliases | JSON Schema emitted (contract) | Arrow | Zamboni `columns` |
| -- | -- | -- | -- | -- |
| `boolean` | bool | `{"type":["boolean","null"]}` | bool | boolean |
| `int16` | smallint | integer, min −32768, max 32767, `x-sql-datatype: smallint` | int16 | int |
| `int32` | int, integer | integer, int32 bounds, `x-sql-datatype: integer` | int32 | int |
| `int64` | bigint, long | integer, int64 bounds, `x-sql-datatype: bigint` | int64 | long |
| `float32` | real, float | number, `x-sql-datatype: real` | float32 | float |
| `float64` | double | number, `x-sql-datatype: double precision` | float64 | double |
| `decimal(p,s)` | numeric(p,s) | `{"type":["string","null"],"format":"x-singer.decimal","precision":p,"scale":s}` | decimal128(p,s) (decimal256 if p > 38) | decimal(p,s) |
| `string` / `string(n)` | text, varchar(n) | string (+ `maxLength`) | string (large_string if needed) | string |
| `date` |  | string, `format: date` | date32 | date |
| `time` |  | string, `format: time` | time64[us] | time |
| `timestamp` | timestamp_ntz | string, `format: date-time`, `x-sql-datatype: timestamp` | timestamp[us] | timestamp |
| `timestamptz` | timestamp_tz | string, `format: date-time`, `x-sql-datatype: timestamptz` | timestamp[us, UTC] | timestamptz |
| `uuid` |  | string, `format: uuid` | `arrow.uuid` extension, which parquet stores as `fixed_len_byte_array(16)` with the UUID logical type (a string option exists in `to_arrow` but is not exposed as a setting in 0.1.0) | uuid |
| `binary` | bytes, blob | string, `contentEncoding: base64` | binary | binary |
| `json` | variant | string, `x-sql-datatype: json` (the value is JSON **text**; decimals inside are exact JSON numbers) | string | string |
| `struct<a: T, …>` |  | object with `properties`, `required` for non-nullable members | struct | struct\<…> |
| `list<T>` | array<T> | array with `items` | list | list\<…> |

**From a tap SCHEMA (undeclared columns).**

- `integer` becomes int64, or narrower when `minimum`/`maximum` fit.
- `number` becomes float64, unless the tap gives `x-singer.decimal` or `precision`/`scale`,
  which give decimal.
- `string` + `format` becomes date / time / timestamptz / uuid.
- base64 becomes binary.
- An object or array with a typed shape becomes struct/list when `nested: keep`; otherwise it
  becomes json, or is flattened (`nested: flatten`).
- A recognised `x-sql-datatype` hint takes precedence.
- `anyOf`/`oneOf`:
  - all branches the same scalar type: that type;
  - only `null` plus one type: that type;
  - otherwise json, with a warning.
- Several non-null types: json, with a warning.
- No type: json.

Defaults pinned by the implementation (`map_conform/types/from_jsonschema.py`):

- `x-singer.decimal` with neither precision nor scale is `decimal(38,9)`. With a precision
  only, it is `decimal(p,0)`.
- `string(n)` and `string` branches in one `anyOf` give `string`.
- An object without `properties`, or an array without `items`, stays json even with
  `nested: keep`.
- Hints may use SQL multi-word names: `double precision`, `timestamp with time zone`,
  `timestamp without time zone`, `character varying(n)`. An unrecognised hint is ignored,
  with a warning.

The contract schema reads back exactly: `from_jsonschema(to_jsonschema(t)) == t` for every
CType, with no warnings.

## 5. Name conformer

The pipeline is pure and deterministic, and each step can be configured:

1. Unicode NFKC normalisation.
1. Transliterate to ASCII with the bundled table (pinned Unicode decompositions plus a curated
   supplement for Latin, Greek and Cyrillic; [ADR-0012](../wiki/decisions/0012-bundled-transliteration-table.md)), or strip.
1. Split camelCase (`aB` → `a_B`) and acronym boundaries (`ABc` → `A_Bc`), so that
   `customerID` → `customer_ID` and `HTTPServer` → `HTTP_Server`.
1. Apply the case.
1. Replace characters outside `[a-z0-9_]` with `_`.
1. Collapse repeated `_` and trim `_` from both ends.
1. Leading digit: prefix `_`.
1. Empty result: `col_<n>`, where n is the source ordinal. Logged.
1. Reserved word: append `_`.
1. Longer than `max_length`: truncate with a hash suffix.
1. Within a stream (and within each struct), check for collisions under case folding: error,
   or `_2`, `_3` suffixes.

Golden examples:

| Source | Output |
| -- | -- |
| `Order Date (UTC)` | `order_date_utc` |
| `customerID` | `customer_id` |
| `HTTPServerURL` | `http_server_url` |
| `% Complete` | `complete` (warning: lossy) |
| `2023 Revenue` | `_2023_revenue` |
| `Ünïcode Näme` | `unicode_name` |
| `select` | `select_` |
| `a.b-c d` | `a_b_c_d` |

Details of steps 2–8 (`map_conform/naming/conform.py`):

- **Camel split** applies only with `case: snake` and `split_camel: true`, on ASCII text. A
  plural acronym stays whole: `customerIDs` → `customer_ids`, `APIs` → `apis`.

- **Transliteration** uses the bundled table. A capital that becomes several letters is
  title-cased (`Θεός` → `Theos`), but in all caps beside another capital (`ΘΕΑ` → `THEA`),
  so the camel split does not cut all-caps words apart. Characters outside the table are
  dropped.

- **Allowed characters** depend on `case`: `[a-z0-9_]` for snake and lower, `[A-Z0-9_]` for
  upper, `[A-Za-z0-9_]` for preserve, and any Unicode word character with `ascii: keep`.

- **Separators versus losses.** Whitespace and `- _ . ( ) [ ] { } / \ : , ; ' "` are
  separators: replacing them is not a loss. Dropping any other character (`%`, `$`, `#`, `€`)
  or transliterating is a lossy change, and is recorded.

- `leading_digit: letter` replaces the first digit as the Singer SDK does (`0`→`a` …
  `9`→`j`). A digit-like character with no digit value, which `ascii: keep` can let
  through, is prefixed instead.

- **Truncation** keeps the head, then `_`, then the first 6 hex digits of the SHA-256 of the
  whole conformed name. A trailing `_` is trimmed from the head first. `max_length` is at
  least 8. The `col_<n>` placeholder, the hash and the letter all follow `case`.

- **Fixed point.** Steps 6–10 repeat until the name stops changing, because truncation can
  produce something an earlier step would change again (e.g. a prefixed `_0…` cut back to
  `_` plus the hash). This is what makes conforming idempotent. Property tests check it for
  arbitrary Unicode input under randomised configurations.

- **Collisions** are checked within a stream (and within a struct) under case folding.
  First occurrences claim their names before any suffix is chosen, so a source genuinely
  named `order_id_2` keeps that name. Later duplicates get the next free `_2`, `_3`, …,
  shortened to fit `max_length`.

- **Nested members** (`naming.nested: true`, `map_conform/naming/nested.py`) of declared
  `struct<…>` types and of tap-schema objects are conformed at every depth, through lists,
  with collisions checked per struct. `required` lists follow their properties. A name tree
  renames the keys of record values at run time; keys it does not know are kept.

- **`naming: sdk`** (short for `{preset: sdk}`) replaces steps 1–10 with the Singer SDK's
  SQL `conform_name`, byte for byte. It drops everything but ASCII letters, digits, `_`,
  `-`, `.` and whitespace, lowercases, trims, turns `.`, `-` and spaces into `_`, and turns
  a leading digit into a letter. There is no camel split, collapse, reserved-word handling
  or truncation; only `on_collision` still applies. A name with nothing left, where the SDK
  crashes, is an error. Tests compare it with the SDK's own function on the golden names and
  on generated names. A stream's naming options merge into the preset:
  `{preset: sdk, on_collision: suffix}`.

- **`nested: flatten`** (`map_conform/naming/flatten.py`) is the SDK's flattening,
  re-implemented and tested against the SDK's functions:

  - Undeclared object properties become `parent__child` columns down to `flatten.max_depth`,
    with the SDK's key shortening at `flatten.max_key_length`.
  - Objects and arrays below the limit become JSON text (compact, exact decimals).
  - Properties the spec names, as a column key or a source, are not flattened.
  - Records are flattened the same way before columns read their sources; expressions'
    `record` stays the unflattened source.
  - The flattened keys are then conformed like any name. The default naming collapses `__`
    to `_`; use `naming: sdk` or `collapse: false` to keep it.
  - Two paths giving the same key is an error at `streams.<s>.nested`.

- **Declared shapes** (`map_conform/naming/shape.py`, WBS 8.10). A flattened column with a
  `shape` is replaced at plan time by its leaf columns, typed from the shape: arrays stay
  `list<…>`, objects without properties are `json`, objects past `max_depth` are structs.
  The tap's nested schema is never read for it. A leaf may have its own column spec (a
  transform, a default); its type still comes from the shape unless declared. At run time
  the value is conformed to the shape (undeclared members dropped, defaults applied, empty
  containers normalised to the default) before it is flattened. An unflattened column with
  a `shape` is typed by it, and the same conforming runs as its first step.

Every lossy rename (dropped characters, transliteration) is logged at INFO when the SCHEMA
compiles. The mapping from source to conformed name is shown by `spec explain`.

## 6. Builtin transforms

Each builtin is a `Transform`:

- a name;
- a kwargs dataclass, validated at plan compile time;
- input/output CType constraints;
- `scalar(value, ctx)`.

`ctx` carries the column, the stream, the row index and the defaults. Vector kernels live
apart from the builtins, in `transforms/vector.py` (Arrow) and `transforms/polars_vector.py`
(polars); `map-conform functions` lists which steps and casts have one. In the tables below,
**Vec** names the engines with a kernel for the step (`arrow` kernels are used under
`engine: polars` too), and "row" means it always runs row by row (§10.2).

**Chain compilation** (`map_conform/plan/chain.py`, registry in
`map_conform/transforms/registry.py`):

- **Stages.** The value's type is tracked through the chain as a *stage*: raw before the
  cast, then a CType. Each step lists the stages it accepts, so a step that cannot take the
  current stage is an error at its path.
- **Arguments.** A scalar step argument fills the builtin's positional kwarg
  (`{strip_chars: "$, "}` → `chars`). A mapping argument is keyword arguments
  (`{hash: {algo: md5}}`), except that it fills a mapping-typed positional kwarg when its keys
  are not all kwarg names (`{map_values: {Y: yes}}`). Kwargs are validated by the spec's
  strict parser.
- **Implicit cast.** A chain with no `cast` gets one. Its options layer, lowest to highest:
  stream defaults, column overrides (`trim`, `null_tokens`, …), the column's `parse`, then
  the step's own kwargs. `{cast: decimal}` on a `decimal(18,2)` column means that column's
  type. The chain must end as the column's declared type.
- **Macros** expand in place with their parameters, and cycles are detected. Errors inside
  a macro point at its definition (`macros.money.steps[0]`).
- **Run time.** Nulls skip steps that are not null-safe. A step that fails raises with its
  rule; the executor adds the stream, column, row and value, and applies `on_error`
  (`map_conform/errors.py`).

### 6.1 Text (pre-cast)

| Builtin | Kwargs | Vec |
| -- | -- | -- |
| `trim` | `chars=None` | arrow (ASCII `chars`) |
| `null_tokens` | `tokens`, `case_sensitive` | arrow (ASCII tokens) |
| `strip_chars` | `chars` | arrow (ASCII `chars`) |
| `regex_replace` | `pattern`, `repl`, `flags` | polars (patterns polars compiles; otherwise row) |
| `regex_extract` | `pattern`, `group=1`, `flags` | polars (as above) |
| `lower` / `upper` |  | arrow (ASCII text) |
| `title` |  | row |
| `normalize_unicode` | `form=NFKC` | row |
| `normalize_whitespace` | collapse internal runs | row |
| `remove_control_chars` |  | row |
| `left` / `right` | `n` | arrow |
| `pad` / `substring` |  | row |
| `map_values` | `{from: to}`, `default` | row |
| `split` | `sep` → list<string> | row |

### 6.2 Numeric

| Builtin | Kwargs / grammar | Vec |
| -- | -- | -- |
| `cast: int*` / `cast: float*` / `cast: decimal` | The default grammar accepts: surrounding whitespace; a sign; one currency symbol or ISO-4217 code before or after; thousands separators in valid groups (`thousands=","`, `decimal_point="."`, locale presets `us`, `eu`, `ch`); an exponent; `(x)` as negative when `parens_negative`; a trailing `-` when `trailing_minus`; `%` when `percent: divide`. | arrow, for plain numbers under the default grammar (a regex check, then a pyarrow cast); other rows, and every row under another `locale`, `thousands` or `decimal_point`, go row-wise |
| `rounding` (on cast) | `half_up` (default; halves round away from zero, `-12.5` → `-13`), `half_even`, `down`, `error`. Also controls int-from-fraction: `error` default. `"12.0"` → 12 is always allowed. | arrow for `half_up` on decimals; other modes row |
| `round` | `ndigits` | row |
| `clamp` | `min`, `max`, `on_out_of_range` | row |
| `nan` | `null` \| `error`. NaN/Inf from float sources become null by default for decimal and int columns. | row (non-finite values are handed on) |
| `scale` | `factor` (e.g. cents → units) | row |

Details pinned by the implementation (`map_conform/transforms/numeric.py`):

- **Removal order.** After cleanup, the parser removes: parentheses (`parens_negative`), a
  trailing `%` (`percent: divide | strip`, otherwise an error), a trailing minus
  (`trailing_minus`), then one currency marker. The marker is a symbol (`$€£¥₹…`) or an
  ISO-4217 code, before or after the number, and may have a sign before it (`-$12`). A
  second marker is an error.
- **Exact arithmetic.** Decimal arithmetic is exact throughout. A float from a JSON tap
  converts through its shortest repr, so `0.1` stays `0.1`.
- **Rounding** defaults to `half_up` for decimals and to `error` for integers. `error` on a
  decimal fails when digits would be lost. A decimal with more digits than its precision
  fails.
- **NaN.** NaN and Inf follow the cast option `nan` (`null` by default). The `nan` row in the
  table above is this cast option, not a separate step.

### 6.3 Temporal

| Builtin | Kwargs | Vec |
| -- | -- | -- |
| `cast: timestamptz` / `timestamp` / `date` / `time` | `formats`: tried in order, each one of: a `strftime` pattern; `iso` (fromisoformat with a lenient `Z`/`z`/space separator); `excel_serial` (1900 system; serials below 60 count from 1899-12-31 and serial 60, Lotus's nonexistent 1900-02-29, is an error; `excel_serial_1904`); `epoch_s` / `epoch_ms` / `epoch_us` / `epoch_ns`; `epoch_auto` (by magnitude, opt-in only); `rfc2822`. Also `tz` (source zone for naive input), `ambiguous: error \| earliest \| latest` and `nonexistent: error \| shift`, `dayfirst` (only for `auto`), `min_year` / `max_year` sanity bounds. | arrow when the first format is `iso` and `tz` is UTC; polars also for a first format that is a simple strptime pattern (`%Y %m %d %H %M %S` and literals); serials, epochs and other zones row |
| `to_utc` | timestamptz is always UTC on output; this is explicit for clarity | row |
| `assume_tz` | `tz` | row |
| `to_local` | `tz` (for `timestamp` naive local wall clock) | row |
| `truncate` | `unit` | row |
| `date_from_timestamp` | `tz` | row |

**Ambiguity rule.** A pattern list that could parse the same string to two different
instants, such as `%m/%d` and `%d/%m` both listed, is allowed. The first match wins. A
`spec explain` warning for it is planned.

Details pinned by the implementation (`map_conform/transforms/temporal.py`):

- **ISO parsing** uses its own parser, not `fromisoformat`, so it behaves the same on every
  supported Python. It accepts `Z`/`z`, a `T`, `t` or space separator, `.` or `,` before any
  number of fraction digits (kept to microseconds), offsets with or without `:`, and
  date-only or time-only values.
- **Excel serials** use exact decimal day fractions. Serials below 60 count from
  1899-12-31; serial 60 is an error, and 0 or less is before the epoch.
- **Epochs.** `epoch_auto` picks the unit by magnitude: below 1e11 seconds, then
  milliseconds, microseconds and nanoseconds. Sub-microsecond digits are truncated.
- **Zones and DST.** Naive input is placed in `tz` (default `timestamp.assume_tz`), and
  `fold` detects DST ambiguity and gaps. `nonexistent: shift` gives the instant after the
  gap. Input with its own offset is never re-zoned.
- **Targets.** A `timestamp` or `date` from aware input is the wall time in `tz`. A time of
  day cannot become a timestamp.
- **Checked at compile time:** format tokens and zones.
- **Not built:** `auto` and `dayfirst`, which need a guessing parser.
- **Builtins:** `to_utc`, `assume_tz` (timestamp → timestamptz), `to_local` (timestamptz →
  timestamp), `truncate` and `date_from_timestamp`.

### 6.4 Boolean, JSON, binary, privacy

| Builtin | Kwargs | Vec |
| -- | -- | -- |
| `cast: boolean` | `true_values`, `false_values`, `case_sensitive=false`; numbers: only 0 and 1 are allowed (otherwise an error) | arrow (ASCII tokens) |
| `cast: json` | `parse_strings` (decode text that is already JSON instead of double-encoding), `sort_keys`; non-ASCII kept as is, decimals kept exact | row |
| `cast: binary` | `encoding: base64 \| hex \| utf8`, strict | row |
| `cast: uuid` | `version=None`; accepts braces, no dashes, uppercase; normalises to canonical lowercase | row |
| `hash` | `algo=sha256 \| md5 \| sha1 \| sha512`, `salt=${env:...}`, `skip_first=n` (any n, not a single digit) | row |
| `mask` | `keep_first`, `keep_last`, `char="*"` | row |
| `set_null` | Also makes the column nullable in SCHEMA | arrow |
| `redact_date` | `to: year \| month`. Keeps the column's type (date stays date, timestamptz stays timestamptz) | row |
| `mask_number` | `value=0` | row |
| `mask_hidden` | `value="hidden"`. Only on string columns; otherwise declare `type: string` | row |
| `fake` | `provider` (e.g. `name`, `email`), `args`, `unique=false`; seeded by `defaults.faker`. Needs the `[faker]` extra | row |
| `tokenize` | `key=${env:...}`: deterministic HMAC-SHA256, the same input giving the same token across runs | row |

**pipelinewise-transform-field parity** (each one is a builtin, minus pipelinewise's bugs):

| pipelinewise type | map-conform step |
| -- | -- |
| `SET-NULL` | `set_null` |
| `HASH` | `hash` |
| `HASH-SKIP-FIRST-n` | `{hash: {skip_first: n}}` |
| `MASK-DATE` | `{redact_date: {to: year}}` |
| `MASK-NUMBER` | `mask_number` |
| `MASK-HIDDEN` | `mask_hidden` |
| `MASK-STRING-SKIP-ENDS-n` | `{mask: {keep_first: n, keep_last: n}}` |

The plan compiler checks each masking step against the declared type, and the emitted SCHEMA
always matches the values. A masking failure follows `on_error`; it is never swallowed.

Details pinned by the implementation (`map_conform/transforms/casts.py`, `privacy.py`):

- **Value cleanup.** Every cast from a raw value first trims and applies the null tokens
  (column overrides win). For a string column, `""` follows `empty_string_for_string`, not
  the null tokens.
- **String casts.** A string cast turns scalars into their text and refuses objects and
  arrays (declare json). It enforces `string(n)` or `max_length`; `on_overflow: truncate`
  cuts instead of failing.
- **JSON casts.** A JSON cast decodes text that is already JSON (`parse_strings` is true by
  default) and keeps decimals exact.
- **`hash`** reads a typed value in a canonical text form: ISO dates and plain decimals.
- **`mask`** masks a value too short to show both kept ends entirely, rather than revealing
  it.
- **`mask_number`** gives its value (0) in the column's own type: `0`, `0.0`, `"0.00"`
  for decimal(10,2), `"0"` for a string. pipelinewise writes the int 0 whatever the
  column.
- **`mask_hidden`** is allowed only in string columns; elsewhere it is a compile error.
  pipelinewise writes `"hidden"` into numeric columns, which targets then reject. Steps can
  declare the column types they work in (`Transform.column_kinds`).
- **`redact_date`** also clears the time of day, which pipelinewise's `MASK-DATE` keeps.
- **`tokenize`** is `HMAC-SHA256(key, canonical text)` as hex, and `key` is required.
- **`fake`** (`map_conform/transforms/fake.py`, the `faker` extra) is a step
  (`{fake: email}`, with `args` and `unique`) and an object in expressions (`fake.email()`,
  `fake.seed_instance(value) or fake.email()`).
  - Each stream has one generator, created on first use. With `defaults.faker.seed`,
    `Faker.seed` is called first, as the SDK does, so seeded values match the SDK
    mapper's snapshots exactly.
  - The provider is checked at compile time.
  - In expressions, `fake.seed`, `add_provider`, `random`, `factories` and private names
    are refused.
  - Without the extra, the step and the object say what to install.
- **Wire forms.** Values are encoded for RECORD messages by `map_conform/types/wire.py`.

## 7. Expression language

**Syntax.** A safe Python-expression subset. It is a superset of what the SDK's simpleeval
dialect accepts, so existing stream-map expressions run unchanged.

| Allowed | Not allowed |
| -- | -- |
| Literals, arithmetic, comparisons, boolean ops | Assignment, lambdas, imports |
| `x if c else y`, comprehensions | Dunder or underscore attribute access |
| Subscripts and slices | `exec`, `eval`, `open`, `getattr` |
| Calls to whitelisted functions | — |
| Methods on str, int, float, Decimal, date, datetime, list, dict | — |

**Names in scope.**

| Name | Meaning |
| -- | -- |
| `value` (alias `self`) | The current value, in a column chain |
| Every column by **conformed** name | Values of the record |
| `record` / `_` | The source record |
| `source(name)` | Access by the raw source name |
| `config` | `spec_vars` |
| `stream`, `source_stream` | Stream names |
| `row_number` | Ordinal of the row |
| `NULL` | The null sentinel |
| `fake` | A Faker generator (the `[faker]` extra) |

**Functions.**

| Group | Functions |
| -- | -- |
| predicates | `is_null`, `is_string`, `is_number`, `is_int`, `is_decimal`, `is_bool`, `is_datetime`, `is_date`, `is_list`, `is_dict`, `is_blank`, `matches(re, s)` |
| coercion | `to_int`, `to_float`, `to_decimal(v, p, s)`, `to_bool`, `to_str`, `to_json`, `from_json` |
| temporal | `parse_datetime(v, *formats, tz=)`, `ensure_utc(v, assume=)`, `to_tz`, `now_utc`, `date_trunc`, `excel_date(n)`, `from_epoch(n, unit)` |
| text | `re_sub`, `re_match`, `re_extract`, `lower`, `upper`, `strip`, `split`, `join`, `pad_left` |
| numeric | `round`, `floor`, `ceil`, `clamp` |
| misc | `coalesce`, `nullif`, `md5`, `sha256`, `uuid4`, `uuid5`, `rand`, `randint` |
| python | `abs`, `all`, `any`, `bool`, `dict`, `enumerate`, `float`, `int`, `len`, `list`, `max`, `min`, `range` (bounded), `set`, `sorted`, `str`, `sum`, `tuple`, `zip` |
| modules | `datetime`, `decimal`, `json`, `math`, `re` (wrapped and read-only) |
| UDFs | every registered UDF |
| builtins | every builtin transform, also callable as a function: `money(value)`, `cast(value, "decimal(18,2)")` |

**Conditionals.** A conditional is either the `case:` step form (§3.4) or a ternary inside an
`expr`. `case` is preferred: each branch can contain builtins, and in BATCH a `case` whose
conditions lower to Arrow masks (§10.2: null and blank tests, comparisons and membership
against literals, `matches`, and `not`/`and`/`or` of those) and whose branches all have
kernels is vectorised, with the results merged by `pyarrow.compute.case_when`. Anything
else runs row-wise.

```yaml
transform:
  case:
    - when: is_null(value) or is_blank(value)
      then: set_null
    - when: is_datetime(value)
      then: {to_utc: {}}
    - when: matches(r"^\d{5}(\.\d+)?$", value)     # spreadsheet serial
      then: {cast: timestamptz, formats: [excel_serial]}
    - else: {cast: timestamptz, formats: [iso, "%m/%d/%Y %H:%M"], tz: America/Chicago}
```

**Implementation.**

- Parse with `ast.parse(mode="eval")`, then a whitelist visitor compiles the tree to Python
  closures once per column.
- This is not simpleeval at runtime: it is faster, has the same safety envelope, and its
  error messages name the column.
- `expr` steps always run row by row; only `case`/`when` conditions lower to Arrow (§10.2).
  A column that any expression reads also runs row by row in BATCH.
- Runtime exceptions become a `ConformError` and follow `on_error`. They never crash the run
  without context.
- **Output typing.** The column's declared `type` is authoritative. After the expr, the
  implicit cast coerces the result to it. Nothing is inferred from expression prefixes.

As built (`map_conform/expr/`):

- **Name lookup**, fixed at compile time, in this order: comprehension variables; `value` /
  `self` (column chains only); `record` / `_`, `row_number`, `NULL`; the constants `config`,
  `stream`, `source_stream` (and `__stream_name__`, `__original_stream_name__`); columns by
  conformed name; the library. An unknown name is a compile error at the spec path, with a
  hint to use `record['...']` for a source property.
- **Columns** evaluate to their *conformed* (typed) values, and the names an expression
  reads are its dependencies. The column being computed cannot read itself by name: use
  `value`, or `record['...']` for its source.
- **In call position** functions are looked up first (after comprehension variables), so
  a column named `max` does not hide `max()`, and `fake(value, 'name')` is the step while
  `fake.name()` uses the `fake` object. Only names and attributes can be called.
  `source(name)` reads the source record by raw name.
- **The sandbox** (`sandbox.py`) allows attributes only on str, bytes, numbers, Decimal,
  the temporal types, UUID, list, tuple, dict, set, read-only mappings and regex
  objects (and on those classes). Names starting with `_`, `format`, `format_map` and
  `mro` are refused, as are methods that mutate a list, dict or set. Modules expose a
  fixed list of names (no `decimal.setcontext`, no `math.factorial`).
- **Size limits:** repetition, padding and format widths up to 1,000,000; integer
  exponents and shifts up to 10,000; at most 100,000 steps per comprehension or `range`.
- **Generator expressions** are evaluated eagerly into lists, so no generator (and its
  frame) is ever reachable. The read-only `record` view leaves as a plain dict.
- **The library** (`functions.py`) adds Python's `len`, `sum`, `any`, `all`, `sorted`,
  `list`, `dict`, `tuple`, `set`, `enumerate`, `zip` and a bounded `range`, and the
  `json` module that the SDK exposes. Except the predicates, `coalesce`, `nullif` and the
  Python builtins, a function given a null returns null. `round` rounds half away from
  zero, like the `round` step. `map-conform functions` lists every step and function.
- **SDK expressions** read record properties as bare names. `expr/sdk.py` rewrites such
  free names to `record['...']` once, at translation. A differential test evaluates every
  expression from the SDK's own mapper tests with the SDK's simpleeval evaluator and with
  map-conform, and the results are equal.

## 8. UDFs (Python functions)

```python
from map_conform import udf


@udf(name="fiscal_week", returns="int32", vectorized=False)
def fiscal_week(value, *, start_month: int = 7, ctx=None) -> int | None: ...


@udf(
    name="clean_sku", returns="string", vectorized=True
)  # receives a pyarrow.Array (one element, as built)
def clean_sku(arr, *, ctx=None): ...
```

**Registration.**

- **Entry points** (group `map_conform.functions`) in any installed package. Always allowed.
- **Spec `udfs: {name: "module:attr"}`**. Needs `allow_python_udfs: true`, because the module
  is imported from the project.

**Contract.**

- A UDF may be used as a step `{fiscal_week: {start_month: 4}}` or in an expr
  `fiscal_week(order_date, start_month=4)`.
- Kwargs are validated against the signature at compile time.
- `returns` must be compatible with where the UDF is used.

**Security note.** A UDF is arbitrary Python, like a DB UDF. The sandbox protects expressions,
not UDFs.

As built (`map_conform/udfs.py`):

- **`@udf(name=, returns=, vectorized=, null_safe=, doc=)`** marks a function and returns it
  unchanged. A plain function works too, with the defaults: untyped result, not null-safe,
  doc from its docstring.
- **Signature.** The value comes first; options must be keyword-only and become a kwargs
  dataclass, checked by the spec's strict parser at compile time. Unknown or missing
  options are errors at the step's path. `int`, `str`, `float`, `bool` and `Literal`
  hints are type-checked; other hints accept any value. A `ctx` parameter receives the step
  context (stream, column, settings, target type).
- **Types.** `returns` sets the step's output type, so the chain's checks see it. Without
  it the result is untyped and the column's implicit cast follows.
- **Failures.** An exception in a UDF becomes a cell error naming the step, and follows
  `on_error`.
- **Vectorized UDFs** run on one-element arrays, in RECORD and BATCH alike: whole-array
  calls in the columnar executor are not built.
- **Names.** Spec module paths override entry points of the same name. A UDF may not take
  the name of a builtin step or a library function.
- **Loading.** Module paths import with the current directory (the Meltano project root)
  on `sys.path`. Problems are reported at `udfs.<name>`, before any data flows.
- **CLI.** `spec explain --allow-python-udfs` loads module-path UDFs, as the setting does.
  `map-conform functions` lists installed UDFs with `[udf]`.

## 9. Plan compilation

At SCHEMA:

1. Resolve the StreamSpec.
1. Conform the stream name.
1. For each source property and each derived column, build a `ColumnPlan`:
   - output name and CType;
   - source accessor(s);
   - steps with kwargs already bound;
   - flags: `vectorised` and the `reads` dependency set;
   - `on_error`, `nullable`, `default`.
1. Check the plan:
   - collisions;
   - unknown sources;
   - step type-compatibility;
   - a dependency cycle among derived columns, which is an error. Topological order is used.
1. Build the output SCHEMA via `to_jsonschema` and the Arrow schema via `to_arrow`.
1. Cache the plan by stream name. A new SCHEMA for the same stream recompiles, and the emitted
   SCHEMA changes only if the output differs.

As built (`map_conform/plan/compile.py`):

- **Column names** come from `spec.check.output_columns`, the same code `spec explain`
  uses.
- **Types.** An undeclared column takes its type from the tap SCHEMA (§4). A column built
  from several sources needs a declared type.
- **Consumed sources.** A source property that a column reads, alone or in a coalesced
  `source` list, is not also emitted as an undeclared column.
- **Nested members** are conformed. The member rename tree is applied to values *before*
  the chain, because the struct CType carries conformed names. Struct and list casts
  (`map_conform/transforms/nested.py`) cast members by their declared types, with neutral
  options, and drop keys the struct does not declare.
- **Compile-time checks:**
  - `on_error: keep` is allowed only for string and json columns;
  - `set_null` makes a column nullable, and an error if the column says `nullable: false`;
  - `default` and `enum` values are cast through the column's own chain, so a bad value is
    an error at its path.
- **Keys and bookmarks.** Key and bookmark properties, given as source or output names,
  are renamed to output names. `strict` turns `undeclared` into `error`.
- **Dependencies.** The columns a column's expressions read are its dependencies. Columns
  are computed in dependency order (`StreamPlan.order`); the output keeps its own order. A
  cycle is an error naming it (`a -> b -> a`).
- **Expression scope.** Columns are visible by output name. `config` is `spec_vars`, and
  `stream` and `source_stream` are the output and tap stream names.
- **`filter`** is compiled with every column in scope and no `value`.
- The plan cache lives in the mapper (WBS 5.8).
- `spec explain --catalog` prints the compiled plan: each column's type, nullability,
  `on_error`, steps, default, enum and the columns it reads, and the stream's filter.

## 10. Execution

### 10.1 Row executor

- The input is the SDK-decoded record (`Decimal` for numbers); reading and writing use the
  SDK's JSON handling, with exact decimals (`types/jsontext.py` for JSON text). orjson is not
  used.
- Each ColumnPlan is one composed closure.
- Output dict in plan order, then `_sdc_*` (§11).
- `filter` is evaluated on the **conformed** record, after the column plans and before
  `_sdc_*`, so it sees conformed names and cast values.

As built (`map_conform/plan/row.py`, `map_conform/mapper.py`):

- **Order.** Columns are computed in dependency order. Expressions see the typed values of
  the columns computed before them (`Decimal`, `datetime`), and the output keeps plan order.
- **Per column**, in order:
  - take the first non-null source value;
  - decode JSON text and rename nested members;
  - run the chain;
  - apply the default;
  - enforce `nullable: false` (always an error, even under `on_error: null`) and `enum`;
  - encode the result for the wire.
- **Failures.** A failed value follows the column's `on_error`. `reject` removes the row from
  the output and logs it. The reject sink is WBS 7.3.
- **`filter`** runs after every column, on the typed values. A falsy result drops the row,
  which is counted in `rows_filtered`. A filter that fails follows the stream's `on_error`:
  `raise` stops, `reject` rejects the row, `null` drops it (a null filter is falsy) and
  `keep` keeps it.
- **Messages.**
  - SCHEMA compiles a plan for each output stream and emits its conformed SCHEMA, with
    `_sdc_*` declared when `add_record_metadata` is set.
  - RECORD keeps `version` and `time_extracted` unchanged.
  - STATE passes through in order.
  - ACTIVATE_VERSION is emitted once per output stream, under the conformed name.
  - A new SCHEMA for a stream recompiles its plans.
- **BATCH** messages are conformed by the same executors (§10.3); for parquet in and out,
  the columnar executor (§10.2) computes the vectorised columns first.
- **Not built.** A fast path that skips a cast when the value already has the target type,
  and orjson I/O, were designed for throughput and remain open performance work.

### 10.2 Columnar executor

The design was: read any BATCH input (JSONL through `pyarrow.json.read_json`) as Arrow
batches; run vectorised columns as `pyarrow.compute` chains (or lowered polars
expressions); convert only the columns a row-wise column reads to Python; and build the
output table with the declared schema, one output file per input file, in order. One test
corpus runs through both executors, and their outputs must be identical.

As built, it differs in three ways, described below: only parquet in and parquet out runs
columnar (JSONL runs row by row); every row still goes through the row executor for the
columns, expressions and policies without kernels; and polars contributes kernels for
specific steps rather than lowering whole plans.

As built (`map_conform/transforms/vector.py`, `map_conform/plan/vector.py`,
`map_conform/batch/columnar.py`, WBS 8.4–8.5):

- **Vector ops claim rows, never fail.** A vector op returns its result and a *todo* mask:
  the rows where its Arrow kernel is not known to agree with the scalar code. Those rows go
  through the scalar chain, row by row, and are spliced back. A vector op therefore never
  raises; errors, policies and messages always come from the scalar path. If a kernel
  refuses a whole batch, the column runs row by row for it.

- **What is claimed:**

  - Text ops (`trim`, `strip_chars`, `lower`, `upper`, `left`, `right`, `null_tokens`)
    claim printable-ASCII rows.
  - Numeric casts claim plain numbers under the default grammar (no locale or separators
    set), and integer input; currency, separators, parentheses, percent and other locales
    go row-wise. Decimals claim only `half_up` rounding.
  - Boolean casts claim the configured tokens and boolean input.
  - Temporal casts (timestamptz, timestamp, date) whose first format is `iso` and whose zone
    is UTC claim strict ISO text and Arrow timestamps; `min_year`/`max_year` violations go
    row-wise.
  - `set_null` claims everything.

- **Which columns are vectorised:** those whose every step has a vector op, with no
  `enum`, no nested renames, no shape, and which no expression or filter reads
  (expressions see Python values). A `default` is filled in; a null in a
  `nullable: false` column goes row-wise, so the scalar path raises it.

- **The rest of the row** (other columns, expressions, the filter, `_sdc_*`, `on_error`,
  rejects and metrics) runs through the row executor, which skips the vectorised columns of
  rows they computed. So the columnar result, the rejects, the first error raised and the
  metrics are exactly the RECORD path's.

- **Where it runs:** parquet BATCH input with `mode: batch` and parquet output, when every
  output stream has a vectorised column and no flattening or shapes. Other BATCH input runs
  row by row.

- **Which engine ran, and the reference.** The mapper logs, at INFO once per tap stream (and
  again if it changes), whether its BATCH files run columnar, naming the columns with a
  kernel, or row-wise, with the reason (input not parquet, `mode: record`, JSONL output,
  shapes, flattening, no vectorised column); DEBUG repeats it per file. `engine: row`
  (in `defaults`, a stream or a column) runs every row as a RECORD would: the reference to
  compare a vectorised result against when they differ.

- **Options a kernel does not know.** Each vector cast lists the options it implements, or
  that act only on text it hands on anyway (`claims` in `transforms/vector.py`). When any
  other option differs from its default, the kernel hands every value to the row path.
  The number grammar (`locale`, `thousands`, `decimal_point`) is handled this way, and so
  is any cast option added later, until its kernel learns it.

- **Parity suite** (`tests/parity/`): every corpus case, Hypothesis-generated text and
  integers through every vectorised cast and text op under every `on_error`, and a mixed
  plan (expressions, filter, rejects, defaults, a non-nullable column). Tables, rejects,
  errors and metrics must be equal.

- **`case` lowering** (`map_conform/plan/lower.py`, WBS 8.6). A `case`, or a column's
  `when`, is vectorised when every branch is and every condition lowers to an Arrow mask:

  - `is_null(value)`, and `is_blank(value)` on ASCII text;
  - `value` compared (`==`, `!=`, `<` …) with, or tested for membership (`in`, `not in`) in,
    string or number literals of the column's kind;
  - `matches(pattern, value)` on text without line breaks, when the pattern compiles as RE2;
  - `not`, `and` and `or` of those.

  Each condition is a mask, each branch runs on the whole column, and the first branch
  whose mask holds supplies the value, as `case_when` does. Null rows of an ordered
  comparison are left to the scalar path, where Python raises. A condition that reads
  another column, or uses anything else, keeps the case row-wise.

- **The polars engine** (`map_conform/transforms/polars_vector.py`, WBS 8.7, the `polars`
  extra). `defaults.engine: polars`, or a column's `engine: polars`, uses polars vector
  ops where they exist and the Arrow ones elsewhere. Without the extra it is a compile
  error naming it. polars adds what Arrow does not vectorise, under the same claiming rule:

  - `regex_replace` and `regex_extract` claim printable-ASCII rows without line breaks,
    for patterns that compile in polars and cannot match the empty string, with the `i`
    flag at most; Python replacement references (`\1`, `\g<name>`) are translated;
  - temporal casts whose first format is a strptime pattern of `%Y %m %d %H %M %S` and
    literals claim rows that parse and print back to the same text, so Python's padding
    leniency stays on the scalar path.

  Parity tests cover generated text and dates through each.

### 10.3 BATCH message I/O

- Read the manifest URIs with fsspec (`batch_config.storage.params`-compatible), with
  streaming reads.
- Write output named `<root>/<stream>/<run-id>-<n>.parquet`, then emit
  `{"type":"BATCH","stream":<conformed>,"encoding":{"format":"parquet","compression":"zstd"},"manifest":[…]}`.
- `_sdc_batched_at` is the **input** file's last-modified time (fsspec `info()`; for stores
  without one, the time the file was opened). `_sdc_extracted_at` comes from the BATCH message
  `time_extracted` when present, otherwise null, which is SDK-equivalent.
- `version` is passed through.

As built (`map_conform/batch/`, WBS 8.1–8.3 and 8.8):

- **Rows.** Every row of every manifest file is conformed by the stream's row executors,
  exactly like a RECORD: the same plan, `on_error`, reject sink, filter, shapes and metrics.
  Row numbers continue the RECORD count of the tap stream.
- **Input** is opened with fsspec, using `batch_output.storage.params` for input and output
  alike. JSONL (gzip or plain) is read line by line with exact decimals; parquet is read in
  row groups of `row_group_size` rows. Other formats or compressions, and unreadable files,
  stop the run with the URI.
- **Output.** With `mode: batch`, map-conform writes one file per input file and output
  stream, in the input's order, under `<root>/<stream>/<run id>-<n>`. `root` is
  `storage.root`, or the input file's directory. Then it emits one BATCH message per output
  stream, with `encoding`, the `manifest`, and the input's `version` and
  `time_extracted`.
  - Parquet uses the declared Arrow schema (`to_arrow` of each column, plus the `_sdc_*`
    columns with `add_record_metadata`: timestamps as `timestamp[us, UTC]`, integers as
    `int64`), built from the RECORD path's wire values, so both carry the same data.
  - JSONL holds the wire values, compact.
  - Compression defaults to zstd for parquet and gzip for JSONL.
- **`mode: record`** emits RECORD messages instead, for targets that do not read BATCH.
- **`_sdc_batched_at`** is each input file's last-modified time (`fs.modified`), or now when
  the store does not report one. `_sdc_extracted_at` is the BATCH message's
  `time_extracted`.
- **`delete_input`** deletes each input file once every output written from it is closed.
- **Columnar.** Parquet in and parquet out first computes the vectorised columns with the
  columnar executor (§10.2); the row executor does the rest, as above.

## 11. `_sdc_*` metadata (SDK-exact)

| Column | Value |
| -- | -- |
| `_sdc_extracted_at` | `time_extracted` of the input message |
| `_sdc_received_at` | now (UTC ISO) when the message is processed |
| `_sdc_batched_at` | BATCH: the input file's last-modified time. RECORD: the mapper start time, as an ISO timestamp (the run is the batch) |
| `_sdc_deleted_at` | the record's own `_sdc_deleted_at` (conformed as timestamptz), else null |
| `_sdc_sequence` | `round(time.time()*1000)` (SDK-identical; not unique) |
| `_sdc_table_version` | the message `version` |
| `_sdc_sync_started_at` | mapper start, epoch ms |

Values and schema are the SDK's (`map_conform/metadata.py`), and a parity test calls the
SDK's own `Sink._add_sdc_metadata_to_record` and `_add_sdc_metadata_to_schema`:

- the timestamps are Python `isoformat()` strings with `+00:00`;
- the property schemas are `{"type": ["null","string"], "format": "date-time"}` and
  `{"type": ["null","integer"]}`.

The columns are added only with `add_record_metadata: true` (default false; the plugin
setting of the same name, or `defaults.add_record_metadata`, which a stream can override),
to SCHEMA, RECORD and BATCH alike (decided 2026-11-22). The tap's own `_sdc_*` properties are
never ordinary columns: with the flag they feed these columns, without it they are left out,
as SDK targets leave them out.

**Downstream.** An SDK target must set `add_record_metadata: true`, otherwise it strips these
columns. `map-conform doctor` checks for this. With the flag on, the target overwrites the
values with near-identical ones, which is defined SDK behaviour.

## 12. Errors and rejects

`ConformError` carries:

- `stream`, `column`, `source_column`, `row_number`;
- `value` (repr, truncated);
- `rule` (step name + kwargs);
- `message`.

| on_error | Effect |
| -- | -- |
| `raise` (default) | Stop at the first error, with a precise message. |
| `null` | Write null (an error if the column is non-nullable). Counted. |
| `keep` | Keep the source value. Allowed only when the declared type is string or json. |
| `reject` | Drop the row from output. Write a dead-letter row `{stream, row_number, column, rule, error, value, record, rejected_at}` to the reject sink. Counted. |

**Thresholds.** `max_reject_rate` and `max_null_rate` per stream turn a lenient policy back
into a failure when a source goes bad.

As built (`map_conform/errors.py`, `map_conform/rejects.py`):

- **The reject sink** writes `<reject.storage>/<output stream>/<run id>.jsonl` (or
  `.parquet`). Each row has `stream`, `row_number`, `column`, `rule`, `error`, `value` (JSON
  text), `record` (the whole raw record, as JSON text) and `rejected_at`. The file paths are
  logged at the end of the run.
- **Thresholds** are Defaults keys, so they can be set per stream. Each is a fraction (0–1)
  of the stream's rows in: rejected rows, or rows where `on_error: null` replaced a value.
  They are checked **before each STATE is passed on**, so a target never commits a bookmark
  past rows a bad source spoiled, and again at the end of input. Going over a limit fails
  the run, with the stream, the counts and the rate in the message.
- **Not built yet:** "the first N similar errors" for `raise`. The run stops at the first
  error.

## 13. Metrics and logging

Per stream:

- rows in and out;
- filtered, rejected;
- nulls produced by each column and rule;
- lossy renames;
- whether BATCH files ran columnar or row-wise, and why.

Emitted as SDK-style metric log lines, and optionally to `metrics_path`.

As built (`map_conform/metrics.py`):

- **Counters**, per output stream: `rows_in`, `rows_out`, `rows_rejected`, `rows_nulled`,
  `rows_filtered`, `values_kept`, `members_dropped` by (column, member path) for members
  a declared shape does not declare, and `errors` by (column, rule), whatever `on_error` did
  with them.
- **Output.** One `Metrics for '<stream>': {...}` log line per stream at the end of the run,
  and `metrics_path` as `{"streams": {name: counters}}`.
- **Logs, not counters:** lossy renames (once per stream, when its SCHEMA compiles) and the
  BATCH engine each stream's files ran on, with the reason (§10.2).

## 14. Testing strategy (summary — see [wiki/qa/test-strategy.md](../wiki/qa/test-strategy.md))

- **Golden naming tests** (§5) and **property-based tests** (Hypothesis): the conformer is
  idempotent, its output always matches the grammar, and outputs are unique.
- **Cast corpus.** CSV and spreadsheet fixtures: dates in 25+ formats, currencies, locales,
  null tokens. Each case is an `input → expected | error` table.
- **Parity tests**, RECORD vs BATCH, for every corpus case.
- **Contract tests.** The emitted SCHEMA validates every emitted RECORD. The emitted parquet
  schema equals `to_arrow(plan)`.
- **End-to-end** (`tests/e2e/`, opt-in with `-m e2e`, run in CI): the messy CSV fixture
  piped through map-conform into the published target-jsonl. The reference Meltano project
  (`examples/`) runs `meltano run` into target-ducklake in CI and checks the lake.
- **Benchmarks** (`tests/bench/`, `-m bench`): RECORD, row-wise BATCH and columnar BATCH
  throughput, gated in CI against a recorded baseline and a minimum columnar speed-up
  ([benchmarks](../wiki/qa/benchmarks.md)).
- **Stream-map parity.** The SDK's own stream-map test cases run through `stream_maps`
  compatibility mode, and their output must match the SDK mapper's.

## 15. Stream-map compatibility

map-conform is a **superset** of the SDK stream maps used by meltano-map-transformer: nothing
that works there is lost. Every feature has a native spec equivalent, and the SDK settings are
also accepted unchanged ([ADR-0010](../wiki/decisions/0010-stream-map-superset.md)).

| SDK stream-map feature | Native spec |
| -- | -- |
| `stream_maps.<stream>` (fnmatch globs) | `streams.<glob>` |
| `__alias__` (expr over `__stream_name__`) | `alias` (string, `${vars}`, or `{expr: ...}` with `stream`) |
| `__filter__` | `filter` |
| `__source__` (copy or split a stream) | `source` on a new output-stream key |
| `__key_properties__` | `key_properties` |
| `<stream>: null` / `"__NULL__"` | `drop: true` |
| `__else__: null` (stream level) | top-level `else: drop` |
| `<prop>: null` / `"__NULL__"` | `{drop: true}` |
| `__else__: null` (property level) | `undeclared: drop` (key properties kept) |
| `<prop>: "<expr>"` | `{expr: "<expr>"}`, with `type` declared or SDK-inferred (below) |
| `self`, `_`, `record`, `config`, `__stream_name__`, `__original_stream_name__` | `value`/`self`, `_`/`record`, `config`, `stream`, `source_stream` (old names kept as aliases) |
| `md5`, `sha256`, `uuid4`, `check_uuid`, `int`, `float`, `str`, `bool`, `datetime`, `json` | the same names, plus the library in §7 |
| `fake` + `faker_config` | `fake` + `defaults.faker`, and the `fake` builtin step |
| `flattening_enabled`, `_max_depth`, `_separator`, `_max_key_length` | `nested: flatten`, `flatten.{max_depth, separator, max_key_length}`, with the same key-shortening algorithm |

**Compatibility mode.** When `stream_maps` is set:

1. It is translated into an in-memory spec, merged *under* the native spec. The native spec
   wins column by column.
1. A translated expression column with no declared `type` gets the **SDK's prefix-based
   inference** (`int(` → integer, `float(` → number, …, otherwise the existing type or
   string), so output types match the SDK mapper. A note (INFO) per column suggests
   declaring a type.
1. Unlike the SDK, the implicit cast still applies, so values always match the SCHEMA, and a
   runtime error follows `on_error` instead of crashing without context.
1. Defects of meltano-map-transformer are *not* reproduced: `time_extracted` is preserved and
   `bookmark_properties` are passed through (renamed).

`map-conform spec import --stream-maps` writes the translation out as a native spec, with the
inferred types written explicitly, so a project can migrate in one step.

As built (`map_conform/spec/stream_maps.py`, `map_conform/spec/importer.py`, `map_conform/expr/sdk.py`):

- **Translation** happens once, at start-up, into a raw spec merged under the native one
  (after `${...}` substitution, so SDK expressions are never substituted). The mapper
  advertises the `stream-maps` and `schema-flattening` capabilities. Problems are reported
  at `stream_maps.<stream>.<key>` before any data flows. What the SDK refuses is refused:
  `__else__` other than null, a string stream definition, a non-string property.
- **Expressions** are rewritten so free record names read `record['...']`; `self`, `_`,
  `record`, `config`, `__stream_name__`, `__original_stream_name__`, `fake` and the SDK
  functions (simpleeval's `int`, `float`, `str`, `rand`, `randint`, `list`, `tuple`,
  `dict`, `set`, and the SDK's `md5`, `sha256`, `bool`, `datetime`, `json`) keep their
  meaning. An `__alias__` that parses and uses no name but `__stream_name__` is an
  expression; otherwise it is the literal name, as in the SDK.
- **Compatibility defaults** apply with `stream_maps` set, unless the spec sets them, so a
  project moving from meltano-map-transformer keeps its output:
  - `naming: sdk`: the names an SDK SQL target creates;
  - `stream.name: preserve`;
  - `nested: keep`;
  - `values: {trim: false, null_tokens: []}`.
- **Types** (WBS 12.2). An expression column gets `infer_type: sdk`: the SDK's prefix rules
  (`int(` → int64, `float(` → float64, `str(`/`json.dumps(`/a quoted literal → string,
  `bool(` → boolean, `.date()` or `datetime.date` → date, `datetime.datetime` →
  timestamptz). Otherwise it takes the type of the existing or passthrough property, or
  string; `record` is the record's struct. A note per column suggests declaring the type.
- **`__else__: null`** keeps the key properties: under `undeclared: drop` the spec's
  `key_properties`, or the tap's, stay. A stream-level `source` may be a glob.
- **Parity** (WBS 12.9, `tests/compat/`). Every case of the SDK's own mapper tests runs
  through the SDK's `PluginMapper` and through map-conform: 38 cases. The SDK's BATCH case
  (`aliased_stream_batch`) is not ported, because the SDK's inline mapper does not map BATCH
  messages, so there is no SDK output to compare with; map-conform's BATCH output is
  compared with its own RECORD output instead (`tests/parity/`). Stream names, key properties, columns, type families and values agree, except for
  these deliberate differences:
  1. canonical UTC timestamps;
  1. exact decimals written as strings (ADR-0007);
  1. untyped values written as JSON text;
  1. richer SCHEMAs;
  1. column names after the SDK target's `conform_name`;
  1. every column in every record, null when the tap left it out.
- **`spec import --stream-maps CONFIG.json [--catalog C] [-o OUT]`** writes the translation,
  compatibility defaults included, as YAML.
  - Types the expression decides are written as `type`.
  - With `--catalog`, so are types taken from tap properties, when every matching stream
    agrees.
  - Otherwise the column keeps `infer_type: sdk` and a note says so.
  - `stream_map_config` should move to `spec_vars`.
  - A round-trip test checks that running the imported spec gives the same output as
    running the stream maps.

## 16. Open questions

| # | Question | Status |
| -- | -- | -- |
| Q1 | uuid in BATCH | **Resolved:** `arrow.uuid` → parquet FLBA(16) with UUID logical type (checked with pyarrow 26 and DuckDB); RECORD stays canonical string |
| Q2 | `_sdc_batched_at` | **Resolved:** BATCH = input file last-modified; RECORD = mapper start |
| Q3 | `filter` names | **Resolved:** conformed names |
| Q4 | Transliteration table: vendor it or depend on a library | **Resolved:** bundle a generated table, no GPL source ([ADR-0012](../wiki/decisions/0012-bundled-transliteration-table.md)) |
| Q5 | Upstream SDK proposal for `_sdc_*` | **Closed:** no. The Singer spec and the SDK own `_sdc_*` behaviour |
