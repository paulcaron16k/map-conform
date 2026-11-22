"""The expression function library (detailed design §7).

Every function is listed by ``map-conform functions`` with its group, signature and doc. The
SDK stream-map names (``md5``, ``sha256``, ``int``, ``float``, ``str``, ``bool``, ``rand``,
``randint``, and the ``datetime`` and ``json`` modules) behave exactly as in the SDK.

Apart from the predicates, ``coalesce`` and the Python builtins, a function given a null
returns null, so ``lower(x)`` on a missing ``x`` is null rather than an error.
"""

from __future__ import annotations

import datetime as dt
import functools
import hashlib
import json
import random
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

from map_conform.errors import StepFailed
from map_conform.expr.sandbox import MAX_LENGTH, MODULES, SandboxError, safe_range
from map_conform.transforms.temporal import TemporalCast, localize, parse_temporal

_TRUE = frozenset({"true", "t", "yes", "y", "1", "on"})
_FALSE = frozenset({"false", "f", "no", "n", "0", "off"})
_UUID_NAMESPACES = MappingProxyType(
    {
        "dns": uuid.NAMESPACE_DNS,
        "url": uuid.NAMESPACE_URL,
        "oid": uuid.NAMESPACE_OID,
        "x500": uuid.NAMESPACE_X500,
    }
)


@dataclass(frozen=True)
class Function:
    """A function expressions may call."""

    name: str
    fn: object
    """The callable, or a read-only module."""
    group: str
    signature: str
    doc: str


_LIBRARY: dict[str, Function] = {}


def _function(group: str, signature: str, *, name: str | None = None) -> Callable[..., Any]:
    def register(fn: Callable[..., Any]) -> Callable[..., Any]:
        key = name or str(getattr(fn, "__name__", ""))
        doc = (fn.__doc__ or "").strip().splitlines()[0]
        _LIBRARY[key] = Function(key, fn, group, f"{key}({signature})", doc)
        return fn

    return register


def _nullable(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Return null when the first argument is null."""

    @functools.wraps(fn)
    def wrapper(value: object, *args: Any, **kwargs: Any) -> object:
        return None if value is None else fn(value, *args, **kwargs)

    return wrapper


def _text(value: object) -> str:
    """A value as text: exact decimals in plain notation, temporals in ISO 8601."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    return str(value)


def _decimal(value: object) -> Decimal:
    if isinstance(value, bool):
        raise StepFailed("a boolean is not a number")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, (int, str)):
        try:
            return Decimal(value.strip() if isinstance(value, str) else value)
        except InvalidOperation:
            raise StepFailed(f"{value!r} is not a number") from None
    raise StepFailed(f"{type(value).__name__} is not a number")


def _datetime(value: object, assume: str = "UTC") -> dt.datetime:
    """A value as an aware datetime: datetimes as given, ISO strings parsed, dates at midnight."""
    parsed = value if isinstance(value, dt.date) else parse_temporal(value, TemporalCast(tz=assume))
    if isinstance(parsed, dt.time):
        raise StepFailed("a time of day is not a timestamp")
    if parsed is None:
        raise StepFailed("a timestamp is required")
    moment = parsed if isinstance(parsed, dt.datetime) else dt.datetime.combine(parsed, dt.time())
    return moment if moment.tzinfo else localize(moment, TemporalCast(tz=assume))


# --- predicates -------------------------------------------------------------------------------


@_function("predicates", "value")
def is_null(value: object) -> bool:
    """True for null."""
    return value is None


@_function("predicates", "value")
def is_string(value: object) -> bool:
    """True for text."""
    return isinstance(value, str)


@_function("predicates", "value")
def is_number(value: object) -> bool:
    """True for an int, float or decimal (not a boolean)."""
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


@_function("predicates", "value")
def is_int(value: object) -> bool:
    """True for an integer (not a boolean)."""
    return isinstance(value, int) and not isinstance(value, bool)


@_function("predicates", "value")
def is_decimal(value: object) -> bool:
    """True for an exact decimal."""
    return isinstance(value, Decimal)


@_function("predicates", "value")
def is_bool(value: object) -> bool:
    """True for a boolean."""
    return isinstance(value, bool)


@_function("predicates", "value")
def is_datetime(value: object) -> bool:
    """True for a timestamp."""
    return isinstance(value, dt.datetime)


@_function("predicates", "value")
def is_date(value: object) -> bool:
    """True for a date (not a timestamp)."""
    return isinstance(value, dt.date) and not isinstance(value, dt.datetime)


@_function("predicates", "value")
def is_list(value: object) -> bool:
    """True for a list."""
    return isinstance(value, (list, tuple))


@_function("predicates", "value")
def is_dict(value: object) -> bool:
    """True for an object."""
    return isinstance(value, Mapping)


@_function("predicates", "value")
def is_blank(value: object) -> bool:
    """True for null or whitespace-only text."""
    return value is None or (isinstance(value, str) and not value.strip())


@_function("predicates", "pattern, value")
def matches(pattern: str, value: object) -> bool:
    """True when the regular expression is found in the value's text; false for null."""
    return value is not None and re.search(pattern, _text(value)) is not None


# --- coercion ---------------------------------------------------------------------------------


@_function("coercion", "value")
@_nullable
def to_int(value: object) -> int:
    """An integer; a fraction is an error ("12.0" is fine)."""
    number = _decimal(value)
    if number != number.to_integral_value():
        raise StepFailed(f"{value!r} has a fraction")
    return int(number)


@_function("coercion", "value")
@_nullable
def to_float(value: object) -> float:
    """A float."""
    return float(_decimal(value))


@_function("coercion", "value, precision=None, scale=None")
@_nullable
def to_decimal(value: object, precision: int | None = None, scale: int | None = None) -> Decimal:
    """An exact decimal, rounded half up to ``scale`` digits when given."""
    number = _decimal(value)
    if scale is not None:
        number = number.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
    if precision is not None and len(number.as_tuple().digits) > precision and number != 0:
        raise StepFailed(f"{number} has more than {precision} digits")
    return number


@_function("coercion", "value")
@_nullable
def to_bool(value: object) -> bool:
    """A boolean from true/false, yes/no, y/n, t/f, 1/0 or on/off (any case)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, Decimal)) and value in {0, 1}:
        return bool(value)
    text = _text(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise StepFailed(f"{value!r} is not a boolean")


@_function("coercion", "value")
@_nullable
def to_str(value: object) -> str:
    """Text: decimals in plain notation, temporals in ISO 8601, booleans as true/false."""
    return _text(value)


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time, uuid.UUID)):
        return _text(value)
    msg = f"{type(value).__name__} is not JSON"
    raise TypeError(msg)


@_function("coercion", "value")
def to_json(value: object) -> str:
    """JSON text (null becomes the text null)."""
    return json.dumps(value, ensure_ascii=False, default=_json_default)


@_function("coercion", "text")
@_nullable
def from_json(text: object) -> object:
    """The value of JSON text; fractions are exact decimals."""
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text, parse_float=Decimal)
    except json.JSONDecodeError as exc:
        raise StepFailed(f"not JSON: {exc.msg}") from None


# --- temporal ---------------------------------------------------------------------------------


@_function("temporal", 'value, *formats, tz="UTC"')
@_nullable
def parse_datetime(value: object, *formats: str, tz: str = "UTC") -> object:
    """A datetime from the formats tried in order (default iso); naive results are placed in tz."""
    options = TemporalCast(formats=formats or ("iso",), tz=tz)
    parsed = parse_temporal(value, options)
    if isinstance(parsed, dt.datetime) and parsed.tzinfo is None:
        return localize(parsed, options)
    return parsed


@_function("temporal", 'value, assume="UTC"')
@_nullable
def ensure_utc(value: object, assume: str = "UTC") -> dt.datetime:
    """A UTC datetime; naive values are taken to be in ``assume``."""
    return _datetime(value, assume).astimezone(dt.UTC)


@_function("temporal", "value, tz")
@_nullable
def to_tz(value: object, tz: str) -> dt.datetime:
    """The same instant in another zone."""
    return _datetime(value).astimezone(ZoneInfo(tz))


@_function("temporal", "")
def now_utc() -> dt.datetime:
    """The current time, in UTC."""
    return dt.datetime.now(tz=dt.UTC)


_UNITS = ("year", "month", "day", "hour", "minute", "second")


@_function("temporal", 'value, unit="day"')
@_nullable
def date_trunc(value: object, unit: str = "day") -> object:
    """The value truncated to year, month, day, hour, minute or second."""
    if unit not in _UNITS:
        raise StepFailed(f"unit must be one of {', '.join(_UNITS)}")
    if not isinstance(value, dt.date):
        value = _datetime(value)
    index = _UNITS.index(unit)
    month = 1 if index < _UNITS.index("month") else value.month
    day = 1 if index < _UNITS.index("day") else value.day
    if not isinstance(value, dt.datetime):  # a date
        return value.replace(month=month, day=day)
    return value.replace(
        month=month,
        day=day,
        hour=value.hour if index >= _UNITS.index("hour") else 0,
        minute=value.minute if index >= _UNITS.index("minute") else 0,
        second=value.second if index >= _UNITS.index("second") else 0,
        microsecond=0,
    )


@_function("temporal", "serial, system_1904=False")
@_nullable
def excel_date(serial: object, system_1904: bool = False) -> object:  # noqa: FBT001, FBT002 -- mirrors the format name
    """A naive datetime from a spreadsheet serial (1900 system with Lotus's leap-year bug)."""
    fmt = "excel_serial_1904" if system_1904 else "excel_serial"
    return parse_temporal(serial, TemporalCast(formats=(fmt,)))


@_function("temporal", 'number, unit="s"')
@_nullable
def from_epoch(number: object, unit: str = "s") -> object:
    """A UTC datetime from seconds (s), ms, us, ns since 1970, or auto by magnitude."""
    if unit not in {"s", "ms", "us", "ns", "auto"}:
        raise StepFailed("unit must be s, ms, us, ns or auto")
    return parse_temporal(number, TemporalCast(formats=(f"epoch_{unit}",)))


# --- text -------------------------------------------------------------------------------------


@_function("text", "pattern, replacement, value")
def re_sub(pattern: str, replacement: str, value: object) -> str | None:
    """Replace every match of the pattern."""
    return None if value is None else re.sub(pattern, replacement, _text(value))


@_function("text", "pattern, value")
def re_match(pattern: str, value: object) -> str | None:
    """The text matched at the start of the value, or null."""
    if value is None:
        return None
    match = re.match(pattern, _text(value))
    return match.group(0) if match else None


@_function("text", "pattern, value, group=1")
def re_extract(pattern: str, value: object, group: int | str = 1) -> str | None:
    """A group of the first match (the first group by default), or null."""
    if value is None:
        return None
    match = re.search(pattern, _text(value))
    if match is None:
        return None
    return match.group(group if match.re.groups else 0)


@_function("text", "value")
@_nullable
def lower(value: object) -> str:
    """Lowercase text."""
    return _text(value).lower()


@_function("text", "value")
@_nullable
def upper(value: object) -> str:
    """Uppercase text."""
    return _text(value).upper()


@_function("text", "value, chars=None")
@_nullable
def strip(value: object, chars: str | None = None) -> str:
    """Text without leading and trailing whitespace (or ``chars``)."""
    return _text(value).strip(chars)


@_function("text", "value, sep=None, maxsplit=-1")
@_nullable
def split(value: object, sep: str | None = None, maxsplit: int = -1) -> list[str]:
    """A list of parts."""
    return _text(value).split(sep, maxsplit)


@_function("text", 'items, sep=""')
@_nullable
def join(items: object, sep: str = "") -> str:
    """The items' text joined with ``sep``; null items are skipped."""
    if not isinstance(items, (list, tuple)):
        raise StepFailed("join needs a list")
    return sep.join(_text(item) for item in items if item is not None)


@_function("text", 'value, width, char=" "')
@_nullable
def pad_left(value: object, width: int, char: str = " ") -> str:
    """Text padded on the left to ``width`` characters."""
    if width > MAX_LENGTH:
        msg = f"a width over {MAX_LENGTH} is not allowed"
        raise SandboxError(msg)
    return _text(value).rjust(width, char)


# --- numeric ----------------------------------------------------------------------------------


@_function("numeric", "value, ndigits=None", name="round")
@_nullable
def fn_round(value: object, ndigits: int | None = None) -> object:
    """Round half away from zero; an int without ndigits, else the input's type."""
    exponent = Decimal(1).scaleb(-(ndigits or 0))
    rounded = _decimal(value).quantize(exponent, rounding=ROUND_HALF_UP)
    if ndigits is None:
        return int(rounded)
    return float(rounded) if isinstance(value, float) else rounded


@_function("numeric", "value")
@_nullable
def floor(value: object) -> int:
    """The largest integer not above the value."""
    return int(_decimal(value).to_integral_value(rounding=ROUND_FLOOR))


@_function("numeric", "value")
@_nullable
def ceil(value: object) -> int:
    """The smallest integer not below the value."""
    return int(_decimal(value).to_integral_value(rounding=ROUND_CEILING))


@_function("numeric", "value, low, high")
@_nullable
def clamp(value: Any, low: Any, high: Any) -> object:  # noqa: ANN401 -- any comparable
    """The value limited to [low, high]."""
    return max(low, min(high, value))


# --- misc -------------------------------------------------------------------------------------


@_function("misc", "*values")
def coalesce(*values: object) -> object:
    """The first non-null value."""
    return next((v for v in values if v is not None), None)


@_function("misc", "value, other")
def nullif(value: object, other: object) -> object:
    """Null when the value equals ``other``, else the value."""
    return None if value == other else value


@_function("misc", "text")
def md5(text: str) -> str:
    """The MD5 hex digest of the text (as the SDK's md5)."""
    return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()


@_function("misc", "text")
def sha256(text: str) -> str:
    """The SHA-256 hex digest of the text (as the SDK's sha256)."""
    return hashlib.sha256(text.encode()).hexdigest()


@_function("misc", "")
def uuid4() -> str:
    """A random UUID."""
    return str(uuid.uuid4())


@_function("misc", "namespace, name")
def uuid5(namespace: str, name: object) -> str:
    """A name-based UUID; the namespace is a UUID or one of dns, url, oid, x500."""
    space = _UUID_NAMESPACES.get(namespace) or uuid.UUID(namespace)
    return str(uuid.uuid5(space, _text(name)))


@_function("misc", "")
def rand() -> float:
    """A random float in [0, 1) (as simpleeval's rand)."""
    return random.random()  # noqa: S311 -- not for security


@_function("misc", "top")
def randint(top: int) -> int:
    """A random integer in [0, top) (as simpleeval's randint)."""
    return int(random.random() * top)  # noqa: S311 -- not for security


# --- Python builtins --------------------------------------------------------------------------

_PYTHON: dict[str, tuple[Callable[..., Any], str, str]] = {
    "int": (int, "value, base=10", "Python int (as in SDK stream maps)."),
    "float": (float, "value", "Python float (as in SDK stream maps)."),
    "str": (str, "value", "Python str (as in SDK stream maps)."),
    "bool": (bool, "value", "Python truthiness (as in SDK stream maps)."),
    "len": (len, "value", "Length of text or a list."),
    "abs": (abs, "value", "Absolute value."),
    "min": (min, "*values", "The smallest value."),
    "max": (max, "*values", "The largest value."),
    "sum": (sum, "items, start=0", "Sum of the items."),
    "any": (any, "items", "True if any item is truthy."),
    "all": (all, "items", "True if every item is truthy."),
    "sorted": (sorted, "items, reverse=False", "A sorted list (no key function)."),
    "list": (list, "items=()", "A new list."),
    "dict": (dict, "items=(), **kwargs", "A new dict."),
    "tuple": (tuple, "items=()", "A new tuple."),
    "set": (set, "items=()", "A new set."),
    "enumerate": (enumerate, "items, start=0", "(index, item) pairs."),
    "zip": (zip, "*lists", "Tuples of items in step."),
    "range": (safe_range, "stop | start, stop[, step]", "A range of at most 100000 integers."),
}
for _name, (_fn, _signature, _doc) in _PYTHON.items():
    _LIBRARY[_name] = Function(_name, _fn, "python", f"{_name}({_signature})", _doc)

for _name, _proxy in MODULES.items():
    _LIBRARY[_name] = Function(
        _name,
        _proxy,
        "modules",
        f"{_name}.<{', '.join(_proxy.names()[:6])}, ...>",
        f"The {_name} module, read-only.",
    )

FUNCTIONS: Mapping[str, Function] = MappingProxyType(dict(sorted(_LIBRARY.items())))
"""Every library function and module, by name."""
