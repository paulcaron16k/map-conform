"""JSON text with exact decimals (ADR-0007).

The Singer SDK decodes JSON numbers with fractions as ``Decimal``. The standard library can
only write a ``Decimal`` as a float, losing digits, or as a string, changing its JSON type.
:func:`dumps` writes it as the JSON number it came from: ``{"price": 3.14}`` stays
``{"price": 3.14}``, and ``0.1000000000000000055511`` keeps every digit.

NaN and infinities are not JSON numbers; like the SDK's serializer, they become ``null``.
Temporal values are written in ISO 8601 and UUIDs in canonical form.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import uuid
from decimal import Decimal
from typing import Any

_COMPACT = (",", ":")


def _plain(value: object, numbers: dict[str, str], token: str) -> object:  # noqa: PLR0911 -- one per kind
    """A copy with decimals replaced by unique placeholder strings, recorded in ``numbers``."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        key = f"{token}{len(numbers)}"
        numbers[key] = format(value, "f")  # plain notation: 1E+2 is 100
        return key
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _plain(v, numbers, token) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v, numbers, token) for v in value]
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def dumps(value: Any, *, compact: bool = False, sort_keys: bool = False) -> str:  # noqa: ANN401
    """JSON text for ``value``, with every ``Decimal`` written as an exact JSON number.

    Raises:
        TypeError: for a value JSON cannot represent.
    """
    numbers: dict[str, str] = {}
    token = f"\x00{uuid.uuid4().hex}:"
    plain = _plain(value, numbers, token)
    text = json.dumps(
        plain,
        ensure_ascii=False,
        sort_keys=sort_keys,
        separators=_COMPACT if compact else None,
        allow_nan=False,
    )
    for key, number in numbers.items():
        text = text.replace(json.dumps(key), number, 1)
    return text
