r"""Compare SDK and map-conform output, allowing only the documented, deliberate differences.

map-conform differs from the SDK mapper on purpose in how values are *written*, never in
what they are (detailed design §15):

1. Timestamps are canonical UTC with microseconds (``2022-01-01T00:00:00.000000Z``); the
   SDK passes the tap's text through (``2022-01-01T00:00:00Z``). The instant is the same.
2. Numbers the tap declares as JSON numbers are exact decimals written as strings with
   ``x-singer.decimal`` (ADR-0007); the SDK writes them as JSON numbers.
3. A value whose type is not a typed struct or list (an untyped object, a ``oneOf`` member)
   is JSON text (ADR-0007): ``"abc"`` is written ``"\"abc\""``; the SDK writes the value.
4. SCHEMAs carry more: integer bounds, ``x-sql-datatype``, decimal precision. Property names,
   key properties and each property's JSON type family are compared.
5. Column names follow the SDK's ``conform_name`` in compatibility mode: the names an SDK SQL
   target creates. ``user.id`` (flattened with ``.``) lands as ``user_id``; the SDK mapper
   leaves that renaming to the target.
6. Every record carries every SCHEMA property, null when the tap left it out; the SDK mapper
   passes the record's own keys.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from singer_sdk.sql.sink import SQLSink


def _instant(value: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def normal(value: Any) -> Any:  # noqa: ANN401, C901, PLR0911 -- one branch per kind
    """A comparable form: decimals by value, instants as instants, JSON text decoded."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value)).normalize()
    if isinstance(value, dt.datetime):
        return value.astimezone(dt.UTC)
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: normal(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normal(v) for v in value]
    if isinstance(value, str):
        if value in {"true", "false", "null"}:  # JSON text of a scalar (difference 3)
            return json.loads(value)
        if (instant := _instant(value)) is not None:
            return instant.astimezone(dt.UTC)
        try:
            return Decimal(value).normalize() if value.strip() else value
        except InvalidOperation:
            pass
        if value[:1] in '[{"':
            try:
                return normal(json.loads(value, parse_float=Decimal))
            except json.JSONDecodeError:
                return value
    return value


def family(schema: dict[str, Any]) -> str:
    """A property's JSON type family; x-singer.decimal strings are numbers."""
    if "anyOf" in schema or "oneOf" in schema:
        return "any"
    types = schema.get("type", [])
    types = {types} if isinstance(types, str) else set(types)
    types.discard("null")
    if schema.get("format") == "x-singer.decimal":
        return "number"
    if schema.get("x-sql-datatype") == "json" or types == {"object", "array"}:
        return "json"
    return "/".join(sorted(types)) or "any"


def sdk_name(name: str) -> str:
    """What the SDK pipeline names a column in the end: its SQL target's conform_name."""
    return SQLSink.conform_name(cast("SQLSink", None), name)


def comparable_sdk_record(record: dict[str, Any], columns: list[str]) -> dict[str, Any]:
    """An SDK record as map-conform writes it: target names, every column (null if absent)."""
    renamed = {sdk_name(k): normal(v) for k, v in record.items()}
    return {column: renamed.get(column) for column in columns}
