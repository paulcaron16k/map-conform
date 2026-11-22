"""Python values -> RECORD wire values (Clean-Landing Contract §3).

Casts produce Python values (``Decimal``, ``datetime``, ``UUID``, ``bytes``, parsed JSON);
the row executor encodes them for the RECORD message with :func:`to_wire`:

- ``timestamptz``: ``YYYY-MM-DDTHH:MM:SS.ffffffZ`` in UTC; ``timestamp``: the same without
  ``Z``; ``time``: ``HH:MM:SS.ffffff``; ``date``: ISO;
- ``decimal(p,s)``: a string with exactly ``s`` fraction digits, never an exponent;
- ``uuid``: lowercase with dashes; ``binary``: strict base64; ``json``: JSON text;
- ``struct`` / ``list``: their members encoded by the same rules.
"""

from __future__ import annotations

import base64
import datetime as dt
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from map_conform.types.jsontext import dumps

if TYPE_CHECKING:
    from map_conform.types.canonical import CType


def to_wire(value: object, ctype: CType) -> Any:  # noqa: ANN401, C901, PLR0911 -- JSON values
    """Encode a conformed value of ``ctype`` for a RECORD message."""
    if value is None:
        return None
    kind = ctype.kind
    if kind == "timestamptz" and isinstance(value, dt.datetime):
        return value.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if kind == "timestamp" and isinstance(value, dt.datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S.%f")
    if kind == "date" and isinstance(value, dt.date):
        return value.isoformat()
    if kind == "time" and isinstance(value, dt.time):
        return value.strftime("%H:%M:%S.%f")
    if kind == "decimal" and isinstance(value, Decimal):
        return format(value, "f")
    if kind == "uuid" and isinstance(value, uuid.UUID):
        return str(value)
    if kind == "binary" and isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if kind == "json":
        return dumps(value)
    if kind == "struct" and isinstance(value, dict):
        members = dict(ctype.members)
        return {k: to_wire(v, members[k]) if k in members else v for k, v in value.items()}
    if kind == "list" and isinstance(value, list):
        return [to_wire(v, ctype.list_item) for v in value]
    return value
