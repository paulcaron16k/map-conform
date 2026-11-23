# map-conform

A Singer/Meltano **inline mapper** that makes data *land clean*. It sits between any tap and
any target and, once, upstream:

- **casts to declared types**, never guessed: exact decimals, dates, timestamps in UTC,
  booleans, UUIDs, JSON, structs and lists;
- **cleans values on the way**: currency symbols, thousands separators, accounting
  negatives, percentages, null tokens (`N/A`, `#N/A`, `-`), spreadsheet serial dates, epoch
  times, time zones and DST, yes/no words;
- **conforms names** so every target accepts them: snake_case, ASCII, length limits,
  reserved words, collision checks;
- **masks personal data**: hashes, keyed tokens, partial masks, redacted dates, nulls, with
  conditions and nested paths;
- **computes columns and filters rows** with a safe expression language, macros and UDFs;
- **conforms BATCH files** (parquet or JSONL) with a columnar Apache Arrow engine, and
  optionally polars;
- **adds the `_sdc_*` metadata columns** with Singer SDK semantics, when asked;
- **accepts SDK `stream_maps` settings unchanged**, so meltano-map-transformer projects move
  over without changes.

Targets can then rely on the [Clean-Landing Contract](https://github.com/paulcaron16k/map-conform/blob/main/wiki/concepts/clean-landing-contract.md)
instead of re-implementing cleanup.

## Install

```bash
pip install map-conform                  # the mapper
pip install 'map-conform[faker]'         # + fake data for masking
pip install 'map-conform[polars]'        # + the polars engine (regex, strptime formats)
pip install 'map-conform[s3]'            # + BATCH files on S3
```

Python 3.11 to 3.14.

## Use it in Meltano

```yaml
plugins:
  mappers:
  - name: map-conform
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
`2026-03-14`, and `Order ID` as `order_id`. Columns the spec does not mention are conformed
from the tap's SCHEMA. Without a spec at all, map-conform conforms names and types with its
defaults. `map-conform doctor` checks the project, including that targets keep the
`_sdc_*` columns.

## Documentation

- [Cookbook](https://github.com/paulcaron16k/map-conform/blob/main/docs/cookbook.md): CSV and spreadsheet exports, epoch times, masking, derived
  columns, nested JSON with declared shapes, moving from stream maps. Every example is
  tested.
- [Spec reference](https://github.com/paulcaron16k/map-conform/blob/main/docs/spec-reference.md): every setting, spec key, step and function,
  generated from the code.
- [Detailed design](https://github.com/paulcaron16k/map-conform/blob/main/docs/detailed-design.md): how each feature behaves, and why.
- [Clean-Landing Contract](https://github.com/paulcaron16k/map-conform/blob/main/wiki/concepts/clean-landing-contract.md): what a target may assume.
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
map-conform functions
```

## Development

```bash
uv sync --all-groups
uv run pytest                      # the suite, offline
uv run pytest -m e2e               # into a real target-jsonl (needs uvx and network)
uv run pytest -m bench tests/bench # throughput benchmarks and the regression gate
uv run ruff check . && uv run ruff format --check .
uv run mypy map_conform tests && uv run ty check
uvx --with tox-uv tox              # every supported Python, plus typing
uvx pre-commit install             # once: ruff, mypy, mdformat, typos, wiki frontmatter
```

After changing the spec model, regenerate the shipped schema and reference:
`uv run python -m map_conform.spec.jsonschema` and
`uv run python -m map_conform.spec.reference`.

## Licence

Apache-2.0
