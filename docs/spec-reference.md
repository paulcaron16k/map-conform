# map-conform spec reference

Generated from the code by `uv run python -m map_conform.spec.reference`; do not edit.
The [detailed design](detailed-design.md) explains the behaviour behind each key, and
the [cookbook](cookbook.md) shows them at work.

## Plugin settings

Set in `meltano.yml` (or `--config`). Nested keys are written with dots in Meltano.

| Key | Type | Default | Meaning |
| -- | -- | -- | -- |
| `spec_path` | string or null | unset | Path to the conform spec (YAML or JSON). Relative paths resolve against the current directory, which is the project root under Meltano. |
| `spec` | mapping of any or null | unset | An inline conform spec for small cases; deep-merged over spec_path. |
| `spec_vars` | mapping of any | `{}` | Values for ${name} in the spec. Environment variables are ${env:NAME}. |
| `strict` | boolean | `false` | Treat undeclared columns as errors and make warnings errors. |
| `allow_python_udfs` | boolean | `false` | Allow udfs given as module paths. Entry-point UDFs are always allowed. |
| `batch_output.mode` | `batch` \| `record` | `"batch"` | Write new BATCH files, or emit the rows as RECORD messages. |
| `batch_output.format` | `parquet` \| `jsonl` | `"parquet"` | Output file encoding. |
| `batch_output.compression` | `zstd` \| `snappy` \| `gzip` \| `none` or null | unset | Output compression. Default: zstd for parquet, gzip for jsonl. |
| `batch_output.storage.root` | string or null | unset | An fsspec URL (file://, s3://, ...). Default: the input file's directory. |
| `batch_output.storage.params` | mapping of any | `{}` | fsspec storage options. |
| `batch_output.delete_input` | boolean | `false` | Delete each input file after its output is written. |
| `batch_output.row_group_size` | integer | `131072` | Rows per parquet row group, which is also the processing chunk size. |
| `reject.storage` | string | `"./.map-conform/rejects"` | Directory for reject files. |
| `reject.format` | `jsonl` \| `parquet` | `"jsonl"` | Reject file encoding. |
| `metrics_path` | string or null | unset | Write per-stream metrics as JSON here at the end of the run. |
| `add_record_metadata` | boolean or null | unset | Add the seven Singer SDK _sdc_* columns (default false); the same as defaults.add_record_metadata, which a stream can override. |
| `stream_maps` | mapping of any or null | unset | Singer SDK stream maps, accepted unchanged and translated into the spec at start-up; the spec wins where both define a column. |
| `stream_map_config` | mapping of any | `{}` | SDK stream-map config: config in expressions, merged under spec_vars. |
| `faker_config` | mapping of any or null | unset | SDK Faker config ({seed, locale}); the same as defaults.faker. |
| `flattening_enabled` | boolean or null | unset | SDK flattening: the same as defaults.nested: flatten. |
| `flattening_max_depth` | integer or null | unset | SDK flattening depth: defaults.flatten.max_depth. |
| `flattening_separator` | string or null | unset | SDK flattening separator: defaults.flatten.separator. |
| `flattening_max_key_length` | integer or null | unset | SDK flattened key length: defaults.flatten.max_key_length. |

## Spec file: top level

| Key | Type | Default | Meaning |
| -- | -- | -- | -- |
| `version` | `1` | required | The spec version. |
| `defaults` | object | the section below | Inherited by every stream. |
| `macros` | mapping of macro | `{}` | Named, parameterised transform chains. |
| `udfs` | mapping of string | `{}` | Python functions by name, as 'package.module:function'. |
| `streams` | mapping of object | `{}` | Per-stream rules: StreamSpec keys plus any Defaults key. A key is a glob over tap stream names, or a new stream name when the rules have source. |
| `else` | `keep` \| `drop` | `"keep"` | Tap streams that match no key: keep (conform with the defaults) or drop. |

## `defaults`

Inherited by every stream; a stream rule may set any of these keys to override them.

| Key | Type | Default | Meaning |
| -- | -- | -- | -- |
| `naming.preset` | `map-conform` \| `sdk` | `"map-conform"` | sdk reproduces the Singer SDK's SQL conform_name byte for byte (for migrations); only on_collision applies then. |
| `naming.case` | `snake` \| `lower` \| `upper` \| `preserve` | `"snake"` | snake splits camelCase and lowercases; lower and upper only change case. |
| `naming.split_camel` | boolean | `true` | customerID -> customer_id; HTTPServer -> http_server. |
| `naming.ascii` | `transliterate` \| `strip` \| `keep` | `"transliterate"` | transliterate with the bundled table (ADR-0012), strip non-ASCII, or keep it. |
| `naming.replace_invalid` | string | `"_"` | Replacement for characters outside [a-z0-9_] after casing. |
| `naming.collapse` | boolean | `true` | Collapse runs of '_' and trim it from both ends. |
| `naming.leading_digit` | `prefix` \| `letter` \| `error` | `"prefix"` | prefix '_', letter (SDK style: 0 -> a), or error. |
| `naming.max_length` | integer | `63` | Longer names are truncated (see truncate). At least 8, room for a hash suffix. |
| `naming.truncate` | `hash` \| `error` | `"hash"` | hash keeps the head plus '_' and 6 hex digits of a hash of the full name. |
| `naming.reserved_words` | `suffix` \| `prefix` \| `error` \| `ignore` | `"suffix"` | What to do with a reserved word: suffix '_', prefix '_', error or ignore. |
| `naming.reserved_dialects` | list of `postgres` \| `duckdb` \| `snowflake` \| `ansi` | `["postgres", "duckdb", "snowflake"]` | Reserved-word lists to union. ansi (SQL:2016) is opt-in: it reserves common column names such as date, year and value. |
| `naming.on_collision` | `error` \| `suffix` | `"error"` | Two names conforming to the same output: error, or add _2, _3, ... |
| `naming.nested` | boolean | `true` | Also conform the member names of struct columns. |
| `stream.name` | `conform` \| `preserve` | `"conform"` | Conform stream names like column names, or keep them. |
| `stream.prefix` | string | `""` | Added after conforming. |
| `stream.split` | string or null | unset | Emit only the part after the last occurrence of this separator. |
| `values.trim` | boolean | `true` | Trim surrounding whitespace from strings. |
| `values.null_tokens` | list of string | `["", "NULL", "null", "N/A", "n/a", "#N/A", "NaN", "-"]` | Strings that mean null. |
| `values.null_tokens_case_sensitive` | boolean | `false` | Match null tokens case-sensitively. |
| `values.empty_string_for_string` | `keep` \| `null` | `"keep"` | What "" becomes in a string column. |
| `timestamp.assume_tz` | string | `"UTC"` | Time zone of naive input cast to timestamptz. |
| `timestamp.output_precision` | `s` \| `ms` \| `us` | `"us"` | Fractional precision on output. |
| `timestamp.formats` | list of string | `["iso"]` | Formats tried in order: strftime patterns, iso, excel_serial, epoch_*, rfc2822. |
| `boolean.true_values` | list of string | `["true", "t", "yes", "y", "1", "on"]` | Strings that mean true. |
| `boolean.false_values` | list of string | `["false", "f", "no", "n", "0", "off"]` | Strings that mean false. |
| `on_error` | `raise` \| `null` \| `keep` \| `reject` | `"raise"` | What a failed cast or transform does: raise, null, keep the raw value, or reject the row to the dead-letter sink. |
| `add_record_metadata` | boolean | `false` | Add the seven Singer SDK _sdc_* columns to SCHEMA, RECORD and BATCH output, as SDK targets do with their setting of the same name. |
| `undeclared` | `conform` \| `drop` \| `error` | `"conform"` | Columns the spec does not mention: conform them from the tap SCHEMA, drop them, or fail. |
| `nested` | `json` \| `flatten` \| `keep` | `"json"` | Undeclared object and array columns: JSON text, flattened, or typed struct/list. |
| `flatten.separator` | string | `"__"` | Joins parent and child keys. |
| `flatten.max_depth` | integer | `1` | Levels of nesting to flatten. |
| `flatten.max_key_length` | integer | `255` | Longest flattened key. |
| `faker.seed` | integer or null | unset | Seed for reproducible fake values. |
| `faker.locale` | string or list of string or null | unset | Faker locale or locales. |
| `engine` | `arrow` \| `polars` \| `row` | `"arrow"` | BATCH engine for parquet files: arrow (vectorised), polars (the polars extra; also vectorises regular expressions and strptime date formats), or row, which runs every row as a RECORD would: the reference to compare a vectorised result against. |
| `max_reject_rate` | number or null | unset | Fail the run when more than this fraction of a stream's rows is rejected (0-1). |
| `max_null_rate` | number or null | unset | Fail the run when on_error: null nulls values in more than this fraction of a stream's rows (0-1). |

## `streams.<glob>`

Plus any `defaults` key. A key is a glob over tap stream names, or a new output stream's
name when the rule has `source`.

| Key | Type | Default | Meaning |
| -- | -- | -- | -- |
| `alias` | string or `{expr: ...}` or null | unset | Final stream name; bypasses stream naming and prefix. |
| `source` | string or null | unset | Make this key a new output stream projected from this tap stream (split or copy). |
| `prefix` | string or null | unset | Overrides stream.prefix. |
| `key_properties` | list of string or null | unset | Overrides the tap's key properties; source or conformed names. |
| `filter` | string or null | unset | Rows where this expression is falsy are dropped; sees conformed names. |
| `columns` | mapping of object | `{}` | Columns by source name, or by new name for derived columns. |
| `order` | `source` \| `declared` | `"source"` | Output column order: the tap's, or the order of columns here. |
| `drop` | boolean | `false` | Drop the whole stream. |

## `columns.<name>`

| Key | Type | Default | Meaning |
| -- | -- | -- | -- |
| `name` | string or null | unset | Output name. It is checked, never silently conformed. |
| `type` | string or null | unset | Declared CType, e.g. int64, decimal(18,2), timestamptz. From the tap SCHEMA if absent. |
| `nullable` | boolean | `true` | If false, a null is an error under on_error. |
| `source` | string or list of string or null | unset | Source column(s) if not the key; a list coalesces in order. |
| `expr` | string or null | unset | Derived value. Without source, it creates a new column. |
| `default` | any | unset | Used when the value is missing or null after transforms. |
| `transform` | chain or null | unset | Steps run before the implicit cast. |
| `parse` | mapping of any or null | unset | Keyword arguments for the implicit cast, e.g. {formats: [...], tz: ...}. |
| `true_values` | list of string or null | unset | Overrides boolean.true_values. |
| `false_values` | list of string or null | unset | Overrides boolean.false_values. |
| `null_tokens` | list of string or null | unset | Overrides values.null_tokens. |
| `trim` | boolean or null | unset | Overrides values.trim. |
| `on_error` | `raise` \| `null` \| `keep` \| `reject` or null | unset | Overrides on_error. |
| `max_length` | integer or null | unset | Longest string allowed. |
| `on_overflow` | `truncate` \| `error` | `"error"` | What a string longer than max_length does. |
| `enum` | list of any or null | unset | Allowed values, checked after the cast. |
| `drop` | boolean | `false` | Remove the column. Dropping a key property is an error. |
| `doc` | string or null | unset | Copied to the SCHEMA description. |
| `sql_type` | string or null | unset | Overrides the emitted x-sql-datatype hint. |
| `when` | string or null | unset | Apply the chain only to rows where this is truthy; sees conformed names. |
| `fields` | mapping of object or null | unset | Transforms on nested members of struct and json columns, by dotted path. |
| `shape` | mapping of any or null | unset | JSON Schema of the column's object or array value, inline or as a path to a .json file (relative to the spec file). It alone decides the column's type, or its flattened columns; members it does not declare are dropped, counted and logged; a member's default (null, {}, []) is used when it is missing or empty. |
| `flatten` | boolean or null | unset | Flatten this column into parent__child columns: from its shape when it has one, else from the tap's schema (the column then takes only source; declare leaf columns for types or steps). false keeps it whole under nested: flatten. Unset: follow nested: flatten. |
| `engine` | `arrow` \| `polars` \| `row` or null | unset | Overrides engine for this column. |
| `infer_type` | `sdk` or null | unset | Without type: infer it from expr as the Singer SDK mapper does (int(...) is an integer, and so on). Set by stream_maps translation; declaring type is clearer. |

## `fields.<path>`

For `struct` and `json` columns; paths are member names joined by `.`, with `[*]` for
list items.

| Key | Type | Default | Meaning |
| -- | -- | -- | -- |
| `transform` | chain or null | unset | Steps applied to the member. |
| `when` | string or null | unset | Apply only where this expression is truthy. |
| `drop` | boolean | `false` | Remove the member. |

## Types

Kinds: `boolean`, `int16`, `int32`, `int64`, `float32`, `float64`, `decimal`, `string`, `date`, `time`, `timestamp`, `timestamptz`, `uuid`, `binary`, `json`, `struct`, `list`. Parameterised: `decimal(p,s)`, `string(n)`, `list<T>`,
`struct<name: T, ...>`. SQL aliases are read too (`bigint`, `varchar(n)`, `long`, ...).

## `parse` options

A column's `parse` sets the options of its cast, by its type; a `cast` step takes the
same options. A default written `defaults.…` comes from that stream setting (and the
column's own `trim`, `null_tokens`, `true_values` or `false_values`). An unknown key
is an error at `columns.<name>.parse.<key>`.

### `binary`

| Key | Type | Default | Meaning |
| -- | -- | -- | -- |
| `trim` | boolean | `defaults.values.trim` | Trim surrounding whitespace before parsing. |
| `null_tokens` | list of string | `defaults.values.null_tokens` | Text that means null, compared after trimming. |
| `null_tokens_case_sensitive` | boolean | `defaults.values.null_tokens_case_sensitive` | Compare null tokens case-sensitively. |
| `encoding` | `base64` \| `hex` \| `utf8` | `"base64"` | How the text encodes the bytes (strict). |

### `boolean`

| Key | Type | Default | Meaning |
| -- | -- | -- | -- |
| `trim` | boolean | `defaults.values.trim` | Trim surrounding whitespace before parsing. |
| `null_tokens` | list of string | `defaults.values.null_tokens` | Text that means null, compared after trimming. |
| `null_tokens_case_sensitive` | boolean | `defaults.values.null_tokens_case_sensitive` | Compare null tokens case-sensitively. |
| `true_values` | list of string | `defaults.boolean.true_values` | Text read as true. |
| `false_values` | list of string | `defaults.boolean.false_values` | Text read as false. |
| `case_sensitive` | boolean | `false` | Compare the tokens case-sensitively. |

### `date`, `time`, `timestamp`, `timestamptz`

| Key | Type | Default | Meaning |
| -- | -- | -- | -- |
| `trim` | boolean | `defaults.values.trim` | Trim surrounding whitespace before parsing. |
| `null_tokens` | list of string | `defaults.values.null_tokens` | Text that means null, compared after trimming. |
| `null_tokens_case_sensitive` | boolean | `defaults.values.null_tokens_case_sensitive` | Compare null tokens case-sensitively. |
| `formats` | list of string | `defaults.timestamp.formats` | Formats tried in order, the first match winning: strftime patterns and the keywords below. |
| `tz` | string | `defaults.timestamp.assume_tz` | IANA zone of naive input; input with an offset keeps it. |
| `ambiguous` | `error` \| `earliest` \| `latest` | `"error"` | A wall time that occurs twice (DST ends). |
| `nonexistent` | `error` \| `shift` | `"error"` | A wall time skipped by DST: an error, or the instant after the gap. |
| `min_year` | integer or null | unset | Earliest year accepted. |
| `max_year` | integer or null | unset | Latest year accepted. |
| `output_precision` | `s` \| `ms` \| `us` | `defaults.timestamp.output_precision` | Fraction digits kept. |

### `decimal`, `float32`, `float64`, `int16`, `int32`, `int64`

| Key | Type | Default | Meaning |
| -- | -- | -- | -- |
| `trim` | boolean | `defaults.values.trim` | Trim surrounding whitespace before parsing. |
| `null_tokens` | list of string | `defaults.values.null_tokens` | Text that means null, compared after trimming. |
| `null_tokens_case_sensitive` | boolean | `defaults.values.null_tokens_case_sensitive` | Compare null tokens case-sensitively. |
| `locale` | `us` \| `eu` \| `ch` | `"us"` | Separators: us is 1,234.56; eu is 1.234,56; ch is 1'234.56. |
| `thousands` | string or null | unset | Thousands separator, overriding the locale's. |
| `decimal_point` | string or null | unset | Decimal point, overriding the locale's. |
| `parens_negative` | boolean | `false` | (12.50) is -12.50. |
| `trailing_minus` | boolean | `false` | 12.50- is -12.50. |
| `percent` | `error` \| `divide` \| `strip` | `"error"` | A trailing %: an error, divide by 100 (15% is 0.15), or drop the sign (15% is 15). |
| `rounding` | `half_up` \| `half_even` \| `down` \| `error` or null | unset | Digits beyond the scale: half_up (halves away from zero), half_even, down, or error. Unset: half_up for decimals, error for integers ('12.0' is always 12). |
| `nan` | `null` \| `error` | `"null"` | What NaN and infinity become. |

### `json`

| Key | Type | Default | Meaning |
| -- | -- | -- | -- |
| `parse_strings` | boolean | `true` | Decode text that is already JSON, instead of storing it as a JSON string. |
| `sort_keys` | boolean | `false` | Write object keys sorted. |
| `null_tokens` | list of string | `[]` | Text that means null (none by default: text is data in a json column). |

### `list`, `struct`

| Key | Type | Default | Meaning |
| -- | -- | -- | -- |
| `parse_strings` | boolean | `true` | Decode text that holds JSON. |

### `string`

| Key | Type | Default | Meaning |
| -- | -- | -- | -- |
| `trim` | boolean | `defaults.values.trim` | Trim surrounding whitespace before parsing. |
| `null_tokens` | list of string | `defaults.values.null_tokens` | Text that means null, compared after trimming. |
| `null_tokens_case_sensitive` | boolean | `defaults.values.null_tokens_case_sensitive` | Compare null tokens case-sensitively. |
| `empty_string_for_string` | `keep` \| `null` | `defaults.values.empty_string_for_string` | What an empty string becomes in a string column. |
| `max_length` | integer or null | unset | The longest value allowed (also set by string(n) or the column's max_length). |
| `on_overflow` | `truncate` \| `error` | `"error"` | What a longer value does. |

### `uuid`

| Key | Type | Default | Meaning |
| -- | -- | -- | -- |
| `trim` | boolean | `defaults.values.trim` | Trim surrounding whitespace before parsing. |
| `null_tokens` | list of string | `defaults.values.null_tokens` | Text that means null, compared after trimming. |
| `null_tokens_case_sensitive` | boolean | `defaults.values.null_tokens_case_sensitive` | Compare null tokens case-sensitively. |
| `version` | integer or null | unset | Require this UUID version. |

### Format keywords

| Keyword | Reads |
| -- | -- |
| `iso` | ISO-8601, leniently: Z or z, a T, t or space separator, any fraction digits (kept to microseconds), date-only or time-only |
| `excel_serial` | Spreadsheet day numbers, 1900 system: 46095 is 2026-03-14; serials below 60 count from 1899-12-31, and 60 (Lotus's 1900-02-29) is an error |
| `excel_serial_1904` | Spreadsheet day numbers, 1904 system |
| `epoch_s` | Seconds since 1970-01-01 UTC |
| `epoch_ms` | Milliseconds since 1970-01-01 UTC |
| `epoch_us` | Microseconds since 1970-01-01 UTC |
| `epoch_ns` | Nanoseconds since 1970-01-01 UTC (truncated to microseconds) |
| `epoch_auto` | An epoch whose unit is chosen by magnitude (opt-in only) |
| `rfc2822` | Email-style dates: Sat, 14 Mar 2026 09:26:53 +0000 |

## Builtin steps

| Step | Options | Meaning |
| -- | -- | -- |
| `assume_tz` | `tz` | Place a naive timestamp in tz, giving an aware one. |
| `clamp` | `min`, `max`, `on_out_of_range` | Limit a number to [min, max], or fail outside it. |
| `date_from_timestamp` | `tz` | The date of a timestamp, in tz when given. |
| `fake` | `provider`, `args`, `unique` | A fake value from a Faker provider, seeded by defaults.faker (faker extra). |
| `hash` | `algo`, `salt`, `skip_first` | Hex digest of the value's text, with salt; skip_first keeps a clear prefix. |
| `left` | `n` | The first n characters. |
| `lower` | none | Lowercase text. |
| `map_values` | `values`, `default`, `case_sensitive` | Replace listed values; others become default when it is set. |
| `mask` | `keep_first`, `keep_last`, `char` | Replace characters with char, keeping keep_first and keep_last. |
| `mask_hidden` | `value` | Replace a string with value ('hidden'); string columns only. |
| `mask_number` | `value` | Replace a number with value (0), in the column's own type. |
| `normalize_unicode` | `form` | Unicode normalisation (NFKC by default). |
| `normalize_whitespace` | none | Collapse runs of whitespace to one space and trim. |
| `null_tokens` | `tokens`, `case_sensitive` | Null for any of the tokens (e.g. N/A, -). |
| `pad` | `width`, `fill`, `side` | Pad text to width with fill, on the left or right. |
| `redact_date` | `to` | Keep only the year, or the year and month; the type is kept. |
| `regex_extract` | `pattern`, `group`, `flags` | A group of the first match, or null. |
| `regex_replace` | `pattern`, `repl`, `flags` | Replace every match of pattern with repl. |
| `remove_control_chars` | none | Remove control characters. |
| `right` | `n` | The last n characters. |
| `round` | `ndigits` | Round half away from zero to ndigits. |
| `scale` | `factor` | Multiply by factor, exactly for decimals (e.g. cents to units). |
| `set_null` | none | Always null; the column becomes nullable. |
| `split` | `sep`, `trim` | Split text into a list of strings. |
| `strip_chars` | `chars` | Strip the listed characters from both ends, e.g. currency symbols. |
| `substring` | `start`, `length` | length characters from start. |
| `title` | none | Title Case text. |
| `to_local` | `tz` | The wall-clock time in tz, as a naive timestamp. |
| `to_utc` | none | An aware timestamp in UTC (explicit; timestamptz output is always UTC). |
| `tokenize` | `key` | Keyed HMAC-SHA256 hex digest: stable across runs, secret without the key. |
| `trim` | `chars` | Remove surrounding whitespace, or chars. |
| `truncate` | `unit` | Truncate a date or timestamp to unit. |
| `upper` | none | Uppercase text. |
| `cast` | per target type | Casts to any of `binary`, `boolean`, `date`, `decimal`, `float32`, `float64`, `int16`, `int32`, `int64`, `json`, `list`, `string`, `struct`, `time`, `timestamp`, `timestamptz`, `uuid`. |

## Expression functions

Builtin steps, `cast(value, type, ...)`, macros and UDFs are callable in expressions
too. Names in scope: `value`/`self`, columns by conformed name, `record`/`_`,
`source(name)`, `config`, `stream`, `source_stream`, `row_number`, `NULL`, `fake`.

| Function | Group | Meaning |
| -- | -- | -- |
| `is_blank(value)` | predicates | True for null or whitespace-only text. |
| `is_bool(value)` | predicates | True for a boolean. |
| `is_date(value)` | predicates | True for a date (not a timestamp). |
| `is_datetime(value)` | predicates | True for a timestamp. |
| `is_decimal(value)` | predicates | True for an exact decimal. |
| `is_dict(value)` | predicates | True for an object. |
| `is_int(value)` | predicates | True for an integer (not a boolean). |
| `is_list(value)` | predicates | True for a list. |
| `is_null(value)` | predicates | True for null. |
| `is_number(value)` | predicates | True for an int, float or decimal (not a boolean). |
| `is_string(value)` | predicates | True for text. |
| `matches(pattern, value)` | predicates | True when the regular expression is found in the value's text; false for null. |
| `from_json(text)` | coercion | The value of JSON text; fractions are exact decimals. |
| `to_bool(value)` | coercion | A boolean from true/false, yes/no, y/n, t/f, 1/0 or on/off (any case). |
| `to_decimal(value, precision=None, scale=None)` | coercion | An exact decimal, rounded half up to ``scale`` digits when given. |
| `to_float(value)` | coercion | A float. |
| `to_int(value)` | coercion | An integer; a fraction is an error ("12.0" is fine). |
| `to_json(value)` | coercion | JSON text (null becomes the text null). |
| `to_str(value)` | coercion | Text: decimals in plain notation, temporals in ISO 8601, booleans as true/false. |
| `date_trunc(value, unit="day")` | temporal | The value truncated to year, month, day, hour, minute or second. |
| `ensure_utc(value, assume="UTC")` | temporal | A UTC datetime; naive values are taken to be in ``assume``. |
| `excel_date(serial, system_1904=False)` | temporal | A naive datetime from a spreadsheet serial (1900 system with Lotus's leap-year bug). |
| `from_epoch(number, unit="s")` | temporal | A UTC datetime from seconds (s), ms, us, ns since 1970, or auto by magnitude. |
| `now_utc()` | temporal | The current time, in UTC. |
| `parse_datetime(value, *formats, tz="UTC")` | temporal | A datetime from the formats tried in order (default iso); naive results are placed in tz. |
| `to_tz(value, tz)` | temporal | The same instant in another zone. |
| `join(items, sep="")` | text | The items' text joined with ``sep``; null items are skipped. |
| `lower(value)` | text | Lowercase text. |
| `pad_left(value, width, char=" ")` | text | Text padded on the left to ``width`` characters. |
| `re_extract(pattern, value, group=1)` | text | A group of the first match (the first group by default), or null. |
| `re_match(pattern, value)` | text | The text matched at the start of the value, or null. |
| `re_sub(pattern, replacement, value)` | text | Replace every match of the pattern. |
| `split(value, sep=None, maxsplit=-1)` | text | A list of parts. |
| `strip(value, chars=None)` | text | Text without leading and trailing whitespace (or ``chars``). |
| `upper(value)` | text | Uppercase text. |
| `ceil(value)` | numeric | The smallest integer not below the value. |
| `clamp(value, low, high)` | numeric | The value limited to [low, high]. |
| `floor(value)` | numeric | The largest integer not above the value. |
| `round(value, ndigits=None)` | numeric | Round half away from zero; an int without ndigits, else the input's type. |
| `coalesce(*values)` | misc | The first non-null value. |
| `md5(text)` | misc | The MD5 hex digest of the text (as the SDK's md5). |
| `nullif(value, other)` | misc | Null when the value equals ``other``, else the value. |
| `rand()` | misc | A random float in [0, 1) (as simpleeval's rand). |
| `randint(top)` | misc | A random integer in [0, top) (as simpleeval's randint). |
| `sha256(text)` | misc | The SHA-256 hex digest of the text (as the SDK's sha256). |
| `uuid4()` | misc | A random UUID. |
| `uuid5(namespace, name)` | misc | A name-based UUID; the namespace is a UUID or one of dns, url, oid, x500. |
| `abs(value)` | python | Absolute value. |
| `all(items)` | python | True if every item is truthy. |
| `any(items)` | python | True if any item is truthy. |
| `bool(value)` | python | Python truthiness (as in SDK stream maps). |
| `dict(items=(), **kwargs)` | python | A new dict. |
| `enumerate(items, start=0)` | python | (index, item) pairs. |
| `float(value)` | python | Python float (as in SDK stream maps). |
| `int(value, base=10)` | python | Python int (as in SDK stream maps). |
| `len(value)` | python | Length of text or a list. |
| `list(items=())` | python | A new list. |
| `max(*values)` | python | The largest value. |
| `min(*values)` | python | The smallest value. |
| `range(stop \| start, stop[, step])` | python | A range of at most 100000 integers. |
| `set(items=())` | python | A new set. |
| `sorted(items, reverse=False)` | python | A sorted list (no key function). |
| `str(value)` | python | Python str (as in SDK stream maps). |
| `sum(items, start=0)` | python | Sum of the items. |
| `tuple(items=())` | python | A new tuple. |
| `zip(*lists)` | python | Tuples of items in step. |
| `datetime.<MAXYEAR, MINYEAR, UTC, date, datetime, time, ...>` | modules | The datetime module, read-only. |
| `decimal.<Decimal, InvalidOperation, ROUND_05UP, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ...>` | modules | The decimal module, read-only. |
| `json.<dumps, loads, ...>` | modules | The json module, read-only. |
| `math.<acos, acosh, asin, asinh, atan, atan2, ...>` | modules | The math module, read-only. |
| `re.<A, ASCII, DOTALL, I, IGNORECASE, M, ...>` | modules | The re module, read-only. |
