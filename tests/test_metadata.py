"""_sdc_* columns match the Singer SDK exactly (WBS 7.1)."""

from __future__ import annotations

import datetime as dt
import time
from types import SimpleNamespace
from typing import cast

import pytest
from singer_sdk.sinks.core import Sink

from map_conform.errors import StepFailed
from map_conform.metadata import Metadata, conform_deleted_at, sdc_schema

START = dt.datetime(2026, 3, 14, 12, 0, tzinfo=dt.UTC)
MESSAGE = {
    "type": "RECORD",
    "stream": "s",
    "record": {},
    "version": 7,
    "time_extracted": "2026-03-14T11:59:00+00:00",
}


def test_schema_matches_the_sdk() -> None:
    """The seven property schemas equal the SDK's _add_sdc_metadata_to_schema output."""
    fake = SimpleNamespace(schema={"properties": {}})
    Sink._add_sdc_metadata_to_schema(cast("Sink", fake))  # noqa: SLF001
    assert sdc_schema() == fake.schema["properties"]
    assert list(sdc_schema()) == list(fake.schema["properties"])


def test_values_match_the_sdk() -> None:
    """Same keys, same deterministic values, same shapes for the clock-based ones."""
    ours: dict[str, object] = {}
    before = round(time.time() * 1000)
    Metadata(START).add(ours, MESSAGE, deleted_at=None)
    theirs: dict[str, object] = {}
    fake = SimpleNamespace(sync_started_at=int(START.timestamp() * 1000))
    Sink._add_sdc_metadata_to_record(  # noqa: SLF001
        cast("Sink", fake), theirs, MESSAGE, {"batch_start_time": START}
    )
    assert list(ours) == list(theirs)
    for key in (
        "_sdc_extracted_at",
        "_sdc_batched_at",
        "_sdc_deleted_at",
        "_sdc_table_version",
        "_sdc_sync_started_at",
    ):
        assert ours[key] == theirs[key], key
    received = dt.datetime.fromisoformat(str(ours["_sdc_received_at"]))
    assert received.tzinfo is not None
    assert isinstance(ours["_sdc_sequence"], int)
    assert ours["_sdc_sequence"] >= before


def test_deleted_at_is_conformed_to_utc() -> None:
    """The record's own _sdc_deleted_at becomes a UTC ISO timestamp."""
    assert conform_deleted_at("2026-03-14T09:00:00-05:00") == "2026-03-14T14:00:00+00:00"
    assert conform_deleted_at("2026-03-14 09:00") == "2026-03-14T09:00:00+00:00"
    assert conform_deleted_at(None) is None
    assert conform_deleted_at("") is None
    with pytest.raises(StepFailed, match="matches none of the formats"):
        conform_deleted_at("soon")
