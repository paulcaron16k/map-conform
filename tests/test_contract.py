"""The Clean-Landing Contract, checked on the mapper's own output (wiki/concepts §1-§4).

The messy fixture streams run through the mapper with a full spec and with no spec at all,
and every SCHEMA and RECORD it writes is checked against the contract's guarantees: legal,
unique names; one JSON type per property; records that validate against their SCHEMA; no
empty string outside string columns; every declared column present.
"""

from __future__ import annotations

import io
import json
import re
from typing import Any

import jsonschema
import pytest

from map_conform.mapper import MapConformMapper
from tests.fixtures.paths import messages

NAME = re.compile(r"^[a-z_][a-z0-9_]*$")
SPEC: dict[str, Any] = {
    "version": 1,
    "defaults": {"on_error": "null", "add_record_metadata": True},
    "streams": {
        "Orders Export": {
            "columns": {
                "Order ID": {"name": "order_id", "type": "int64", "nullable": False},
                "Order Date": {"type": "date", "parse": {"formats": ["%m/%d/%Y", "iso",
                                                                     "excel_serial"]}},
                "Amount ($)": {"type": "decimal(12,2)", "parse": {"parens_negative": True,
                                                                  "trailing_minus": True}},
                "Discount %": {"type": "decimal(6,4)", "parse": {"percent": "divide"}},
                "Paid?": {"type": "boolean"},
                "Qty.": {"type": "int32"},
                "Created At (UTC)": {"type": "timestamptz"},
                "Tracking UUID": {"type": "uuid"},
            }
        }
    },
}  # fmt: skip
CASES = [
    ("orders_export.singer.jsonl", SPEC),
    ("orders_export.singer.jsonl", None),
    ("inventory_xlsx.singer.jsonl", None),
]


def output(name: str, spec: dict[str, Any] | None, capsys: pytest.CaptureFixture[str]) -> list[Any]:
    """The messages the mapper writes for a fixture stream."""
    mapper = MapConformMapper(config={"spec": spec} if spec else {})
    capsys.readouterr()
    text = "".join(json.dumps(m) + "\n" for m in messages(name) if m["type"] != "BATCH")
    mapper.listen(io.StringIO(text))
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def _non_null(prop: dict[str, Any]) -> list[str]:
    types = prop["type"] if isinstance(prop["type"], list) else [prop["type"]]
    return [t for t in types if t != "null"]


@pytest.mark.parametrize(("name", "spec"), CASES, ids=["spec", "no-spec", "xlsx-no-spec"])
def test_output_keeps_the_contract(
    name: str, spec: dict[str, Any] | None, capsys: pytest.CaptureFixture[str]
) -> None:
    """Names, SCHEMA shape, RECORD validity, no stray empty strings, every column present."""
    out = output(name, spec, capsys)
    schemas = {m["stream"]: m for m in out if m["type"] == "SCHEMA"}
    records = [m for m in out if m["type"] == "RECORD"]
    assert schemas
    assert records
    for stream, message in schemas.items():
        assert NAME.match(stream), stream
        properties = message["schema"]["properties"]
        assert all(NAME.match(p) for p in properties), list(properties)
        assert len({p.casefold() for p in properties}) == len(properties)
        assert set(message["key_properties"]) <= set(properties)
        for prop in properties.values():
            assert not {"anyOf", "oneOf", "allOf", "$ref"} & set(prop), prop
            assert len(_non_null(prop)) == 1, prop
        jsonschema.Draft7Validator.check_schema(message["schema"])
    for message in records:
        schema = schemas[message["stream"]]["schema"]
        record = message["record"]
        jsonschema.Draft7Validator(schema).validate(record)
        assert set(record) == set(schema["properties"])
        for key, value in record.items():
            prop = schema["properties"][key]
            if value == "":
                assert _non_null(prop) == ["string"], (key, prop)
                assert "format" not in prop, (key, prop)


def test_metadata_columns_follow_the_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """With add_record_metadata the seven _sdc_* columns are declared; without it, none."""
    with_flag = output("orders_export.singer.jsonl", SPEC, capsys)
    without = output("orders_export.singer.jsonl", None, capsys)
    declared = next(m for m in with_flag if m["type"] == "SCHEMA")["schema"]["properties"]
    plain = next(m for m in without if m["type"] == "SCHEMA")["schema"]["properties"]
    assert len([p for p in declared if p.startswith("_sdc_")]) == 7  # noqa: PLR2004
    assert not [p for p in plain if p.startswith("_sdc_")]
