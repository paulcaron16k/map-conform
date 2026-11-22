# Test fixtures

Shared inputs for the cast, naming, parity, contract and end-to-end tests. Two kinds:

- **Hand-authored case tables** in `corpus/`, the specification each builtin is tested
  against. Edit them directly.

- **Generated files** in `sources/`, `streams/`, `catalogs/` and `batch/`. They are built from
  the data in [`generate.py`](generate.py). Never edit them by hand; change `generate.py` and
  run:

  ```bash
  uv run python -m tests.fixtures.generate
  ```

  `tests/test_fixtures.py` regenerates into a temporary directory and fails when a committed
  file is stale or when a file has no generator.

## `corpus/`: cast and naming cases

Each cast table has the columns `case, type, input, kwargs, expected, note`.

| Column | Meaning |
| -- | -- |
| `case` | Unique id across the whole corpus; used as the pytest id |
| `type` | The declared CType, e.g. `int64`, `decimal(10,2)`, `timestamptz`, `string(5)` |
| `input` | The raw string value as a tap delivers it. An empty cell is the empty string |
| `kwargs` | JSON object of cast kwargs, or empty for the spec defaults (design §3.2) |
| `expected` | The value on the wire, `!null` for JSON null, or `!error` for a cast failure (handled by `on_error`) |
| `note` | Why the case exists |

| Table | Covers |
| -- | -- |
| [`numeric.csv`](corpus/numeric.csv) | int16/32/64, float64 and decimal: signs, thousands groups, currency symbols and ISO codes, locales, parentheses, trailing minus, percent, exponents, rounding modes, bounds, exact decimal rounding |
| [`temporal.csv`](corpus/temporal.csv) | 25+ input formats: lenient ISO, strptime patterns, RFC 2822, Excel serials (1900 and 1904 systems, the Lotus leap-year bug), epoch s/ms/us/ns and `epoch_auto`, time zones, DST ambiguity and gaps, sanity bounds |
| [`boolean.csv`](corpus/boolean.csv) | the default true/false words, case, numbers, custom lists, case sensitivity |
| [`uuid.csv`](corpus/uuid.csv) | braces, case, missing dashes, length, version checks |
| [`text.csv`](corpus/text.csv) | trimming (including NBSP), null tokens, empty strings, `maxLength` |
| [`names.csv`](corpus/names.csv) | name conformer golden cases (`case, source, expected, note`), including every example in design §5 |

Wire forms follow the [Clean-Landing Contract](../../wiki/concepts/clean-landing-contract.md)
§3. Where the contract leaves the fraction open, the corpus uses six digits
(`output_precision: us`): `timestamptz` is `YYYY-MM-DDTHH:MM:SS.ffffffZ`, `timestamp` is the
same without `Z`, and `time` is `HH:MM:SS.ffffff`. Two rules decided by the owner on 2026-11-22
(guidance §7, rows 19–20) are encoded here:

- Excel serial `60` (the Lotus 1900-02-29 that never existed) is an error, and serials below
  60 count from 1899-12-31.
- `half_up` rounds halves away from zero (`-12.5` → `-13`).

Expected values that depend on calendars and time zones were checked against the Python
standard library (`datetime.strptime`, `zoneinfo`, `email.utils`).

## `sources/`: raw files as a tap reads them

| File | What is messy |
| -- | -- |
| `orders_export.csv` | A spreadsheet saved as CSV: UTF-8 BOM, CRLF, a quoted cell with an embedded newline. Headers need conforming (`Amount ($)`, `customerID`, `Paid?`). Values mix date formats and Excel serials, use currency symbols, thousands separators, parentheses, percentages, null tokens (`-`, `#N/A`, `NULL`, `N/A`), padded strings, an NBSP, and one row of uncleanable values (`abc`, `maybe`, `next week`) |

`.gitattributes` marks it `-text`, and pre-commit's whitespace hooks skip the fixture data,
so the bytes are exact.

## `streams/`: Singer message streams

| File | Messages |
| -- | -- |
| `orders_export.singer.jsonl` | What tap-csv emits for `sources/orders_export.csv`: an all-string SCHEMA, 12 RECORDs and a STATE. The stream name `Orders Export` needs conforming |
| `inventory_xlsx.singer.jsonl` | What a spreadsheet (XLSX) tap emits: whole numbers as floats (`3.0`), dates as ISO text or raw serials (`46095.0`), float artefacts (`0.30000000000000004`), a mixed `["number","string"]` column, error cells as text |
| `orders_export.batch-parquet.singer.jsonl` | SCHEMA, one BATCH over two parquet files, STATE |
| `orders_export.batch-jsonl.singer.jsonl` | SCHEMA, one BATCH over a gzipped JSONL file, STATE |
| `inventory_xlsx.batch-parquet.singer.jsonl` | SCHEMA, one BATCH over a typed parquet file, STATE |

Every RECORD carries `version` and `time_extracted`. BATCH manifests contain the
placeholder `{FIXTURES}`. Load streams with `tests.fixtures.paths.messages(name)`, which
replaces it with this directory's absolute path.

## `batch/`: BATCH files

What an SDK tap writes: source column names and source types.

| File | Contents |
| -- | -- |
| `orders_export-0001.parquet`, `-0002.parquet` | Orders rows 1–6 and 7–12, all `string` columns, zstd |
| `orders_export-0001.jsonl.gz` | Orders rows 1–6 as gzipped JSONL (reproducible: no gzip mtime or name) |
| `inventory_xlsx-0001.parquet` | Inventory rows with float64, bool and string columns; the mixed `Weight (kg)` column is string, since Arrow needs one type |

The rows are identical to the RECORD streams, which `test_fixtures.py` checks, so RECORD and
BATCH parity tests compare like with like. Git sets file modification times at checkout.
Tests of `_sdc_batched_at` (the input file's mtime) set it with `os.utime` first.

## `catalogs/`: Singer catalogs

| File | Use |
| -- | -- |
| `orders_export.catalog.json`, `inventory_xlsx.catalog.json` | Catalogs for the two streams, with selection and key metadata |
| `typed.catalog.json` | One stream whose properties exercise every SCHEMA → CType rule in design §4: integer bounds, decimals, string formats, base64, `x-sql-datatype` hints, objects, arrays, `anyOf`, multiple types, untyped |
| `typed.expected.json` | The CType each `typed` property maps to with the defaults (`nested: json`), plus the overrides under `nested: keep` |
