# Changelog

All notable changes to map-conform are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Before 1.0, a minor version may change behaviour;
each such change is listed.

## [Unreleased]

### Fixed

- The default `pytest` run no longer needs the network: the e2e test is opt-in
  (`-m e2e`), and CI runs it in the test matrix.
- A `|` in a spec reference cell no longer splits its table row.
- `spec validate` compiles every plan, so a typo in a step or `parse` option, an unknown
  step or name, or a type mismatch fails validation rather than the run. Without
  `--catalog`, problems in a tap column with no declared type are warnings. It takes
  `--allow-python-udfs`, as `spec explain` does.
- A problem with a `parse` option is reported at `columns.<c>.parse.<key>`, not under
  `transform`.
- `map-conform functions` reported no step as vectorised. It now lists the engines that
  vectorise each step and cast (`engines`, `cast_engines` in `--json`), from the kernel
  tables themselves.

## [0.1.0] - 2026-11-23

The first release: a Singer/Meltano inline mapper that conforms names, types, values and
metadata so targets receive clean data.

### Added

- **Conform spec** (YAML or JSON, `spec_path` or inline): strict parsing with every problem
  reported at its path, `${var}` and `${env:NAME}` substitution, inheritance from
  `defaults` through stream globs to exact names, macros with parameters, and a generated
  JSON Schema (`map-conform spec schema`).
- **Types and casts** to declared canonical types: integers, floats, exact decimals,
  strings, booleans, dates, times, timestamps with and without zone, UUIDs, binary, JSON,
  structs and lists. The casts clean text on the way: currency, thousands separators,
  accounting negatives, percentages, locales, null tokens, Excel serial dates, epoch times,
  time zones with DST policies, yes/no words.
- **Name conforming**: snake_case with camelCase splitting, ASCII transliteration with a
  bundled table, reserved words of PostgreSQL, DuckDB and Snowflake, length limits with hash
  truncation, collision checks, nested member names, stream prefixes and aliases, and the
  `naming: sdk` preset matching the Singer SDK byte for byte.
- **Builtin steps** for text, numbers, temporals, privacy (hash, mask, set_null,
  redact_date, mask_number, mask_hidden, tokenize) and fake data (the `faker` extra).
- **Expressions**: a sandboxed Python subset compiled once per column, with a function
  library; `expr`, `case` and `when` steps; derived columns in dependency order; stream
  `filter`; `fields` for nested members; UDFs from installed packages or, opted in, from
  project modules.
- **Errors**: `on_error` (`raise`, `null`, `keep`, `reject`), a reject sink (JSONL or
  parquet), reject and null rate limits checked before each STATE, and per-stream metrics.
- **`_sdc_*` metadata columns** with Singer SDK semantics, when `add_record_metadata` is
  true.
- **BATCH**: parquet and JSONL manifests over fsspec, conformed into new files with the
  declared Arrow schema, or into RECORD messages; a columnar Arrow engine that gives exactly
  the row path's results, `case` lowering, and the `polars` engine (extra).
- **Flattening** with Singer SDK semantics, and from a declared JSON `shape` that keeps the
  output schema stable when the tap's schema drifts.
- **SDK compatibility**: `stream_maps`, `stream_map_config`, `faker_config` and
  `flattening_*` settings accepted unchanged, checked against the SDK's own mapper tests.
- **Tools**: `spec validate`, `spec explain`, `spec import` (from a catalog, Zamboni
  `columns` or SDK stream maps), `spec export --zamboni`, `doctor` and `functions`.
- **Docs**: README, a generated spec reference, and a cookbook whose examples are tested.
