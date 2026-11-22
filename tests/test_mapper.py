"""The mapper conforms SCHEMA and RECORD, passes STATE, renames ACTIVATE_VERSION (WBS 5.8)."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from singer_sdk.exceptions import ConfigValidationError

from map_conform.errors import ConformError
from map_conform.mapper import MapConformMapper

SCHEMA: dict[str, Any] = {
    "type": "SCHEMA",
    "stream": "Customer Orders",
    "schema": {
        "type": "object",
        "properties": {
            "Order ID": {"type": ["string", "null"]},
            "Amount": {"type": ["string", "null"]},
            "Updated At": {"type": ["string", "null"], "format": "date-time"},
        },
    },
    "key_properties": ["Order ID"],
    "bookmark_properties": ["Updated At"],
}
RECORD: dict[str, Any] = {
    "type": "RECORD",
    "stream": "Customer Orders",
    "record": {"Order ID": " 0042 ", "Amount": "$1,234.50", "Updated At": "2026-03-14 09:00"},
    "time_extracted": "2026-11-21T08:30:00.123456+05:30",
    "version": 1732170000000,
}
STATE: dict[str, Any] = {
    "type": "STATE",
    "value": {"bookmarks": {"Customer Orders": {"replication_key": "x"}}},
}
ACTIVATE_VERSION: dict[str, Any] = {
    "type": "ACTIVATE_VERSION",
    "stream": "Customer Orders",
    "version": 7,
}
SPEC: dict[str, Any] = {
    "version": 1,
    "defaults": {"stream": {"prefix": "raw_"}},
    "streams": {
        "Customer Orders": {
            "columns": {
                "Order ID": {"name": "order_id", "type": "int64", "nullable": False},
                "Amount": {"type": "decimal(12,2)"},
            }
        }
    },
}


def run_mapper(
    messages: list[dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
    spec: dict[str, Any] | None = None,
    **config: Any,
) -> list[dict[str, Any]]:
    """Feed messages through the mapper and return what it wrote."""
    mapper = MapConformMapper(config={"spec": spec or SPEC, **config})
    capsys.readouterr()
    mapper.listen(io.StringIO("".join(json.dumps(m) + "\n" for m in messages)))
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_schema_is_conformed_with_metadata(capsys: pytest.CaptureFixture[str]) -> None:
    """Names, types, keys and bookmarks are conformed; the _sdc_* columns are declared."""
    (schema,) = run_mapper([SCHEMA], capsys)
    assert schema["stream"] == "raw_customer_orders"
    assert schema["key_properties"] == ["order_id"]
    assert schema["bookmark_properties"] == ["updated_at"]
    properties = schema["schema"]["properties"]
    assert list(properties)[:3] == ["order_id", "amount", "updated_at"]
    assert properties["amount"]["format"] == "x-singer.decimal"
    assert properties["updated_at"]["x-sql-datatype"] == "timestamptz"
    assert properties["_sdc_sequence"] == {"type": ["null", "integer"]}


def test_record_is_conformed_and_message_fields_kept(capsys: pytest.CaptureFixture[str]) -> None:
    """Values are cleaned and cast; version and time_extracted pass unchanged."""
    _, record = run_mapper([SCHEMA, RECORD], capsys)
    assert record["stream"] == "raw_customer_orders"
    assert record["version"] == RECORD["version"]
    assert record["time_extracted"] == RECORD["time_extracted"]
    values = record["record"]
    assert values["order_id"] == 42  # noqa: PLR2004
    assert values["amount"] == "1234.50"
    assert values["updated_at"] == "2026-03-14T09:00:00.000000Z"
    assert values["_sdc_extracted_at"] == RECORD["time_extracted"]
    assert values["_sdc_table_version"] == RECORD["version"]


def test_state_passes_and_activate_version_is_renamed(capsys: pytest.CaptureFixture[str]) -> None:
    """STATE is untouched and in order; ACTIVATE_VERSION names the output stream."""
    out = run_mapper([SCHEMA, RECORD, STATE, ACTIVATE_VERSION], capsys)
    assert [m["type"] for m in out] == ["SCHEMA", "RECORD", "STATE", "ACTIVATE_VERSION"]
    assert out[2] == STATE
    assert out[3] == {**ACTIVATE_VERSION, "stream": "raw_customer_orders"}


def test_source_streams_and_dropped_streams(capsys: pytest.CaptureFixture[str]) -> None:
    """A source copy doubles the output; a dropped stream emits nothing."""
    spec = {**SPEC, "streams": {**SPEC["streams"], "orders_copy": {"source": "Customer Orders"}}}
    out = run_mapper([SCHEMA, RECORD], capsys, spec)
    assert [(m["type"], m["stream"]) for m in out] == [
        ("SCHEMA", "raw_customer_orders"),
        ("SCHEMA", "raw_orders_copy"),
        ("RECORD", "raw_customer_orders"),
        ("RECORD", "raw_orders_copy"),
    ]
    dropped = {"version": 1, "streams": {"Customer Orders": {"drop": True}}}
    assert run_mapper([SCHEMA, RECORD, STATE], capsys, dropped) == [STATE]


def test_a_bad_value_stops_the_run_with_its_context(capsys: pytest.CaptureFixture[str]) -> None:
    """on_error: raise (the default) stops with stream, column, row and value."""
    bad = {**RECORD, "record": {**RECORD["record"], "Amount": "lots"}}
    with pytest.raises(
        ConformError,
        match=r"stream 'Customer Orders', column 'amount', row 2: "
        r"cast: decimal\(12,2\) failed on 'lots'",
    ):
        run_mapper([SCHEMA, RECORD, bad], capsys)


def test_reject_drops_the_row_and_says_so(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    """on_error: reject removes the row from the output and logs it."""
    spec = {**SPEC, "defaults": {**SPEC["defaults"], "on_error": "reject"}}
    bad = {**RECORD, "record": {**RECORD["record"], "Amount": "lots"}}
    out = run_mapper([SCHEMA, bad, RECORD], capsys, spec)
    assert [m["type"] for m in out] == ["SCHEMA", "RECORD"]
    assert "Rejected row 1 of 'Customer Orders'" in caplog.text


def test_new_schema_recompiles(capsys: pytest.CaptureFixture[str]) -> None:
    """A second SCHEMA for the stream replaces its plan."""
    wider = {
        **SCHEMA,
        "schema": {
            "type": "object",
            "properties": {**SCHEMA["schema"]["properties"], "Note": {"type": ["string", "null"]}},
        },
    }
    out = run_mapper(
        [SCHEMA, RECORD, wider, {**RECORD, "record": {**RECORD["record"], "Note": "x"}}], capsys
    )
    assert "note" not in out[1]["record"]
    assert out[3]["record"]["note"] == "x"


def test_metadata_none_and_record_before_schema(capsys: pytest.CaptureFixture[str]) -> None:
    """metadata: none emits no _sdc_* columns; a RECORD before its SCHEMA is an error."""
    spec = {**SPEC, "defaults": {**SPEC["defaults"], "metadata": "none"}}
    schema, record = run_mapper([SCHEMA, RECORD], capsys, spec)
    assert not [p for p in schema["schema"]["properties"] if p.startswith("_sdc_")]
    assert not [p for p in record["record"] if p.startswith("_sdc_")]
    with pytest.raises(ValueError, match="before its SCHEMA"):
        run_mapper([RECORD], capsys)


def test_batch_is_refused_until_p4(capsys: pytest.CaptureFixture[str]) -> None:
    """BATCH stops with a clear message rather than passing unconformed files."""
    batch = {
        "type": "BATCH",
        "stream": "Customer Orders",
        "encoding": {"format": "jsonl"},
        "manifest": [],
    }
    with pytest.raises(NotImplementedError, match="conformed from phase P4"):
        run_mapper([SCHEMA, batch], capsys)


def test_plan_problems_are_config_errors(capsys: pytest.CaptureFixture[str]) -> None:
    """A spec that does not fit the tap SCHEMA fails at the SCHEMA, with paths."""
    spec = {
        "version": 1,
        "streams": {"Customer Orders": {"columns": {"Missing": {"type": "int64"}}}},
    }
    with pytest.raises(ConfigValidationError) as caught:
        run_mapper([SCHEMA], capsys, spec)
    assert caught.value.errors == [
        (
            "streams[\"Customer Orders\"].columns.Missing: column 'Missing' is not in the catalog "
            "stream; a new column needs expr"
        )
    ]


def test_about_lists_only_implemented_capabilities() -> None:
    """--about does not advertise stream maps or flattening before they exist."""
    result = CliRunner().invoke(MapConformMapper.cli, ["--about", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["capabilities"] == ["about", "structured-logging"]


@pytest.mark.parametrize(
    "command",
    [[str(Path(sys.executable).with_name("map-conform"))], [sys.executable, "-m", "map_conform"]],
    ids=["console-script", "python-m"],
)
def test_cli_maps_stdin_to_stdout(command: list[str], tmp_path: Path) -> None:
    """The installed executable, run as Meltano runs it, conforms stdin to stdout."""
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"spec": SPEC}))
    result = subprocess.run(  # noqa: S603 -- fixed argv built from this interpreter
        [*command, "--config", str(config)],
        input="".join(json.dumps(m) + "\n" for m in (SCHEMA, RECORD, STATE)),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    out = [json.loads(line) for line in result.stdout.splitlines()]
    assert [m["type"] for m in out] == ["SCHEMA", "RECORD", "STATE"]
    assert out[1]["record"]["order_id"] == 42  # noqa: PLR2004
