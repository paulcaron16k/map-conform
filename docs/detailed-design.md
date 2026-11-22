# map-conform — Detailed design

Related: [HLD](architecture-hld.md) · [plan](plan-wbs.md) · [contract](../wiki/concepts/clean-landing-contract.md)

## 1. Plugin settings (Meltano / `--config`)

The plugin settings are kept small on purpose. The real configuration is in the spec file,
so Meltano's ~128 KiB-per-environment-variable limit never applies to it.

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
| `batch_output.storage.params` | object | `{}` | fsspec storage options. |
| `batch_output.delete_input` | boolean | false | Delete each input file after its output is written. |
| `batch_output.row_group_size` | integer | 131072 | Rows per parquet row group, which is also the size of each processing chunk. |
| `reject.storage` | string | `./.map-conform/rejects` | Where the dead-letter files go. |
| `reject.format` | `jsonl` \| `parquet` | `jsonl` |  |
| `metrics_path` | string | — | Write per-stream metrics as JSON at the end of the run. |
| `stream_maps` | object | — | **SDK-compatible.** Accepted unchanged and translated into the spec at startup (§15). The native spec wins where both define a column. |
| `stream_map_config` | object | — | **SDK-compatible.** Exposed as `config` in expressions; merged with `spec_vars`. |
| `faker_config` | object | — | **SDK-compatible.** `{seed, locale}`; same as `defaults.faker`. |
| `flattening_enabled` / `flattening_max_depth` / `flattening_separator` / `flattening_max_key_length` |  | — | **SDK-compatible.** Same as `defaults.nested: flatten` plus `defaults.flatten.*`. |

## 2. CLI

```
map-conform --config CONFIG [--input FILE]          # the mapper (SDK CLI)
map-conform spec validate SPEC [--catalog CATALOG]   # strict parse + plan compile against a catalog
map-conform spec explain SPEC --stream S [--catalog C]  # print the resolved plan per column
map-conform spec schema                              # print the spec's JSON Schema
map-conform spec import --catalog C [--zamboni TC]   # draft a spec from a catalog (+ Zamboni columns)
map-conform spec export SPEC --zamboni TC            # write canonical types into Zamboni `columns`
map-conform spec import --stream-maps CONFIG.json    # convert SDK stream_maps (+ flattening) to a native spec
map-conform doctor [--meltano-yml meltano.yml]       # check targets have add_record_metadata, etc.
map-conform functions [--json]                       # list builtins, kwargs, vectorisable?
```

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
    case: snake                  # snake | lower | upper | preserve
    split_camel: true            # customerID → customer_id; HTTPServer → http_server
    ascii: transliterate         # transliterate (Ünïcode→Unicode) | strip | keep
    replace_invalid: "_"         # any char outside [a-z0-9_] after casing
    collapse: true               # "__" → "_" ; trim leading/trailing "_"
    leading_digit: prefix        # prefix "_" | letter (SDK: 0→a) | error
    max_length: 63
    truncate: hash               # hash: keep head + "_" + 6-hex of full name | error
    reserved_words: suffix       # suffix "_" | prefix "_" | error | ignore
    reserved_dialects: [ansi, postgres, duckdb]   # unioned lists, data files
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
  metadata: sdc                  # sdc | none
  undeclared: conform            # conform | drop | error
  nested: json                   # json | flatten | keep   (for undeclared object/array)
  flatten: {separator: "__", max_depth: 1, max_key_length: 255}   # SDK flattening semantics
  faker: {seed: null, locale: null}   # for `fake` (needs the [faker] extra)

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
| `max_length` | int | For strings: `truncate` \| `error` via `on_overflow`. |
| `enum` | list | Allowed values, checked after the cast. |
| `drop` | bool | Remove the column. Dropping a key property is an error. |
| `doc` | string | Copied to the SCHEMA `description` and to the Zamboni export. |
| `sql_type` | string | Overrides the `x-sql-datatype` hint that is emitted (rarely needed). |
| `when` | expr | Apply the whole chain only to rows where this is truthy; other rows keep the cast value. Sees conformed names. (pipelinewise `when`: `equals` → `col == x`, `regex_match` → `matches(re, col)`; a falsy literal such as `0` is compared correctly.) |
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
    steps: [{strip_chars: "${currency}, "}, {parens_negative: true}, {cast: decimal}]
  sheet_date:
    steps: [{cast: timestamptz, formats: ["%m/%d/%Y %I:%M %p", "%m/%d/%Y", excel_serial, iso]}]
```

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
| `uuid` |  | string, `format: uuid` | `arrow.uuid` extension, which parquet stores as `fixed_len_byte_array(16)` with the UUID logical type; `uuid_as: string` is an option | uuid |
| `binary` | bytes, blob | string, `contentEncoding: base64` | binary | binary |
| `json` | variant | string, `x-sql-datatype: json` (the value is JSON **text**) | string | string |
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

Every lossy rename (dropped characters, transliteration) is logged once per stream. The mapping
from source to conformed name is available from `spec explain` and is written to metrics.

## 6. Builtin transforms

Each builtin is a `Transform`:

- a name;
- a kwargs dataclass, validated at plan compile time;
- input/output CType constraints;
- `scalar(value, ctx)`;
- an optional `arrow(array, ctx)`.

`ctx` carries the column, the stream, the row index and the defaults. Vectorisable builtins
are marked ✓.

### 6.1 Text (pre-cast)

| Builtin | Kwargs | Vec |
| -- | -- | -- |
| `trim` | `chars=None` | ✓ |
| `null_tokens` | `tokens`, `case_sensitive` | ✓ |
| `strip_chars` | `chars` | ✓ |
| `regex_replace` | `pattern`, `repl`, `flags` | ✓ (RE2 subset; otherwise row-wise) |
| `regex_extract` | `pattern`, `group=1` | ✓ |
| `lower` / `upper` / `title` |  | ✓ |
| `normalize_unicode` | `form=NFKC` | row |
| `normalize_whitespace` | collapse internal runs | ✓ |
| `remove_control_chars` |  | ✓ |
| `pad` / `left` / `right` / `substring` |  | ✓ |
| `map_values` | `{from: to}`, `default` | ✓ |
| `split` | `sep` → list<string> | ✓ |

### 6.2 Numeric

| Builtin | Kwargs / grammar | Vec |
| -- | -- | -- |
| `cast: int*` / `cast: float*` / `cast: decimal` | The default grammar accepts: surrounding whitespace; a sign; one currency symbol or ISO-4217 code before or after; thousands separators in valid groups (`thousands=","`, `decimal_point="."`, locale presets `us`, `eu`, `ch`); an exponent; `(x)` as negative when `parens_negative`; a trailing `-` when `trailing_minus`; `%` when `percent: divide`. | ✓ (a regex validate + pyarrow cast; failures go row-wise for the error path) |
| `rounding` (on cast) | `half_up` (default; halves round away from zero, `-12.5` → `-13`), `half_even`, `down`, `error`. Also controls int-from-fraction: `error` default. `"12.0"` → 12 is always allowed. | ✓ |
| `round` | `ndigits` | ✓ |
| `clamp` | `min`, `max`, `on_out_of_range` | ✓ |
| `nan` | `null` \| `error`. NaN/Inf from float sources become null by default for decimal and int columns. | ✓ |
| `scale` | `factor` (e.g. cents → units) | ✓ |

### 6.3 Temporal

| Builtin | Kwargs | Vec |
| -- | -- | -- |
| `cast: timestamptz` / `timestamp` / `date` / `time` | `formats`: tried in order, each one of: a `strftime` pattern; `iso` (fromisoformat with a lenient `Z`/`z`/space separator); `excel_serial` (1900 system; serials below 60 count from 1899-12-31 and serial 60, Lotus's nonexistent 1900-02-29, is an error; `excel_serial_1904`); `epoch_s` / `epoch_ms` / `epoch_us` / `epoch_ns`; `epoch_auto` (by magnitude, opt-in only); `rfc2822`. Also `tz` (source zone for naive input), `ambiguous: error \| earliest \| latest` and `nonexistent: error \| shift`, `dayfirst` (only for `auto`), `min_year` / `max_year` sanity bounds. | ✓ for strptime and ISO via `pyarrow.compute.strptime` / `cast`; serial and epoch via arithmetic; otherwise row-wise |
| `to_utc` | timestamptz is always UTC on output; this is explicit for clarity | ✓ |
| `assume_tz` | `tz` | ✓ |
| `to_local` | `tz` (for `timestamp` naive local wall clock) | ✓ |
| `truncate` | `unit` | ✓ |
| `date_from_timestamp` | `tz` | ✓ |

**Ambiguity rule.** A pattern list that could parse the same string to two different
instants, such as `%m/%d` and `%d/%m` both listed, is allowed. The first match wins. `spec explain` warns about it.

### 6.4 Boolean, JSON, binary, privacy

| Builtin | Kwargs | Vec |
| -- | -- | -- |
| `cast: boolean` | `true_values`, `false_values`, `case_sensitive=false`; numbers: only 0 and 1 are allowed (otherwise an error) | ✓ |
| `cast: json` | `parse_strings` (decode text that is already JSON instead of double-encoding), `sort_keys`, `ensure_ascii=false`, decimals kept exact | row |
| `json_get` | `path` (JSONPath subset) | row |
| `cast: binary` | `encoding: base64 \| hex \| utf8`, strict | ✓ |
| `cast: uuid` | `version=None`; accepts braces, no dashes, uppercase; normalises to canonical lowercase | ✓ |
| `hash` | `algo=sha256 \| md5 \| sha1 \| sha512`, `salt=${env:...}`, `skip_first=n` (any n, not a single digit) | ✓ |
| `mask` | `keep_first`, `keep_last`, `char="*"` | ✓ |
| `set_null` | Also makes the column nullable in SCHEMA | ✓ |
| `redact_date` | `to: year \| month`. Keeps the column's type (date stays date, timestamptz stays timestamptz) | ✓ |
| `mask_number` | `value=0` | ✓ |
| `mask_hidden` | `value="hidden"`. Only on string columns; otherwise declare `type: string` | ✓ |
| `fake` | `provider` (e.g. `name`, `email`), `args`, `unique=false`; seeded by `defaults.faker`. Needs the `[faker]` extra | row |
| `tokenize` | `key=${env:...}`: deterministic HMAC-SHA256, the same input giving the same token across runs | ✓ |

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

**Functions.**

| Group | Functions |
| -- | -- |
| predicates | `is_null`, `is_string`, `is_number`, `is_int`, `is_decimal`, `is_bool`, `is_datetime`, `is_date`, `is_list`, `is_dict`, `is_blank`, `matches(re, s)` |
| coercion | `to_int`, `to_float`, `to_decimal(v, p, s)`, `to_bool`, `to_str`, `to_json`, `from_json` |
| temporal | `parse_datetime(v, *formats, tz=)`, `ensure_utc(v, assume=)`, `to_tz`, `now_utc`, `date_trunc`, `excel_date(n)`, `from_epoch(n, unit)` |
| text | `re_sub`, `re_match`, `re_extract`, `lower`, `upper`, `strip`, `split`, `join`, `len`, `pad_left` |
| numeric | `round`, `abs`, `min`, `max`, `floor`, `ceil`, `clamp` |
| misc | `coalesce`, `nullif`, `md5`, `sha256`, `uuid4`, `uuid5`, `fake` (with the `[faker]` extra) |
| modules | `datetime`, `decimal`, `math`, `re` (wrapped and read-only) |
| UDFs | every registered UDF |
| builtins | every builtin transform, also callable as a function: `money(value)`, `cast(value, "decimal(18,2)")` |

**Conditionals.** A conditional is either the `case:` step form (§3.4) or a ternary inside an
`expr`. `case` is preferred, because each branch can contain builtins and so stays
vectorisable: the whens become masks, branches run on their subset, and the results are
merged with `pyarrow.compute.case_when`.

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
- `expr` → Arrow lowering covers arithmetic, comparisons, boolean ops, `coalesce`, string
  methods with Arrow kernels and the predicates. Anything else runs row-wise.
- Runtime exceptions become a `ConformError` and follow `on_error`. They never crash the run
  without context.
- **Output typing.** The column's declared `type` is authoritative. After the expr, the
  implicit cast coerces the result to it. Nothing is inferred from expression prefixes.

## 8. UDFs (Python functions)

```python
from map_conform import udf


@udf(name="fiscal_week", returns="int32", vectorized=False)
def fiscal_week(value, *, start_month: int = 7, ctx=None) -> int | None: ...


@udf(name="clean_sku", returns="string", vectorized=True)  # receives a pyarrow.Array
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

## 10. Execution

### 10.1 Row executor

- The input is the SDK-decoded record (`Decimal` for numbers). I/O uses orjson where it is
  safe; numbers that need exact Decimal go through the SDK decoder path.
- Each ColumnPlan is one composed closure. A fast path skips the cast when the value already
  has the target Python type and passes its checks.
- Output dict in plan order, then `_sdc_*` (§11).
- `filter` is evaluated on the **conformed** record, after the column plans and before
  `_sdc_*`, so it sees conformed names and cast values.

### 10.2 Columnar executor

- Input: a `pyarrow.RecordBatch` with any schema. JSONL is read in line blocks with
  `pyarrow.json.read_json`, with explicit `string` types for declared columns so nothing is
  inferred, or through the row decoder when nested shapes are irregular.
- Vectorised ColumnPlans run as chains of `pyarrow.compute` calls. With the `[polars]` extra,
  a plan may instead be lowered to a polars expression. This is chosen per column with
  `engine: polars` or globally, and is useful for regex-heavy text and flexible datetime
  parsing.
- Row-wise ColumnPlans convert only the columns in their `reads` set with `to_pylist`, run
  the row closure and build `pa.array(values, type=arrow_type)`.
- Errors produce a boolean reject mask, a null replacement or a raise. Rejected rows are
  filtered out of the output batch and written to the reject sink together with the error.
- Output: `pa.RecordBatch.from_arrays(…, schema=declared)`, written with
  `pyarrow.parquet.ParquetWriter`, one output file per input file, in the same order.
- **Parity.** One test corpus is run through both executors, and their outputs must be
  identical when converted to the canonical JSON form.

### 10.3 BATCH message I/O

- Read the manifest URIs with fsspec (`batch_config.storage.params`-compatible), with
  streaming reads.
- Write output named `<root>/<stream>/<run-id>-<n>.parquet`, then emit
  `{"type":"BATCH","stream":<conformed>,"encoding":{"format":"parquet","compression":"zstd"},"manifest":[…]}`.
- `_sdc_batched_at` is the **input** file's last-modified time (fsspec `info()`; for stores
  without one, the time the file was opened). `_sdc_extracted_at` comes from the BATCH message
  `time_extracted` when present, otherwise null, which is SDK-equivalent.
- `version` is passed through.

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
| `raise` (default) | Stop with a precise message and the first N similar errors in the batch. |
| `null` | Write null (an error if the column is non-nullable). Counted. |
| `keep` | Keep the source value. Allowed only when the declared type is string or json. |
| `reject` | Drop the row from output. Write a dead-letter row `{stream, row_number, column, rule, error, record}` to the reject sink. Counted. |

**Thresholds.** `max_reject_rate` and `max_null_rate` per stream turn a lenient policy back
into a failure when a source goes bad.

## 13. Metrics and logging

Per stream:

- rows in and out;
- filtered, rejected;
- nulls produced by each column and rule;
- lossy renames;
- columns run row-wise in BATCH, and why.

Emitted as SDK-style metric log lines, and optionally to `metrics_path`.

## 14. Testing strategy (summary — see [wiki/qa/test-strategy.md](../wiki/qa/test-strategy.md))

- **Golden naming tests** (§5) and **property-based tests** (Hypothesis): the conformer is
  idempotent, its output always matches the grammar, and outputs are unique.
- **Cast corpus.** CSV and spreadsheet fixtures: dates in 25+ formats, currencies, locales,
  null tokens. Each case is an `input → expected | error` table.
- **Parity tests**, RECORD vs BATCH, for every corpus case.
- **Contract tests.** The emitted SCHEMA validates every emitted RECORD. The emitted parquet
  schema equals `to_arrow(plan)`.
- **End-to-end** through `meltano run tap-csv map-conform target-jsonl`, and through
  target-ducklake with its cleanup options off.
- **Benchmarks** (pytest-benchmark) gate regressions in CI.
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
   string), so output types match the SDK mapper. A warning per column suggests declaring a
   type.
1. Unlike the SDK, the implicit cast still applies, so values always match the SCHEMA, and a
   runtime error follows `on_error` instead of crashing without context.
1. Defects of meltano-map-transformer are *not* reproduced: `time_extracted` is preserved and
   `bookmark_properties` are passed through (renamed).

`map-conform spec import --stream-maps` writes the translation out as a native spec, with the
inferred types written explicitly, so a project can migrate in one step.

## 16. Open questions

| # | Question | Status |
| -- | -- | -- |
| Q1 | uuid in BATCH | **Resolved:** `arrow.uuid` → parquet FLBA(16) with UUID logical type (checked with pyarrow 26 and DuckDB); RECORD stays canonical string |
| Q2 | `_sdc_batched_at` | **Resolved:** BATCH = input file last-modified; RECORD = mapper start |
| Q3 | `filter` names | **Resolved:** conformed names |
| Q4 | Transliteration table: vendor it or depend on a library | **Resolved:** bundle a generated table, no GPL source ([ADR-0012](../wiki/decisions/0012-bundled-transliteration-table.md)) |
| Q5 | Upstream SDK proposal for `_sdc_*` | **Closed:** no. The Singer spec and the SDK own `_sdc_*` behaviour |
