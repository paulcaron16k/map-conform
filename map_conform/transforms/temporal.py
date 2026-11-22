"""Temporal casts and builtins (detailed design §6.3).

Formats are tried in order; the first that parses wins:

- a ``strptime`` pattern (anything containing ``%``);
- ``iso``: ISO-8601 dates, times and timestamps, leniently: ``Z``/``z``, a space or ``t``
  separator, any number of fraction digits (kept to microseconds), date-only;
- ``excel_serial``: the 1900 date system, with Lotus's bug: serials below 60 count from
  1899-12-31, and 60 (the 1900-02-29 that never existed) is an error;
  ``excel_serial_1904``: the 1904 system;
- ``epoch_s`` / ``epoch_ms`` / ``epoch_us`` / ``epoch_ns``, and ``epoch_auto`` by magnitude;
- ``rfc2822``.

A naive result is placed in ``tz`` (default: the stream's ``assume_tz``). A wall time that
happens twice (DST ends) follows ``ambiguous``; one that never happens (DST starts) follows
``nonexistent``. Both default to ``error``. ``timestamptz`` values are UTC.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from map_conform.errors import StepFailed
from map_conform.spec._struct import documented
from map_conform.transforms.casts import Cleanup, clean, cleanup_defaults
from map_conform.transforms.registry import RAW, TEMPORAL, Registry, Transform
from map_conform.types.canonical import CType, Kind

if TYPE_CHECKING:
    from collections.abc import Callable

    from map_conform.plan.chain import CastArgs
    from map_conform.spec.model import ColumnSpec, Defaults
    from map_conform.transforms.registry import Context

NAMED_FORMATS = frozenset(
    {
        "iso",
        "excel_serial",
        "excel_serial_1904",
        "epoch_s",
        "epoch_ms",
        "epoch_us",
        "epoch_ns",
        "epoch_auto",
        "rfc2822",
    }
)
_EXCEL_1900 = dt.datetime(1899, 12, 30)  # noqa: DTZ001 -- serials are naive wall time
_EXCEL_EARLY = dt.datetime(1899, 12, 31)  # noqa: DTZ001
_EXCEL_1904 = dt.datetime(1904, 1, 1)  # noqa: DTZ001
_LOTUS_LEAP_DAY = 60
_EPOCH_DIVISORS = {"epoch_s": 1, "epoch_ms": 10**3, "epoch_us": 10**6, "epoch_ns": 10**9}
_MICROS_PER_DAY = 86_400 * 10**6
_ISO_DATE = r"(?P<date>\d{4}-\d{2}-\d{2})"
_ISO_TIME = r"(?P<h>\d{2}):(?P<m>\d{2})(?::(?P<s>\d{2})(?:[.,](?P<f>\d+))?)?"
_ISO_ZONE = r"(?P<z>[Zz]|[+-]\d{2}(?::?\d{2})?)?"
_ISO_TIMESTAMP = re.compile(rf"^{_ISO_DATE}(?:[Tt ]{_ISO_TIME})?\s*{_ISO_ZONE}$")
_ISO_TIME_ONLY = re.compile(rf"^{_ISO_TIME}\s*{_ISO_ZONE}$")
_NUMBER = re.compile(r"^[+-]?\d+(?:\.\d+)?$")


def _formats_problem(formats: tuple[str, ...]) -> str | None:
    unknown = [f for f in formats if "%" not in f and f not in NAMED_FORMATS]
    if unknown:
        return (
            f"unknown format(s) {unknown}; use a strptime pattern or one of {sorted(NAMED_FORMATS)}"
        )
    return None if formats else "give at least one format"


def _zone_problem(tz: str) -> str | None:
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        return f"unknown time zone {tz!r}"
    return None


@dataclass(frozen=True)
class TemporalCast(Cleanup):
    """Options for casts to timestamptz, timestamp, date and time."""

    formats: tuple[str, ...] = documented(
        "Formats tried in order.", default=("iso",), metadata={"check": _formats_problem}
    )
    tz: str = documented("Zone of naive input.", default="UTC", metadata={"check": _zone_problem})
    ambiguous: Literal["error", "earliest", "latest"] = "error"
    nonexistent: Literal["error", "shift"] = "error"
    min_year: int | None = None
    max_year: int | None = None
    output_precision: Literal["s", "ms", "us"] = "us"


def _temporal_defaults(settings: Defaults, column: ColumnSpec | None) -> dict[str, Any]:
    out = cleanup_defaults(settings, column)
    out["formats"] = list(settings.timestamp.formats)
    out["tz"] = settings.timestamp.assume_tz
    out["output_precision"] = settings.timestamp.output_precision
    return out


# --- parsing ----------------------------------------------------------------------------------


def _offset(zone: str) -> dt.tzinfo:
    if zone in {"Z", "z"}:
        return dt.UTC
    sign = -1 if zone[0] == "-" else 1
    digits = zone[1:].replace(":", "")
    hours, minutes = int(digits[:2]), int(digits[2:4] or 0)
    return dt.timezone(sign * dt.timedelta(hours=hours, minutes=minutes))


def _iso(text: str) -> dt.datetime | dt.time | None:
    if match := _ISO_TIMESTAMP.match(text):
        day = dt.date.fromisoformat(match["date"])
        clock = _clock(match) if match["h"] else dt.time()
        tzinfo = _offset(match["z"]) if match["z"] else None
        return dt.datetime.combine(day, clock, tzinfo)
    if match := _ISO_TIME_ONLY.match(text):
        clock = _clock(match)
        return clock.replace(tzinfo=_offset(match["z"])) if match["z"] else clock
    return None


def _clock(match: re.Match[str]) -> dt.time:
    fraction = (match["f"] or "")[:6].ljust(6, "0")
    return dt.time(int(match["h"]), int(match["m"]), int(match["s"] or 0), int(fraction))


def _serial(text: str, *, system_1904: bool) -> dt.datetime | None:
    if not _NUMBER.match(text):
        return None
    serial = Decimal(text)
    if serial <= 0:
        raise StepFailed(f"Excel serial {text} is before the epoch")
    days = int(serial)
    micros = int(((serial - days) * _MICROS_PER_DAY).to_integral_value(ROUND_HALF_UP))
    if system_1904:
        base = _EXCEL_1904
    elif days == _LOTUS_LEAP_DAY:
        raise StepFailed("Excel serial 60 is 1900-02-29, which never existed")
    else:
        base = _EXCEL_EARLY if days < _LOTUS_LEAP_DAY else _EXCEL_1900
    return base + dt.timedelta(days=days, microseconds=micros)


def _epoch(text: str, unit: str) -> dt.datetime | None:
    if not _NUMBER.match(text):
        return None
    number = Decimal(text)
    if unit == "epoch_auto":
        size = abs(number)
        unit = (
            "epoch_s"
            if size < 10**11
            else "epoch_ms"
            if size < 10**14
            else "epoch_us"
            if size < 10**17
            else "epoch_ns"
        )
    micros = int(number * 10**6 / _EPOCH_DIVISORS[unit])  # truncates below a microsecond
    return dt.datetime(1970, 1, 1, tzinfo=dt.UTC) + dt.timedelta(microseconds=micros)


def _rfc2822(text: str) -> dt.datetime | None:
    return parsedate_to_datetime(text)


def _parser(fmt: str) -> Callable[[str], dt.datetime | dt.time | None]:
    if "%" in fmt:
        return lambda text: dt.datetime.strptime(text, fmt)  # noqa: DTZ007 -- zoned later
    if fmt in {"excel_serial", "excel_serial_1904"}:
        return lambda text: _serial(text, system_1904=fmt == "excel_serial_1904")
    if fmt.startswith("epoch_"):
        return lambda text: _epoch(text, fmt)
    return {"iso": _iso, "rfc2822": _rfc2822}[fmt]


def _one_format(text: str, fmt: str) -> dt.datetime | dt.time | None:
    """Parse with one format; None when it does not apply."""
    try:
        return _parser(fmt)(text)
    except (ValueError, OverflowError, InvalidOperation, TypeError, IndexError):
        return None


def parse_temporal(value: object, options: TemporalCast) -> dt.datetime | dt.time | dt.date | None:
    """Parse a raw value with the configured formats, before zones and target types."""
    cleaned = clean(value, options)
    if cleaned is None or isinstance(cleaned, (dt.datetime, dt.date, dt.time)):
        return cleaned
    if isinstance(cleaned, bool):
        raise StepFailed("a boolean is not a date")
    text = cleaned if isinstance(cleaned, str) else repr(cleaned)
    for fmt in options.formats:
        parsed = _one_format(text, fmt)
        if parsed is not None:
            return parsed
    raise StepFailed(f"matches none of the formats {list(options.formats)}")


# --- zones ------------------------------------------------------------------------------------


def localize(naive: dt.datetime, options: TemporalCast) -> dt.datetime:
    """Place a naive wall time in ``options.tz``, applying the DST policies."""
    zone = ZoneInfo(options.tz)
    early, late = naive.replace(tzinfo=zone, fold=0), naive.replace(tzinfo=zone, fold=1)
    exists = early.astimezone(dt.UTC).astimezone(zone).replace(tzinfo=None) == naive
    if not exists:
        if options.nonexistent == "error":
            raise StepFailed(f"{naive} does not exist in {options.tz} (a DST gap)")
        return early  # converts to the instant after the gap
    if early.utcoffset() != late.utcoffset():
        if options.ambiguous == "error":
            raise StepFailed(f"{naive} happens twice in {options.tz} (DST ends)")
        return early if options.ambiguous == "earliest" else late
    return early


def _precision(value: dt.datetime | dt.time, precision: str) -> Any:  # noqa: ANN401
    if precision == "s":
        return value.replace(microsecond=0)
    if precision == "ms":
        return value.replace(microsecond=value.microsecond // 1000 * 1000)
    return value


def _check_year(day: dt.date, options: TemporalCast) -> None:
    if options.min_year is not None and day.year < options.min_year:
        raise StepFailed(f"year {day.year} is before min_year {options.min_year}")
    if options.max_year is not None and day.year > options.max_year:
        raise StepFailed(f"year {day.year} is after max_year {options.max_year}")


def cast_temporal(value: object, args: CastArgs, _ctx: Context) -> object:
    """Cast to timestamptz, timestamp, date or time."""
    options: TemporalCast = args.options
    parsed = parse_temporal(value, options)
    if parsed is None:
        return None
    kind = args.target.kind
    if isinstance(parsed, dt.time):
        if kind != "time":
            raise StepFailed(f"a time of day is not a {kind}")
        return _precision(parsed.replace(tzinfo=None), options.output_precision)
    if not isinstance(parsed, dt.datetime):  # a date object
        parsed = dt.datetime.combine(parsed, dt.time())
    if kind == "time":
        return _precision(parsed.timetz().replace(tzinfo=None), options.output_precision)
    if kind == "timestamptz":
        aware = parsed if parsed.tzinfo else localize(parsed, options)
        result = aware.astimezone(dt.UTC)
    else:  # timestamp and date: the wall time in tz
        result = (
            parsed.astimezone(ZoneInfo(options.tz)).replace(tzinfo=None)
            if parsed.tzinfo
            else parsed
        )
    _check_year(result.date(), options)
    if kind == "date":
        return result.date()
    return _precision(result, options.output_precision)


# --- builtins after the cast -------------------------------------------------------------------


@dataclass(frozen=True)
class ZoneKwargs:
    """A time zone."""

    tz: str = documented(
        "IANA zone, e.g. America/New_York.", default="UTC", metadata={"check": _zone_problem}
    )


@dataclass(frozen=True)
class OptionalZoneKwargs:
    """An optional time zone (default: the value's own, UTC for timestamptz)."""

    tz: str | None = documented("IANA zone.", default=None, metadata={"check": _zone_problem})


@dataclass(frozen=True)
class TruncateKwargs:
    """Truncate to a unit."""

    unit: Literal["year", "month", "day", "hour", "minute", "second"] = "day"


def _truncate_datetime(value: dt.datetime, unit: str) -> dt.datetime:
    if unit == "second":
        return value.replace(microsecond=0)
    if unit == "minute":
        return value.replace(second=0, microsecond=0)
    if unit == "hour":
        return value.replace(minute=0, second=0, microsecond=0)
    day = _truncate_date(value.date(), unit)
    return dt.datetime.combine(day, dt.time(), value.tzinfo)


def _truncate_date(value: dt.date, unit: str) -> dt.date:
    if unit == "year":
        return value.replace(month=1, day=1)
    if unit == "month":
        return value.replace(day=1)
    return value


def _truncate(value: object, k: TruncateKwargs, _ctx: Context) -> object:
    if isinstance(value, dt.datetime):
        return _truncate_datetime(value, k.unit)
    if isinstance(value, dt.date):
        return _truncate_date(value, k.unit)
    raise StepFailed(f"truncate needs a date or timestamp, got {type(value).__name__}")


def _assume_tz(value: object, k: ZoneKwargs, _ctx: Context) -> object:
    options = TemporalCast(tz=k.tz)
    if not isinstance(value, dt.datetime):
        raise StepFailed("assume_tz needs a timestamp")
    return localize(value, options).astimezone(dt.UTC)


def _to_local(value: object, k: ZoneKwargs, _ctx: Context) -> object:
    if not isinstance(value, dt.datetime):
        raise StepFailed("to_local needs a timestamptz")
    return value.astimezone(ZoneInfo(k.tz)).replace(tzinfo=None)


def _date_from_timestamp(value: object, k: OptionalZoneKwargs, _ctx: Context) -> object:
    if not isinstance(value, dt.datetime):
        raise StepFailed("date_from_timestamp needs a timestamp")
    if value.tzinfo is not None and k.tz is not None:
        value = value.astimezone(ZoneInfo(k.tz))
    return value.date()


def _stage(kind: Kind) -> Callable[[CType | None, object], CType]:
    """A produces() callback giving a fixed type."""
    return lambda _stage, _k: CType(kind)


def register(registry: Registry) -> None:
    """Add the temporal casts and builtins."""
    registry.register_cast(
        TEMPORAL,
        Transform(
            "cast",
            cast_temporal,
            kwargs=TemporalCast,
            defaults=_temporal_defaults,
            accepts=frozenset({RAW, "string", *TEMPORAL}),
        ),
    )
    registry.register(Transform("to_utc", lambda v, _k, _c: v, accepts=frozenset({"timestamptz"})))
    registry.register(
        Transform(
            "assume_tz",
            _assume_tz,
            kwargs=ZoneKwargs,
            positional="tz",
            accepts=frozenset({"timestamp"}),
            produces=_stage("timestamptz"),
        )
    )
    registry.register(
        Transform(
            "to_local",
            _to_local,
            kwargs=ZoneKwargs,
            positional="tz",
            accepts=frozenset({"timestamptz"}),
            produces=_stage("timestamp"),
        )
    )
    registry.register(
        Transform(
            "truncate",
            _truncate,
            kwargs=TruncateKwargs,
            positional="unit",
            accepts=frozenset({"date", "timestamp", "timestamptz"}),
        )
    )
    registry.register(
        Transform(
            "date_from_timestamp",
            _date_from_timestamp,
            kwargs=OptionalZoneKwargs,
            positional="tz",
            accepts=frozenset({"timestamp", "timestamptz"}),
            produces=_stage("date"),
        )
    )
