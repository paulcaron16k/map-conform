"""The P0 mapper passes every message through unchanged."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from map_conform.mapper import MapConformMapper

SCHEMA = {
    "type": "SCHEMA",
    "stream": "Customer Orders",
    "schema": {"type": "object", "properties": {"Order ID": {"type": ["string", "null"]}}},
    "key_properties": ["Order ID"],
}
RECORD = {
    "type": "RECORD",
    "stream": "Customer Orders",
    "record": {"Order ID": " 0042 ", "Amount": "$1,234.50", "Nested": {"a": [1, None]}},
    "time_extracted": "2026-11-21T08:30:00.123456+05:30",
    "version": 1732170000000,
}
STATE = {"type": "STATE", "value": {"bookmarks": {"Customer Orders": {"replication_key": "x"}}}}
ACTIVATE_VERSION = {"type": "ACTIVATE_VERSION", "stream": "Customer Orders", "version": 7}
BATCH = {
    "type": "BATCH",
    "stream": "Customer Orders",
    "encoding": {"format": "parquet", "compression": "gzip"},
    "manifest": ["file:///nonexistent/part-0001.parquet"],
    "time_extracted": "2026-11-21T08:30:00Z",
    "x-producer-extension": {"rows": 3},
}


def run_mapper(messages: list[dict[str, Any]], capsys: pytest.CaptureFixture[str]) -> list[Any]:
    """Feed messages through the mapper and return what it wrote."""
    mapper = MapConformMapper(config={})
    lines = "".join(json.dumps(m) + "\n" for m in messages)
    capsys.readouterr()
    mapper.listen(io.StringIO(lines))
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


@pytest.mark.parametrize(
    "message",
    [SCHEMA, RECORD, STATE, ACTIVATE_VERSION, BATCH],
    ids=lambda m: m["type"],
)
def test_message_passes_through_unchanged(
    message: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Each message type, including unmodelled fields, is emitted exactly as read."""
    assert run_mapper([message], capsys) == [message]


def test_stream_order_is_preserved(capsys: pytest.CaptureFixture[str]) -> None:
    """A whole stream comes out in input order."""
    stream: list[dict[str, Any]] = [SCHEMA, RECORD, BATCH, ACTIVATE_VERSION, STATE]
    assert run_mapper(stream, capsys) == stream


def test_batch_files_are_not_opened(capsys: pytest.CaptureFixture[str]) -> None:
    """A BATCH pass-through forwards the manifest without reading the files it names."""
    (out,) = run_mapper([BATCH], capsys)
    assert out["manifest"] == BATCH["manifest"]


def test_about_lists_only_implemented_capabilities() -> None:
    """``--about`` does not advertise stream maps or flattening before they exist."""
    result = CliRunner().invoke(MapConformMapper.cli, ["--about", "--format", "json"])
    assert result.exit_code == 0, result.output
    about = json.loads(result.output)
    assert about["name"] == "map-conform"
    assert about["capabilities"] == ["about", "structured-logging"]


@pytest.mark.parametrize(
    "command",
    [
        [str(Path(sys.executable).with_name("map-conform"))],
        [sys.executable, "-m", "map_conform"],
    ],
    ids=["console-script", "python-m"],
)
def test_cli_maps_stdin_to_stdout(command: list[str], tmp_path: Path) -> None:
    """The installed executable, run as Meltano runs it, maps stdin to stdout."""
    config = tmp_path / "config.json"
    config.write_text("{}")
    stream: list[dict[str, Any]] = [SCHEMA, RECORD, BATCH, STATE]
    result = subprocess.run(  # noqa: S603 -- fixed argv built from this interpreter
        [*command, "--config", str(config)],
        input="".join(json.dumps(m) + "\n" for m in stream),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert [json.loads(line) for line in result.stdout.splitlines()] == stream
