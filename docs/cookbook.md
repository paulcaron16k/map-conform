# map-conform cookbook

Each recipe shows a spec, the records a tap sends, and the records map-conform emits. Every
example here is run by the test suite (`tests/test_cookbook.py`), so what you read is what
the mapper does. Keys and options are listed in the [spec reference](spec-reference.md).

Each recipe has the same parts:

- **spec**: the conform spec (`spec_path` in Meltano);
- **input**: the records the tap sends. Their SCHEMA, which a real tap sends first, says
  every property is a string unless a **schema** block gives the tap's property types;
- **settings**: any plugin settings besides the spec (`config` of the mapping in Meltano);
- **output**: the records map-conform writes, and, where shown, the **rejects** it sets
  aside or the **error** that stops the run.

To try one, save the spec as `conform.yml` and pipe Singer messages through
`map-conform --config config.json`, where `config.json` is `{"spec_path": "conform.yml"}`
plus any settings. `map-conform spec validate conform.yml` checks a spec without data.

## How a spec is applied

**Which rules a stream gets.** A `streams` key is a glob over the tap's stream names,
matched case-sensitively. A stream gets `defaults`, then every matching glob from the least
to the most specific, then its exact name; objects merge key by key and lists replace. Tap
streams that match no key are conformed with `defaults` (`else: drop` drops them instead).

**What happens to one column**, in order: the tap's value (or the first non-null of a
`source` list); the column's `expr`, if any; its `transform` steps; the cast to its `type`,
which trims, applies the null tokens and parses with the `parse` options; then `default`,
`nullable` and `enum`. Steps before the cast see the raw value, so put `trim` or `lower`
first when a step needs clean text; a `cast` step in the chain says where the cast happens
when a step needs the typed value (`[cast, redact_date]`). A failure anywhere follows
`on_error`.

**Names in expressions.** `expr`, `when` and `filter` see the other columns by their
*conformed* names and typed values (`qty`, not `Qty`); `value` is the column's own value;
`record['Qty']` reads the raw tap record. Imported stream maps use `record[...]`, because
the SDK's expressions read raw properties.

**Columns the spec does not mention** follow `undeclared`: `conform` (the default) types
them from the tap's SCHEMA and conforms their names, `drop` leaves them out (key properties
stay), `error` fails. The `strict` setting means `undeclared: error` everywhere, and makes
warnings errors. `nested`
decides how undeclared objects land (JSON text, flattened or kept); see the nested recipes.

**Missing, null and empty.** A missing property and a null are the same. Text equal to a
null token (`N/A`, `#N/A`, `-`, ... after trimming; see `values.null_tokens`) is null in any
column. An empty string is null too, except in a string column, where it stays `""` unless
`values.empty_string_for_string: null`. A declared shape's member `default` also replaces an
empty object or list.

## A CSV export

tap-csv reads every value as text. Declare the types you want; the casts clean the text on
the way: currency symbols and thousands separators, accounting negatives, percentages,
yes/no words, US dates and null tokens. Column names are conformed to snake_case.

```yaml cookbook:spec
version: 1
streams:
  Orders Export:
    columns:
      Order ID: {name: order_id, type: int64, nullable: false}
      Amount ($): {type: "decimal(12,2)", parse: {parens_negative: true}}
      Discount %: {type: "decimal(6,4)", parse: {percent: divide}}
      Paid?: {type: boolean}
      Order Date: {type: date, parse: {formats: ["%m/%d/%Y", iso]}}
      Customer Email: {type: string}
```

```json cookbook:input
[
  {"Order ID": " 1001 ", "Amount ($)": "$1,234.50", "Discount %": "15%", "Paid?": "Yes",
   "Order Date": "03/14/2026", "Customer Email": "ann@example.com"},
  {"Order ID": "1002", "Amount ($)": "(12.00)", "Discount %": "0%", "Paid?": "no",
   "Order Date": "2026-03-15", "Customer Email": "N/A"}
]
```

```json cookbook:output
[
  {"order_id": 1001, "amount": "1234.50", "discount": "0.1500", "paid": true, "order_date": "2026-03-14", "customer_email": "ann@example.com"},
  {"order_id": 1002, "amount": "-12.00", "discount": "0.0000", "paid": false, "order_date": "2026-03-15", "customer_email": null}
]
```

## European and Swiss formats

`locale` sets the separators: `eu` reads `1.234,56`, `ch` reads `1'234.56`. Dates follow the
`strptime` patterns you list, tried in order. Boolean words are stream defaults (a column can
set its own `true_values` and `false_values`); they are compared without case.

```yaml cookbook:spec
version: 1
defaults:
  boolean: {true_values: [ja, oui, "true"], false_values: [nein, non, "false"]}
streams:
  bestellungen:
    columns:
      Bestell-Nr.: {name: bestell_nr, type: int64}
      Betrag (€): {type: "decimal(12,2)", parse: {locale: eu}}
      Betrag CHF: {type: "decimal(12,2)", parse: {locale: ch}}
      Datum: {type: date, parse: {formats: ["%d.%m.%Y", iso]}}
      Bezahlt: {type: boolean}
```

```json cookbook:input
[
  {"Bestell-Nr.": "1001", "Betrag (€)": "1.234,56 €", "Betrag CHF": "CHF 1'234.50",
   "Datum": "14.03.2026", "Bezahlt": "ja"},
  {"Bestell-Nr.": "1002", "Betrag (€)": "-12,00", "Betrag CHF": "12.00",
   "Datum": "2026-03-15", "Bezahlt": "Nein"}
]
```

```json cookbook:output
[
  {"bestell_nr": 1001, "betrag": "1234.56", "betrag_chf": "1234.50", "datum": "2026-03-14", "bezahlt": true},
  {"bestell_nr": 1002, "betrag": "-12.00", "betrag_chf": "12.00", "datum": "2026-03-15", "bezahlt": false}
]
```

Every `parse` option, by type, is in the
[spec reference](spec-reference.md#parse-options), with the date format keywords
(`iso`, `excel_serial`, `epoch_s`, `rfc2822`, ...).

## A spreadsheet (XLSX) export

Spreadsheet taps send whole numbers as floats, dates as serial numbers, binary float
artefacts, and error cells as text. Excel serials are a date format of their own, and
`#N/A` is one of the default null tokens.

```yaml cookbook:spec
version: 1
streams:
  inventory:
    columns:
      SKU: {type: string}
      Qty: {type: int32}
      Unit Cost: {type: "decimal(10,2)"}
      Received: {type: date, parse: {formats: [excel_serial, iso]}}
      Weight (kg): {type: "decimal(8,3)", on_error: "null"}
```

```json cookbook:schema
{"SKU": {"type": "string"}, "Qty": {"type": "number"}, "Unit Cost": {"type": "number"},
 "Received": {"type": ["number", "string"]}, "Weight (kg)": {"type": ["number", "string"]}}
```

```json cookbook:input
[
  {"SKU": "A-1", "Qty": 3.0, "Unit Cost": 0.30000000000000004, "Received": 46095.0,
   "Weight (kg)": 1.5},
  {"SKU": "B-2", "Qty": 12.0, "Unit Cost": 2.5, "Received": "2026-03-01",
   "Weight (kg)": "#N/A"}
]
```

```json cookbook:output
[
  {"sku": "A-1", "qty": 3, "unit_cost": "0.30", "received": "2026-03-14", "weight_kg": "1.500"},
  {"sku": "B-2", "qty": 12, "unit_cost": "2.50", "received": "2026-03-01", "weight_kg": null}
]
```

## When a value is bad

By default a value that cannot be cast stops the run (`on_error: raise`), naming the stream,
column, row and value:

```yaml cookbook:spec
version: 1
streams:
  orders:
    columns:
      id: {type: int64}
      qty: {type: int32}
```

```json cookbook:input
[{"id": "1", "qty": "3"}, {"id": "2", "qty": "three"}]
```

```text cookbook:error
stream 'orders', column 'qty', row 2: cast: int32 failed on 'three': not a number.
```

The next recipe shows the other choices.

## Setting bad values aside

A column, a stream or `defaults` can set `on_error` to keep the run going:

| `on_error` | The row | Counted in metrics as |
| -- | -- | -- |
| `raise` (default) | stops the run |  |
| `null` | lands with null in that column (an error if the column is `nullable: false`) | `rows_nulled` |
| `keep` | lands with the source value; string and json columns only | `values_kept` |
| `reject` | is left out of the output and written to the rejects file | `rows_rejected` |

```yaml cookbook:spec
version: 1
streams:
  orders:
    columns:
      id: {type: int64}
      qty: {type: int32, on_error: reject}
      price: {type: "decimal(10,2)", on_error: "null"}
      note: {type: string}
```

```json cookbook:input
[
  {"id": "1", "qty": "3", "price": "2.50", "note": "fine"},
  {"id": "2", "qty": "three", "price": "2.50", "note": "qty is not a number"},
  {"id": "3", "qty": "4", "price": "12,50", "note": "price uses a comma"}
]
```

```json cookbook:output
[
  {"id": 1, "qty": 3, "price": "2.50", "note": "fine"},
  {"id": 3, "qty": 4, "price": null, "note": "price uses a comma"}
]
```

Rejected rows go to `<reject.storage>/<output stream>/<run id>.jsonl` (default
`./.map-conform/rejects`; `reject.format: parquet` is the other choice). Each line has the
`stream`, `row_number`, `column`, `rule`, the full `error`, the `value` and the whole raw
`record` (both as JSON text) and `rejected_at`, so a row can be fixed and replayed:

```json cookbook:rejects
[{"stream": "orders", "row_number": 2, "column": "qty", "rule": "cast: int32", "value": "\"three\""}]
```

To fail when a source goes bad without stopping on the first value, set `max_reject_rate` or
`max_null_rate` (a fraction, 0-1, of a stream's rows) in `defaults` or on a stream. They are
checked before each STATE message is passed on, so a target never commits a bookmark past
rows a bad source spoiled.

## Epoch timestamps

APIs often send times as seconds or milliseconds since 1970. Say which; the result is a UTC
timestamp.

```yaml cookbook:spec
version: 1
streams:
  events:
    columns:
      created: {type: timestamptz, parse: {formats: [epoch_s]}}
      updated_ms: {type: timestamptz, parse: {formats: [epoch_ms]}}
      seen: {type: timestamptz, parse: {formats: [iso, epoch_s]}}
```

```json cookbook:schema
{"created": {"type": "integer"}, "updated_ms": {"type": "integer"}, "seen": {"type": "string"}}
```

```json cookbook:input
[
  {"created": 1773480413, "updated_ms": 1773480413123, "seen": "2026-03-14T10:26:53+01:00"},
  {"created": 1773480413, "updated_ms": 1773480413999, "seen": "1773480413"}
]
```

```json cookbook:output
[
  {"created": "2026-03-14T09:26:53.000000Z", "updated_ms": "2026-03-14T09:26:53.123000Z", "seen": "2026-03-14T09:26:53.000000Z"},
  {"created": "2026-03-14T09:26:53.000000Z", "updated_ms": "2026-03-14T09:26:53.999000Z", "seen": "2026-03-14T09:26:53.000000Z"}
]
```

## Pseudonyms: hashes and fake names

A hash is the same for the same input, so hashed emails still join across tables and runs.
Normalise before hashing: steps before the cast see the raw value, so trim and lowercase
first, or `Ann@Example.com ` and `ann@example.com` hash differently. `hash` is SHA-256 by
default (`algo: md5 | sha1 | sha512`); keep the salt out of the spec with `${env:...}`.

For a readable stand-in, `fake.seed_instance(value) or fake.name()` gives the same fake name
for the same real one. It reseeds the stream's one Faker generator, so other fake columns in
the row would follow it: mask those instead, as the phone is here. For random fakes,
`{fake: name}` and `defaults.faker.seed` give the same sequence on every run. Fakes need the
`faker` extra.

```yaml cookbook:spec
version: 1
streams:
  customers:
    columns:
      email: {transform: [trim, lower, {hash: {salt: "${salt}"}}]}
      name: {type: string, transform: {expr: "fake.seed_instance(value) or fake.name()"}}
      phone: {transform: {mask: {keep_last: 4}}}
```

```json cookbook:settings
{"spec_vars": {"salt": "pepper"}}
```

```json cookbook:input
[
  {"email": "Ann@Example.com", "name": "Ann Lee", "phone": "+1 555 0100"},
  {"email": "ann@example.com ", "name": "Bob Ray", "phone": "+1 555 0199"},
  {"email": "bob@example.com", "name": "Ann Lee", "phone": "+1 555 0123"}
]
```

```json cookbook:output
[
  {"email": "831740710d6a8225c6ad8e71610353afdfcf9f6a3caa448dc11ab17a513081c2", "name": "Samuel Gonzalez", "phone": "*******0100"},
  {"email": "831740710d6a8225c6ad8e71610353afdfcf9f6a3caa448dc11ab17a513081c2", "name": "Stephen Mccarthy", "phone": "*******0199"},
  {"email": "40f27281a6f2d75f9690f415970debe57e538178a2ef93d532ee09f0fb0c90da", "name": "Samuel Gonzalez", "phone": "*******0123"}
]
```

## Masking personal data

Hash an email with a salt (keep the salt out of the file with `${env:...}` or `spec_vars`),
show only the last digits of a phone number, drop a national ID, keep only the year of a
birth date, and replace a card number with a keyed token that is stable across runs. A
`when` masks a column only on some rows.

```yaml cookbook:spec
version: 1
streams:
  customers:
    columns:
      email: {transform: {hash: {salt: "${salt}"}}}
      phone: {transform: {mask: {keep_last: 4}}}
      national_id: {transform: set_null}
      birth_date: {type: date, transform: [cast, redact_date]}
      card: {transform: {tokenize: "${token_key}"}}
      country: {type: string}
      city: {type: string, transform: {mask_hidden: "***"}, when: "country == 'DE'"}
```

```json cookbook:settings
{"spec_vars": {"salt": "pepper", "token_key": "k-2026"}}
```

```json cookbook:input
[
  {"email": "ann@example.com", "phone": "+1 555 0100", "national_id": "123-45-6789",
   "birth_date": "1990-07-04", "card": "4111111111111111", "country": "DE", "city": "Berlin"},
  {"email": "bob@example.com", "phone": "+1 555 0199", "national_id": "987-65-4321",
   "birth_date": "1985-12-31", "card": "4111111111111111", "country": "US", "city": "Austin"}
]
```

```json cookbook:output
[
  {"email": "831740710d6a8225c6ad8e71610353afdfcf9f6a3caa448dc11ab17a513081c2", "phone": "*******0100", "national_id": null, "birth_date": "1990-01-01", "card": "ae2f4debe1d2b4d9d79a4b89147c674db6fca8990e5c1d7911c67ca551961083", "country": "DE", "city": "***"},
  {"email": "40f27281a6f2d75f9690f415970debe57e538178a2ef93d532ee09f0fb0c90da", "phone": "*******0199", "national_id": null, "birth_date": "1985-01-01", "card": "ae2f4debe1d2b4d9d79a4b89147c674db6fca8990e5c1d7911c67ca551961083", "country": "US", "city": "Austin"}
]
```

## Derived columns and a filter

A column can be computed from others, by their conformed names and typed values. The filter
drops the rows where it is false; it sees the same names.

```yaml cookbook:spec
version: 1
streams:
  order_lines:
    filter: total > 0
    columns:
      Qty: {type: int32}
      Price: {type: "decimal(10,2)"}
      total: {type: "decimal(12,2)", expr: qty * price}
      size: {type: string, expr: "'bulk' if qty >= 100 else 'retail'"}
```

```json cookbook:input
[
  {"Qty": "3", "Price": "2.50"},
  {"Qty": "0", "Price": "9.99"},
  {"Qty": "120", "Price": "1.10"}
]
```

```json cookbook:output
[
  {"qty": 3, "price": "2.50", "total": "7.50", "size": "retail"},
  {"qty": 120, "price": "1.10", "total": "132.00", "size": "bulk"}
]
```

## Nested objects: JSON text, flattened or typed

An object property lands one of three ways. By default (`nested: json`) it is one column of
JSON text, which every target can store. `flatten: true` turns its members into columns
named `parent__member`; `nested: flatten` does that for every undeclared object, and a
column's `flatten: false` opts out. A declared `struct<...>` type keeps it an object, with
typed members; members are named as the tap names them (`Score`) and land conformed
(`score`).

`naming.collapse` turns `__` into `_` by default, so the flattened names below would be
`billing_city`; `collapse: false` keeps the separator, as the Singer SDK's flattening does.

```yaml cookbook:spec
version: 1
defaults: {naming: {collapse: false}}
streams:
  users:
    columns:
      billing: {flatten: true}
      meta: {type: "struct<source: string, Score: int32>"}
```

```json cookbook:schema
{"id": {"type": "string"},
 "address": {"type": ["object", "null"], "properties": {"city": {"type": "string"}}},
 "billing": {"type": ["object", "null"], "properties": {"city": {"type": "string"},
                                                        "zip": {"type": "string"}}},
 "meta": {"type": ["object", "null"], "properties": {"source": {"type": "string"},
                                                     "Score": {"type": "string"}}}}
```

```json cookbook:input
[
  {"id": "1", "address": {"city": "Lyon"}, "billing": {"city": "Paris", "zip": "75001"},
   "meta": {"source": "web", "Score": "7"}}
]
```

```json cookbook:output
[
  {"id": "1", "address": "{\"city\": \"Lyon\"}", "billing__city": "Paris", "billing__zip": "75001", "meta": {"source": "web", "score": 7}}
]
```

The flattened columns follow the tap's schema, so they change when it does. To keep them
fixed, declare a shape, as in the next recipe.

## Nested JSON with a declared shape

Declare the shape of a nested object and flatten it: the columns and their types come from
the shape, so the output does not change when the tap's schema drifts. (`collapse: false`
keeps the `__` separator, as above.) A member's `default`
says how a missing or empty value lands, and members the shape does not declare are dropped
(and counted in the metrics).

```yaml cookbook:spec
version: 1
defaults: {naming: {collapse: false}}
streams:
  users:
    columns:
      profile:
        flatten: true
        shape:
          type: object
          properties:
            name: {type: string}
            tags: {type: array, items: {type: string}, default: []}
            prefs: {type: object, default: {}}
```

```json cookbook:schema
{"id": {"type": "string"}, "profile": {"type": "object"}}
```

```json cookbook:input
[
  {"id": "1", "profile": {"name": "Ann", "tags": ["vip"], "prefs": {"lang": "en"}}},
  {"id": "2", "profile": {"name": "Bob", "tags": [], "unknown": true}},
  {"id": "3"}
]
```

```json cookbook:output
[
  {"id": "1", "profile__name": "Ann", "profile__tags": ["vip"], "profile__prefs": "{\"lang\": \"en\"}"},
  {"id": "2", "profile__name": "Bob", "profile__tags": [], "profile__prefs": "{}"},
  {"id": "3", "profile__name": null, "profile__tags": [], "profile__prefs": "{}"}
]
```

## Parquet BATCH files

When a tap sends BATCH messages (parquet files listed in a manifest), map-conform reads each
file, conforms every row with the same plan as RECORDs, and writes a new parquet file with
the declared types (decimals as `decimal128`, dates as `date32`, UUIDs as the parquet UUID
type), then sends a BATCH message listing the new files. The target must read BATCH too, and
reach the files: set `batch_output.storage.root` to a shared location (`s3://...` with the
`s3` extra, and `batch_output.storage.params` for credentials). For a target that does not
read BATCH, `batch_output.mode: record` sends RECORD messages instead.

Below, the output is the rows read back from the new parquet file. Plain numbers, ISO dates
and trimming run on whole columns with Arrow; the rest (`$12.00`, the US date, the braced
UUID) runs row by row, with the same result. The log says which engine each stream's files
ran on and why; `defaults.engine: row` runs everything row by row, the reference to compare
against if a result looks wrong.

```yaml cookbook:spec
version: 1
streams:
  orders:
    columns:
      Order ID: {name: order_id, type: int64}
      Amount: {type: "decimal(12,2)"}
      Ordered: {type: date, parse: {formats: ["%m/%d/%Y", iso]}}
      Tracking: {type: uuid}
```

```json cookbook:parquet
[
  {"Order ID": "1001", "Amount": "1234.5", "Ordered": "2026-03-14",
   "Tracking": "{0F8FAD5B-D9CB-469F-A165-70867728950E}"},
  {"Order ID": "1002", "Amount": "$12.00", "Ordered": "03/15/2026", "Tracking": null}
]
```

```json cookbook:output
[
  {"order_id": 1001, "amount": "1234.50", "ordered": "2026-03-14", "tracking": "0f8fad5b-d9cb-469f-a165-70867728950e"},
  {"order_id": 1002, "amount": "12.00", "ordered": "2026-03-15", "tracking": null}
]
```

## The `_sdc_*` columns

With `add_record_metadata: true`, map-conform adds the Singer SDK's seven metadata columns to
SCHEMA, RECORD and BATCH output, with the SDK's values: `_sdc_extracted_at` (the message's
`time_extracted`, so null when the tap sends none), `_sdc_received_at`, `_sdc_batched_at`
(a BATCH file's modification time; the mapper's start time for RECORDs),
`_sdc_deleted_at` (the tap's own, if it sends one), `_sdc_sequence`, `_sdc_table_version`
and `_sdc_sync_started_at`.

**If they are missing in the target:**

1. map-conform must add them. Set `add_record_metadata: true` in the mapping's config, or in
   the spec's `defaults` or on a stream. A stream rule wins over the spec's `defaults`,
   which win over the plugin setting; the default is off. Without it, a tap's own `_sdc_*`
   properties are left out too, as SDK targets leave them out.
1. The target must keep them. A Singer SDK target strips every `_sdc_*` column unless *its*
   config also has `add_record_metadata: true` (it then overwrites them with near-identical
   values of its own).
1. `map-conform doctor` (run in the Meltano project) checks both: it reports each loader
   that runs after a mapping that adds the columns but would strip them.

```yaml
plugins:
  mappers:
  - name: map-conform
    mappings:
    - name: conform
      config: {spec_path: conform.yml, add_record_metadata: true}
  loaders:
  - name: target-postgres
    config: {add_record_metadata: true}
```

## Moving from SDK stream maps

The settings of meltano-map-transformer (`stream_maps`, `stream_map_config`,
`faker_config`, `flattening_*`) work unchanged in a map-conform mapping: they are translated
into a spec at start-up. Move them over as they are:

```yaml
# before                                    # after
mappers:                                    mappers:
- name: meltano-map-transformer             - name: map-conform
  variant: meltano                            namespace: map_conform
  pip_url: meltano-map-transformer            pip_url: map-conform
  mappings:                                   mappings:
  - name: hash-emails                         - name: hash-emails
    config:                                     config:
      stream_maps:                                stream_maps:
        customers:                                  customers:
          email_hash: md5(email)                      email_hash: md5(email)
          email: __NULL__                             email: __NULL__
```

With `stream_maps` set, defaults that keep the old output apply unless the spec sets them:
the SDK's names (`naming: sdk`, the names an SDK SQL target creates), stream names kept as
they are, nested objects kept, and no trimming or null tokens. The output still differs
from meltano-map-transformer's on purpose:

| meltano-map-transformer | map-conform |
| -- | -- |
| Timestamps as the tap sent them | Canonical UTC, `2026-03-14T09:00:00.000000Z` |
| Tap numbers as JSON numbers | Exact decimal strings with `x-singer.decimal` in the SCHEMA |
| A value with no single type (an untyped object, a `oneOf`) as it is | JSON text |
| Names as the tap sent them, for the target to rename | Already the names an SDK SQL target creates (`user.id` is `user_id`) |
| SCHEMA as the tap sent it | Canonical types, integer bounds, `x-sql-datatype` hints |
| A record leaves out properties the tap left out | Every column in every record, null when missing |
| An expression error crashes the run | It follows `on_error`, with the stream, column and row |
| `time_extracted` replaced by now, `bookmark_properties` dropped | Both kept |
| BATCH messages crash the run | BATCH conformed |

`map-conform spec import --stream-maps config.json > conform.yml` writes the translation as
a native spec, with the types the SDK would infer written out (add `--catalog` for the
tap's), so you can switch to `spec_path` and use the rest of the spec. A test checks that
the imported spec gives the same output as the stream maps.

```yaml cookbook:spec
version: 1
```

```json cookbook:settings
{"stream_maps": {"customers": {"email_hash": "md5(email)", "domain": "email.split('@')[1]",
                               "email": null}}}
```

```json cookbook:input
[{"id": "1", "email": "ann@example.com"}]
```

```json cookbook:output
[
  {"id": "1", "email_hash": "257c57037d384ae37ea27a07e8a01665", "domain": "example.com"}
]
```
