"""Privacy builtins: hash, mask, set_null, redact_date (detailed design §6.4, WBS 5.6).

These follow pipelinewise-transform-field's semantics, minus its bugs:

- ``HASH`` is ``hash``; ``HASH-SKIP-FIRST-n`` is ``{hash: {skip_first: n}}`` for any n,
  where pipelinewise reads a single digit;
- ``MASK-DATE`` is ``{redact_date: {to: year}}`` and keeps the column's type;
- ``MASK-STRING-SKIP-ENDS-n`` is ``{mask: {keep_first: n, keep_last: n}}``, and a value too
  short to show both ends is masked entirely rather than shown;
- ``SET-NULL`` is ``set_null``, which also makes the column nullable in the SCHEMA.

A typed value is hashed in a canonical text form (ISO dates, plain decimals), so the hash
does not depend on Python's repr.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from map_conform.errors import StepFailed
from map_conform.transforms.registry import ANY, RAW, NoKwargs, Registry, Transform
from map_conform.types.canonical import CType

if TYPE_CHECKING:
    from map_conform.transforms.registry import Context


@dataclass(frozen=True)
class HashKwargs:
    """A hex digest of the value, optionally keeping the first characters readable."""

    algo: Literal["sha256", "md5", "sha1", "sha512"] = "sha256"
    salt: str = ""
    skip_first: int = 0


@dataclass(frozen=True)
class MaskKwargs:
    """Mask the middle of a string."""

    keep_first: int = 0
    keep_last: int = 0
    char: str = "*"


@dataclass(frozen=True)
class RedactDateKwargs:
    """Keep only the year (or year and month) of a date or timestamp."""

    to: Literal["year", "month"] = "year"


def _canonical_text(value: object) -> str:
    """A stable text form of a value, raw or typed, for hashing."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    return str(value)


def _hash(value: object, k: HashKwargs, _ctx: Context) -> object:
    if k.skip_first < 0:
        raise StepFailed("skip_first must not be negative")
    text = _canonical_text(value)
    head, tail = text[: k.skip_first], text[k.skip_first :]
    digest = hashlib.new(k.algo, (k.salt + tail).encode("utf-8")).hexdigest()
    return head + digest


def _mask(value: object, k: MaskKwargs, _ctx: Context) -> object:
    if len(k.char) != 1:
        raise StepFailed("char must be one character")
    if k.keep_first < 0 or k.keep_last < 0:
        raise StepFailed("keep_first and keep_last must not be negative")
    text = value if isinstance(value, str) else str(value)
    if len(text) <= k.keep_first + k.keep_last:
        return k.char * len(text)
    end = len(text) - k.keep_last
    return text[: k.keep_first] + k.char * (end - k.keep_first) + text[end:]


def _redact_date(value: object, k: RedactDateKwargs, _ctx: Context) -> object:
    if isinstance(value, dt.datetime):
        month = value.month if k.to == "month" else 1
        return value.replace(month=month, day=1, hour=0, minute=0, second=0, microsecond=0)
    if isinstance(value, dt.date):
        return value.replace(month=value.month if k.to == "month" else 1, day=1)
    raise StepFailed(f"redact_date needs a date or timestamp, got {type(value).__name__}")


def register(registry: Registry) -> None:
    """Add the privacy builtins."""
    registry.register(
        Transform(
            "hash",
            _hash,
            kwargs=HashKwargs,
            positional="algo",
            accepts=frozenset({ANY}),
            produces=lambda _stage, _k: CType("string"),
        )
    )
    registry.register(
        Transform("mask", _mask, kwargs=MaskKwargs, accepts=frozenset({RAW, "string"}))
    )
    registry.register(
        Transform(
            "set_null",
            lambda _v, _k, _c: None,
            kwargs=NoKwargs,
            accepts=frozenset({ANY}),
            forces_nullable=True,
        )
    )
    registry.register(
        Transform(
            "redact_date",
            _redact_date,
            kwargs=RedactDateKwargs,
            positional="to",
            accepts=frozenset({"date", "timestamp", "timestamptz"}),
        )
    )
