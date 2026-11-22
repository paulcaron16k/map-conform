"""Conformed rows as Arrow data, with the plan's declared schema (detailed design §10.2).

Rows reach this module in their wire form, the exact values a RECORD message carries, so a
BATCH file holds the same data as the RECORD path would. Each wire value is turned back into
the Python value its Arrow type takes: exact decimals, temporals, UUID bytes, binary bytes,
and structs and lists member by member.
"""

from __future__ import annotations

import base64
import datetime as dt
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pyarrow as pa

from map_conform.metadata import INTEGER_COLUMNS, TIMESTAMP_COLUMNS
from map_conform.types.canonical import CType
from map_conform.types.to_arrow import to_arrow

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from map_conform.plan.compile import StreamPlan

_TIMESTAMPTZ = CType("timestamptz")
_INT64 = CType("int64")


def _parse(kind: str) -> Callable[[Any], Any]:
    parsers: dict[str, Callable[[Any], Any]] = {
        "decimal": Decimal,
        "date": dt.date.fromisoformat,
        "time": dt.time.fromisoformat,
        "timestamp": dt.datetime.fromisoformat,
        "timestamptz": dt.datetime.fromisoformat,
        "uuid": lambda v: uuid.UUID(v).bytes,
        "binary": base64.b64decode,
    }
    return parsers.get(kind, lambda v: v)


def arrow_value(value: object, ctype: CType) -> object:
    """A wire value as the Python value its Arrow type takes."""
    if value is None:
        return None
    if ctype.kind == "struct" and isinstance(value, dict):
        members = dict(ctype.members)
        return {name: arrow_value(value.get(name), member) for name, member in members.items()}
    if ctype.kind == "list" and isinstance(value, list):
        return [arrow_value(v, ctype.list_item) for v in value]
    return _parse(ctype.kind)(value)


def output_columns(plan: StreamPlan, *, metadata: bool) -> list[tuple[str, CType, bool]]:
    """(name, CType, nullable) of every output column, ``_sdc_*`` last when added."""
    columns = [(c.name, c.ctype, c.nullable) for c in plan.columns]
    if metadata:
        columns += [(name, _TIMESTAMPTZ, True) for name in TIMESTAMP_COLUMNS]
        columns += [(name, _INT64, True) for name in INTEGER_COLUMNS]
    return columns


def arrow_schema(columns: Sequence[tuple[str, CType, bool]]) -> pa.Schema:
    """The declared Arrow schema: ``to_arrow`` of each column."""
    return pa.schema([pa.field(n, to_arrow(t), nullable=nullable) for n, t, nullable in columns])


def to_table(
    rows: Sequence[Mapping[str, Any]], columns: Sequence[tuple[str, CType, bool]]
) -> pa.Table:
    """Wire rows as a table with exactly the declared schema."""
    schema = arrow_schema(columns)
    arrays = [
        pa.array([arrow_value(row.get(name), ctype) for row in rows], type=field.type)
        for (name, ctype, _), field in zip(columns, schema, strict=True)
    ]
    return pa.Table.from_arrays(arrays, schema=schema)
