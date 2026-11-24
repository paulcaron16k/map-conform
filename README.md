# map-conform

[![PyPI](https://img.shields.io/pypi/v/map-conform)](https://pypi.org/project/map-conform/)
[![Python](https://img.shields.io/pypi/pyversions/map-conform)](https://pypi.org/project/map-conform/)
[![Test](https://github.com/paulcaron16k/map-conform/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/paulcaron16k/map-conform/actions/workflows/test.yml)
[![License](https://img.shields.io/pypi/l/map-conform)](https://github.com/paulcaron16k/map-conform/blob/main/LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

A Singer/Meltano **inline mapper** that makes data *land clean*. It sits between any tap and
any target and, once, upstream:

- **casts to declared types**, never guessed: exact decimals, dates, timestamps in UTC,
  booleans, UUIDs, JSON, structs and lists;
- **cleans values on the way**: currency symbols, thousands separators (US, European and
  Swiss), accounting negatives, percentages, null tokens (`N/A`, `#N/A`, `-`), spreadsheet
  serial dates, epoch times, time zones and DST, yes/no words;
- **conforms names** of streams, columns and nested members so every target accepts them:
  snake_case, ASCII, length limits, reserved words, collision checks;
- **masks personal data**: hashes, keyed tokens, partial masks, redacted dates, fake values,
  nulls, with conditions and nested paths;
- **computes columns and filters rows** with a safe expression language, macros and UDFs;
- **sets bad values aside** instead of crashing, if you ask: null them, keep them, or reject
  the row to a file you can replay;
- **conforms BATCH files** (parquet or JSONL), with Arrow kernels for parquet and optionally
  polars;
- **adds the `_sdc_*` metadata columns** with Singer SDK semantics, when asked;
- **accepts SDK `stream_maps` settings unchanged**, so meltano-map-transformer projects move
  over without changes.

Targets can then rely on the [Clean-Landing Contract](https://github.com/paulcaron16k/map-conform/blob/main/wiki/concepts/clean-landing-contract.md):
what every record, SCHEMA and BATCH file from map-conform guarantees, so a target writes data
instead of cleaning it. Target maintainers can paste its
[reviewer snippet](https://github.com/paulcaron16k/map-conform/blob/main/wiki/concepts/clean-landing-contract.md#7-reviewer-instruction-for-target-repos)
into their review rules, so reviewers stop asking for cleanup the mapper already did.

## Why

Every Singer target cleans data a little differently, so the same CSV lands with different
values depending on where it goes, and BATCH data skips the SDK's per-record cleanup
altogether. The common fallback, a cleanup layer in dbt, is SQL only, needs macros that work
across every warehouse a project uses, and runs after the raw data, mess and personal data
included, has landed. map-conform does the cleanup once, in Python, before anything is
stored: exact decimals, real date parsing, Unicode-aware names and masking, for every target.

Compared with meltano-map-transformer (SDK stream maps), which renames, filters and computes
columns but takes types from expression prefixes and crashes on a bad value, map-conform
declares each column's type, cleans and casts the value, handles bad values by policy, and
conforms BATCH messages. Stream maps keep working ([migration](https://github.com/paulcaron16k/map-conform/blob/main/docs/cookbook.md#moving-from-sdk-stream-maps)).

## Install

```bash
pip install map-conform                  # the mapper
pip install 'map-conform[faker]'         # + fake data for masking
pip install 'map-conform[polars]'        # + the polars engine (regex, strptime formats)
pip install 'map-conform[s3]'            # + BATCH files on S3
```

Python 3.11 to 3.14.

## Use it in Meltano

map-conform is not on Meltano Hub yet, so add it as a custom mapper (`namespace` is what
makes it custom):

```yaml
plugins:
  mappers:
  - name: map-conform
    namespace: map_conform
    pip_url: map-conform
    executable: map-conform
    mappings:
    - name: conform
      config:
        spec_path: conform.yml
        add_record_metadata: true     # add the _sdc_* columns
  loaders:
  - name: target-postgres
    config:
      add_record_metadata: true       # so the SDK target keeps them
```

```bash
meltano run tap-csv conform target-postgres
```

Any setting can go in the mapping's `config`. To set them with `meltano config` or
environment variables, declare them under the plugin's `settings:` too;
[plugin-definition.yml](https://github.com/paulcaron16k/map-conform/blob/main/plugin-definition.yml)
lists every one, and `map-conform --about` describes them.

A spec (`conform.yml`) declares what the data should look like:

```yaml
version: 1
defaults:
  on_error: reject            # bad rows go to ./.map-conform/rejects, the run goes on
streams:
  Orders Export:
    key_properties: [order_id]
    columns:
      Order ID: {name: order_id, type: int64, nullable: false}
      Amount ($): {type: "decimal(12,2)", parse: {parens_negative: true}}
      Order Date: {type: date, parse: {formats: ["%m/%d/%Y", iso, excel_serial]}}
      Customer Email: {transform: {hash: {salt: "${env:EMAIL_SALT}"}}}
```

`"$1,234.50"` lands as `1234.50`, `"(12.00)"` as `-12.00`, `"03/14/2026"` and `46095` as
`2026-03-14`, `Order ID` as `order_id` and `Amount ($)` as `amount`; the stream lands as
`orders_export` (`stream: {name: preserve}` keeps tap stream names). Columns the spec does
not mention are conformed from the tap's SCHEMA. Without a spec at all, map-conform conforms
names and types with its defaults.

Without `on_error`, a value that cannot be cast stops the run with the stream, column, row
and value: nothing lands wrong silently. Check a spec before running it with
`map-conform spec validate conform.yml`, and a project with `map-conform doctor`.

## Documentation

- [Cookbook](https://github.com/paulcaron16k/map-conform/blob/main/docs/cookbook.md):
  CSV, spreadsheet and European exports, bad values and rejects, epoch times, hashes and
  fake names, masking, derived columns, parquet BATCH files, nested objects and declared
  shapes, the `_sdc_*` columns, and moving from stream maps. Every example is run by the
  test suite.
- [Spec reference](https://github.com/paulcaron16k/map-conform/blob/main/docs/spec-reference.md):
  every setting, spec key, `parse` option, step and function, generated from the code.
- [Detailed design](https://github.com/paulcaron16k/map-conform/blob/main/docs/detailed-design.md): how each feature behaves, and why.
- [Clean-Landing Contract](https://github.com/paulcaron16k/map-conform/blob/main/wiki/concepts/clean-landing-contract.md): what a target may assume, and a reviewer snippet for target repos.
- The project's knowledge base is in [wiki/](https://github.com/paulcaron16k/map-conform/blob/main/wiki/index.md).

## Command line

```bash
map-conform --config config.json < tap-output.jsonl      # the mapper (Singer SDK CLI)
map-conform spec validate conform.yml --catalog catalog.json
map-conform spec explain conform.yml --stream "Orders Export" --catalog catalog.json
map-conform spec import --catalog catalog.json > conform.yml      # draft a spec
map-conform spec import --stream-maps config.json > conform.yml   # from SDK stream maps
map-conform spec export conform.yml --zamboni table-config.json --catalog catalog.json
map-conform spec schema > conform.schema.json                     # for editor completion
map-conform doctor --meltano-yml meltano.yml
map-conform functions                                             # steps, casts, functions
```

A catalog is what the tap discovers (`meltano invoke tap-csv --discover > catalog.json`);
with it, `spec validate` and `spec explain` check the spec against the tap's real columns
and types. `spec export --zamboni` writes each column's type into a
[Zamboni](https://github.com/paulcaron16k/Zamboni) table-config, the layout and
maintenance spec of its Iceberg tables; skip it if you do not use Zamboni.

## Development

```bash
uv sync --all-groups
uv run pytest
```

[CONTRIBUTING.md](https://github.com/paulcaron16k/map-conform/blob/main/CONTRIBUTING.md) has
the workflow, and the
[dev environment runbook](https://github.com/paulcaron16k/map-conform/blob/main/wiki/runbooks/dev-environment.md)
the checks that make a change done, the generated files, and checklists for adding a step,
an option, a setting or a type. Releases follow the
[release runbook](https://github.com/paulcaron16k/map-conform/blob/main/wiki/runbooks/release.md).
Security problems: [SECURITY.md](https://github.com/paulcaron16k/map-conform/blob/main/SECURITY.md).

## Licence

Apache-2.0
