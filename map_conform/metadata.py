"""The seven ``_sdc_*`` columns, exactly as the Singer SDK sets them (detailed design §11).

Names, schema and values match ``singer_sdk.sinks.core.Sink._add_sdc_metadata_to_record`` and
``_add_sdc_metadata_to_schema``, with one documented difference: ``_sdc_batched_at`` for
RECORD messages is the mapper's start time (the run is the batch), and the record's own
``_sdc_deleted_at`` is conformed to a UTC timestamp.

An SDK target strips these columns unless it sets ``add_record_metadata: true``.
"""

from __future__ import annotations

import datetime as dt
import time
from typing import Any

from map_conform.errors import StepFailed
from map_conform.transforms.temporal import TemporalCast, localize, parse_temporal

SDC_PREFIX = "_sdc_"
TIMESTAMP_COLUMNS = ("_sdc_extracted_at", "_sdc_received_at", "_sdc_batched_at", "_sdc_deleted_at")
INTEGER_COLUMNS = ("_sdc_sequence", "_sdc_table_version", "_sdc_sync_started_at")
_DELETED_AT = TemporalCast(formats=("iso",))


def sdc_schema() -> dict[str, dict[str, Any]]:
    """The ``_sdc_*`` property schemas, as the SDK writes them."""
    properties: dict[str, dict[str, Any]] = {
        column: {"type": ["null", "string"], "format": "date-time"} for column in TIMESTAMP_COLUMNS
    }
    properties.update({column: {"type": ["null", "integer"]} for column in INTEGER_COLUMNS})
    return properties


class Metadata:
    """Adds ``_sdc_*`` values to conformed records for one run."""

    def __init__(self, started_at: dt.datetime | None = None) -> None:
        """Fix the run's start: ``_sdc_batched_at`` and ``_sdc_sync_started_at`` derive from it."""
        start = started_at or dt.datetime.now(tz=dt.UTC)
        self.batched_at = start.isoformat()
        self.sync_started_at = int(start.timestamp() * 1000)

    def add(self, record: dict[str, Any], message: dict[str, Any], deleted_at: object) -> None:
        """Set the seven columns on an output record.

        Raises:
            StepFailed: if the source ``_sdc_deleted_at`` is not a timestamp.
        """
        record["_sdc_extracted_at"] = message.get("time_extracted")
        record["_sdc_received_at"] = dt.datetime.now(tz=dt.UTC).isoformat()
        record["_sdc_batched_at"] = self.batched_at
        record["_sdc_deleted_at"] = conform_deleted_at(deleted_at)
        record["_sdc_sequence"] = round(time.time() * 1000)
        record["_sdc_table_version"] = message.get("version")
        record["_sdc_sync_started_at"] = self.sync_started_at


def conform_deleted_at(value: object) -> str | None:
    """A source ``_sdc_deleted_at`` as a UTC ISO timestamp, or None."""
    if value is None or value == "":
        return None
    parsed = parse_temporal(value, _DELETED_AT)
    if not isinstance(parsed, dt.datetime):
        raise StepFailed(f"_sdc_deleted_at {value!r} is not a timestamp")
    aware = parsed if parsed.tzinfo else localize(parsed, _DELETED_AT)
    return aware.astimezone(dt.UTC).isoformat()
