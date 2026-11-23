# Example: tap-csv → map-conform → target-ducklake

A small Meltano project that loads a messy spreadsheet export (`data/orders.csv`: currency
symbols, accounting negatives, percentages, yes/no words, US dates and Excel serial dates,
braced UUIDs, padded names) into a local [DuckLake](https://ducklake.select/), cleaned on
the way by map-conform with the spec in `conform.yml`. CI runs it on every change.

```bash
cd examples
meltano install            # tap-csv, map-conform (from this checkout) and target-ducklake
mkdir -p output            # where the lake goes (SQLite catalog and data files)
meltano run load           # tap-csv conform target-ducklake
map-conform doctor         # checks the project, e.g. that the target keeps _sdc_* columns
```

The lake is in `output/`. Query it with DuckDB:

```sql
INSTALL ducklake; INSTALL sqlite; LOAD ducklake;   -- the extensions download once
ATTACH 'ducklake:sqlite:output/catalog.sqlite' AS lake (DATA_PATH 'output/data/');
SELECT order_id, order_date, amount, discount, paid, tracking_uuid FROM lake.raw.orders;
```

`order_id` is a BIGINT, `amount` a DECIMAL(12,2) (`$1,234.50` → 1234.50, `(250.00)` →
-250.00), `discount` a fraction (`10%` → 0.1000), `order_date` a DATE whatever the source
format, and the column names are snake_case.

Eleven of the twelve rows land. Row 10's amount is `abc`, so under `on_error: reject` it is
set aside in `.map-conform/rejects/orders/<run id>.jsonl`, with the column, the error and the
raw record, instead of failing the run.

## What is here

| Path | What |
| -- | -- |
| `meltano.yml` | The project: tap-csv, map-conform (installed from this checkout, `pip_url: ..`) and target-ducklake, and the `load` job |
| `conform.yml` | The conform spec |
| `data/orders.csv` | The messy input |
| `check_lake.py` | The check CI runs after `meltano run load`: row count, column types and values in the lake |
| `plugins/` | Meltano's lock files for the plugins |
| `output/`, `.map-conform/`, `.meltano/` | Made by a run (the lake, rejects, Meltano's state); not committed |

To adapt it, point `spec_path` at your own spec, replace tap-csv with your tap, and replace
target-ducklake with your target. Keep `add_record_metadata: true` on an SDK target, and run
`map-conform doctor` to check.
