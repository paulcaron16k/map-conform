"""The shared fixtures are current, well-formed and mutually consistent."""

from __future__ import annotations

import csv
import gzip
import json
import re
from pathlib import Path
from typing import Any

import jsonschema
import pyarrow.parquet as pq
import pytest
from singer_sdk.singerlib import Catalog

from tests.fixtures import generate as gen
from tests.fixtures.paths import FIXTURES, messages

CORPUS = FIXTURES / "corpus"
CAST_TABLES = ["numeric.csv", "temporal.csv", "boolean.csv", "uuid.csv", "text.csv"]
DERIVED_DIRS = ["sources", "streams", "catalogs", "batch"]
CTYPE = re.compile(
    r"^(boolean|int(16|32|64)|float(32|64)|decimal\(\d+,\d+\)|string(\(\d+\))?"
    r"|date|time|timestamp|timestamptz|uuid|binary|json)$"
)
MIN_TEMPORAL_FORMATS = 25
CONFORMED_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _rows(name: str) -> list[dict[str, str]]:
    with (CORPUS / name).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_derived_fixtures_are_current(tmp_path: Path) -> None:
    """Regenerating changes nothing; parquet and gzip are compared by content, not bytes."""
    written = gen.generate(tmp_path)
    stale = []
    for fresh in written:
        rel = fresh.relative_to(tmp_path)
        committed = FIXTURES / rel
        if not committed.exists():
            stale.append(f"{rel}: missing")
        elif fresh.suffix == ".parquet":
            if not pq.read_table(fresh).equals(pq.read_table(committed), check_metadata=True):
                stale.append(f"{rel}: content differs")
        elif fresh.suffix == ".gz":
            # Deflate output depends on the zlib build, so compare what decompresses.
            if gzip.decompress(fresh.read_bytes()) != gzip.decompress(committed.read_bytes()):
                stale.append(f"{rel}: content differs")
        elif fresh.read_bytes() != committed.read_bytes():
            stale.append(f"{rel}: bytes differ")
    expected = {p.relative_to(tmp_path) for p in written}
    extra = [
        str(p.relative_to(FIXTURES))
        for d in DERIVED_DIRS
        for p in (FIXTURES / d).rglob("*")
        if p.is_file() and p.relative_to(FIXTURES) not in expected
    ]
    assert not stale, f"run `uv run python -m tests.fixtures.generate`: {stale}"
    assert not extra, f"files no generator writes: {extra}"


@pytest.mark.parametrize("table", CAST_TABLES)
def test_cast_table_is_well_formed(table: str) -> None:
    """Each case names a CType, valid kwargs and an expected value or marker."""
    rows = _rows(table)
    assert rows, table
    assert list(rows[0]) == ["case", "type", "input", "kwargs", "expected", "note"]
    for row in rows:
        assert CTYPE.match(row["type"]), row
        if row["kwargs"]:
            assert isinstance(json.loads(row["kwargs"]), dict), row
        if row["expected"] == "":
            assert row["type"].startswith("string"), f"'' is only a string result: {row}"


def test_case_ids_are_unique_across_tables() -> None:
    """Case ids double as pytest ids, so they are unique over the whole corpus."""
    ids = [row["case"] for table in [*CAST_TABLES, "names.csv"] for row in _rows(table)]
    assert len(ids) == len(set(ids)), sorted({i for i in ids if ids.count(i) > 1})


def test_every_outcome_kind_is_covered() -> None:
    """Each cast table has successes, and the corpus covers errors and nulls."""
    outcomes = {
        table: {
            r["expected"] if r["expected"] in {"!error", "!null"} else "value" for r in _rows(table)
        }
        for table in CAST_TABLES
    }
    for table, kinds in outcomes.items():
        assert kinds == {"value", "!error", "!null"}, (table, kinds)


def test_temporal_corpus_covers_25_formats() -> None:
    """The design promises dates in 25+ formats (detailed design §14)."""
    formats = {
        f
        for r in _rows("temporal.csv")
        if r["kwargs"]
        for f in json.loads(r["kwargs"]).get("formats", [])
    }
    shapes = {r["input"] for r in _rows("temporal.csv") if not r["kwargs"]}
    assert len(formats) + len(shapes) >= MIN_TEMPORAL_FORMATS, (formats, shapes)


def test_names_table_outputs_are_conformed() -> None:
    """Golden outputs obey the conformed-name grammar and are fixed points."""
    rows = _rows("names.csv")
    assert list(rows[0]) == ["case", "source", "expected", "note"]
    for row in rows:
        assert CONFORMED_NAME.match(row["expected"]), row
    assert any(r["source"] == r["expected"] for r in rows), "an idempotence case"


def test_source_csv_is_a_spreadsheet_export() -> None:
    """BOM, CRLF and an embedded newline survive, and it parses to the generator's rows."""
    raw = (FIXTURES / "sources" / "orders_export.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in raw
    with (FIXTURES / "sources" / "orders_export.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows == [gen.ORDERS_HEADER, *gen.ORDERS_ROWS]
    assert any("\n" in cell for row in rows for cell in row)


STREAMS = sorted(p.name for p in (FIXTURES / "streams").glob("*.jsonl"))


@pytest.mark.parametrize("name", STREAMS)
def test_singer_stream_is_valid(name: str) -> None:
    """SCHEMA comes first, RECORDs validate against it and BATCH manifests resolve."""
    schemas: dict[str, Any] = {}
    stream = messages(name)
    assert stream[0]["type"] == "SCHEMA"
    for message in stream:
        kind = message["type"]
        if kind == "SCHEMA":
            jsonschema.Draft7Validator.check_schema(message["schema"])
            schemas[message["stream"]] = jsonschema.Draft7Validator(message["schema"])
        elif kind == "RECORD":
            schemas[message["stream"]].validate(message["record"])
        elif kind == "BATCH":
            assert message["stream"] in schemas
            for uri in message["manifest"]:
                assert uri.startswith("file://"), uri
                assert Path(uri.removeprefix("file://")).is_file(), uri


def _records(name: str) -> list[dict[str, Any]]:
    return [m["record"] for m in messages(name) if m["type"] == "RECORD"]


def test_batch_files_hold_the_record_stream_rows() -> None:
    """RECORD and BATCH fixtures carry the same rows, so parity tests compare like with like."""
    records = _records("orders_export.singer.jsonl")
    parquet_rows = [
        row
        for part in ("0001", "0002")
        for row in pq.read_table(FIXTURES / "batch" / f"orders_export-{part}.parquet").to_pylist()
    ]
    assert parquet_rows == records
    with gzip.open(FIXTURES / "batch" / "orders_export-0001.jsonl.gz", "rt", encoding="utf-8") as f:
        assert [json.loads(line) for line in f] == records[:6]
    inventory = pq.read_table(FIXTURES / "batch" / "inventory_xlsx-0001.parquet").to_pylist()
    assert [r["SKU"] for r in inventory] == [
        r["SKU"] for r in _records("inventory_xlsx.singer.jsonl")
    ]


@pytest.mark.parametrize(
    "path", sorted((FIXTURES / "catalogs").glob("*.catalog.json")), ids=lambda p: p.name
)
def test_catalog_loads_with_the_sdk(path: Path) -> None:
    """Each catalog is one the Singer SDK accepts."""
    catalog = Catalog.from_dict(json.loads(path.read_text(encoding="utf-8")))
    assert len(catalog) == 1


def test_typed_expectations_cover_the_catalog() -> None:
    """Every typed-catalog property has an expected CType, and only those do."""
    catalog = json.loads((FIXTURES / "catalogs" / "typed.catalog.json").read_text())
    expected = json.loads((FIXTURES / "catalogs" / "typed.expected.json").read_text())
    properties = catalog["streams"][0]["schema"]["properties"]
    assert set(expected["nested_json"]) == set(properties)
    assert set(expected["nested_keep_overrides"]) <= set(properties)
    for ctype in expected["nested_json"].values():
        assert CTYPE.match(ctype), ctype
