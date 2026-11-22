"""Temporal casts beyond the corpus: DST policies, zones, precision, builtins (WBS 5.4)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest

from map_conform.plan.chain import StepError
from tests.transforms.test_builtins import problems, run

UTC = dt.UTC
NY = "America/New_York"


def ts(value: object, target: str = "timestamptz", **kwargs: Any) -> object:
    """Cast one value to a temporal type with cast options."""
    return run({"cast": target, **kwargs}, value, target=target)


@pytest.mark.parametrize(
    ("wall", "policy", "expected_hour"),
    [
        ("2026-11-01 01:30:00", {"ambiguous": "earliest"}, 5),
        ("2026-11-01 01:30:00", {"ambiguous": "latest"}, 6),
        ("2026-11-01 00:30:00", {}, 4),
        ("2026-11-01 02:30:00", {}, 7),
        ("2026-03-08 02:30:00", {"nonexistent": "shift"}, 7),
        ("2026-03-08 03:30:00", {}, 7),
        ("2026-03-08 01:59:59", {}, 6),
    ],
)
def test_dst_transitions(wall: str, policy: dict[str, str], expected_hour: int) -> None:
    """Around both New York transitions: unambiguous times, and both policies."""
    result = ts(wall, tz=NY, **policy)
    assert isinstance(result, dt.datetime)
    assert result.tzinfo == UTC
    assert result.hour == expected_hour


@pytest.mark.parametrize(
    ("wall", "reason"),
    [("2026-11-01 01:30:00", "happens twice"), ("2026-03-08 02:30:00", "does not exist")],
)
def test_dst_problems_are_errors_by_default(wall: str, reason: str) -> None:
    """Ambiguous and nonexistent wall times fail unless a policy says otherwise."""
    with pytest.raises(StepError, match=reason):
        ts(wall, tz=NY)


def test_southern_hemisphere_and_half_hour_zones() -> None:
    """Zones other than New York, including a half-hour offset."""
    assert ts("2026-04-05 02:30:00", tz="Australia/Sydney", ambiguous="earliest") == dt.datetime(
        2026, 4, 4, 15, 30, tzinfo=UTC
    )
    assert ts("2026-03-14 12:00:00", tz="Asia/Kolkata") == dt.datetime(
        2026, 3, 14, 6, 30, tzinfo=UTC
    )


def test_explicit_offsets_ignore_the_zone_setting() -> None:
    """An input with its own offset is not re-zoned, even during a DST gap."""
    assert ts("2026-03-08T02:30:00-05:00", tz=NY) == dt.datetime(2026, 3, 8, 7, 30, tzinfo=UTC)


def test_timestamp_and_date_targets_use_the_wall_time_in_tz() -> None:
    """Aware input to a naive timestamp or date converts to tz first."""
    assert ts("2026-03-14T23:30:00-05:00", target="timestamp", tz=NY) == dt.datetime(  # noqa: DTZ001
        2026, 3, 15, 0, 30
    )
    assert ts("2026-03-15T03:30:00Z", target="date", tz=NY) == dt.date(2026, 3, 14)
    assert ts("2026-03-14 09:00", target="timestamp", formats=["%Y-%m-%d %H:%M"]) == dt.datetime(  # noqa: DTZ001
        2026, 3, 14, 9, 0
    )


@pytest.mark.parametrize(
    ("value", "kwargs", "expected"),
    [
        (
            "2026-03-14T09:26:53.123456789Z",
            {},
            dt.datetime(2026, 3, 14, 9, 26, 53, 123456, tzinfo=UTC),
        ),
        ("2026-03-14t09:26:53,5z", {}, dt.datetime(2026, 3, 14, 9, 26, 53, 500000, tzinfo=UTC)),
        ("2026-03-14T09:26+0530", {}, dt.datetime(2026, 3, 14, 3, 56, tzinfo=UTC)),
        (
            "2026-03-14T09:26:53.987654Z",
            {"output_precision": "ms"},
            dt.datetime(2026, 3, 14, 9, 26, 53, 987000, tzinfo=UTC),
        ),
        (
            "2026-03-14T09:26:53.987654Z",
            {"output_precision": "s"},
            dt.datetime(2026, 3, 14, 9, 26, 53, tzinfo=UTC),
        ),
        (46095.0, {"formats": ["excel_serial"]}, dt.datetime(2026, 3, 14, tzinfo=UTC)),
        (
            Decimal("46095.25"),  # how the SDK decodes a JSON fraction
            {"formats": ["excel_serial"]},
            dt.datetime(2026, 3, 14, 6, tzinfo=UTC),
        ),
        (
            Decimal("1773480413.5"),
            {"formats": ["epoch_s"]},
            dt.datetime(2026, 3, 14, 9, 26, 53, 500000, tzinfo=UTC),
        ),
        (1773480413, {"formats": ["epoch_s"]}, dt.datetime(2026, 3, 14, 9, 26, 53, tzinfo=UTC)),
        (
            "1773480413123456789",
            {"formats": ["epoch_ns"]},
            dt.datetime(2026, 3, 14, 9, 26, 53, 123456, tzinfo=UTC),
        ),
        (
            "Sat, 14 Mar 2026 09:26:53 -0000",
            {"formats": ["rfc2822"]},
            dt.datetime(2026, 3, 14, 9, 26, 53, tzinfo=UTC),
        ),
        (
            "46095.5",
            {"formats": ["excel_serial"], "tz": NY},
            dt.datetime(2026, 3, 14, 16, tzinfo=UTC),
        ),
    ],
)
def test_formats_and_precision(
    value: object, kwargs: dict[str, Any], expected: dt.datetime
) -> None:
    """Fractions, offsets, precision, XLSX floats, epochs and RFC 2822."""
    assert ts(value, **kwargs) == expected


def test_time_target() -> None:
    """Times parse from ISO times and patterns; an offset on a time is dropped."""
    assert ts("09:26:53.5+02:00", target="time") == dt.time(9, 26, 53, 500000)
    with pytest.raises(StepError, match="matches none of the formats"):
        ts("25:00", target="time")
    with pytest.raises(StepError, match="a time of day is not a timestamptz"):
        ts("09:26")


def test_bounds_and_bad_input() -> None:
    """Year bounds, serials before the epoch, booleans."""
    with pytest.raises(StepError, match="after max_year"):
        ts("2999-01-01", max_year=2100)
    with pytest.raises(StepError, match="before the epoch"):
        ts("-3", formats=["excel_serial"])
    with pytest.raises(StepError, match="a boolean is not a date"):
        ts(True)  # noqa: FBT003


def test_options_are_checked_at_compile_time() -> None:
    """Unknown format tokens and zones are spec errors, not run-time surprises."""
    assert problems({"cast": "timestamptz", "formats": ["iso", "auto"]}, "timestamptz") == [
        (
            "c.transform.formats: unknown format(s) ['auto']; use a strptime pattern or one of "
            "['epoch_auto', 'epoch_ms', 'epoch_ns', 'epoch_s', 'epoch_us', 'excel_serial', "
            "'excel_serial_1904', 'iso', 'rfc2822']"
        )
    ]
    assert problems({"cast": "timestamptz", "tz": "Mars/Olympus"}, "timestamptz") == [
        "c.transform.tz: unknown time zone 'Mars/Olympus'"
    ]


def test_temporal_builtins() -> None:
    """to_local, assume_tz, truncate, date_from_timestamp and to_utc change stage as declared."""
    moment = "2026-03-14T15:30:45Z"
    assert run([{"cast": "timestamptz"}, "to_utc"], moment, target="timestamptz") == dt.datetime(
        2026, 3, 14, 15, 30, 45, tzinfo=UTC
    )
    assert run(
        [{"cast": "timestamptz"}, {"to_local": NY}], moment, target="timestamp"
    ) == dt.datetime(  # noqa: DTZ001
        2026, 3, 14, 11, 30, 45
    )
    assert run(
        [{"cast": "timestamp"}, {"assume_tz": NY}], "2026-03-14 11:30:45", target="timestamptz"
    ) == dt.datetime(2026, 3, 14, 15, 30, 45, tzinfo=UTC)
    assert run(
        [{"cast": "timestamptz"}, {"truncate": "hour"}], moment, target="timestamptz"
    ) == dt.datetime(2026, 3, 14, 15, tzinfo=UTC)
    assert run([{"cast": "date"}, {"truncate": "month"}], "2026-03-14", target="date") == dt.date(
        2026, 3, 1
    )
    assert run(
        [{"cast": "timestamptz"}, {"date_from_timestamp": NY}],
        "2026-03-15T02:00:00Z",
        target="date",
    ) == dt.date(2026, 3, 14)
    assert problems([{"cast": "timestamptz"}, {"assume_tz": NY}], "timestamptz") == [
        "c.transform[1]: assume_tz cannot take a timestamptz value here"
    ]
