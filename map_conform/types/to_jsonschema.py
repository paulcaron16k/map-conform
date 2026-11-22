"""CType -> canonical JSON Schema property: the Clean-Landing Contract's SCHEMA (§4 table).

Decimals are strings with ``format: x-singer.decimal`` and their precision and scale (few
targets honour ``x-sql-datatype``); json is JSON text; struct and list are typed objects and
arrays. ``x-sql-datatype`` is emitted as a hint where the table lists one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from map_conform.types.from_jsonschema import INT16, INT32

if TYPE_CHECKING:
    from map_conform.types.canonical import CType

INT64 = (-(2**63), 2**63 - 1)

_SCALARS: dict[str, dict[str, Any]] = {
    "boolean": {"type": "boolean"},
    "int16": {"type": "integer", "minimum": INT16[0], "maximum": INT16[1],
              "x-sql-datatype": "smallint"},
    "int32": {"type": "integer", "minimum": INT32[0], "maximum": INT32[1],
              "x-sql-datatype": "integer"},
    "int64": {"type": "integer", "minimum": INT64[0], "maximum": INT64[1],
              "x-sql-datatype": "bigint"},
    "float32": {"type": "number", "x-sql-datatype": "real"},
    "float64": {"type": "number", "x-sql-datatype": "double precision"},
    "date": {"type": "string", "format": "date"},
    "time": {"type": "string", "format": "time"},
    "timestamp": {"type": "string", "format": "date-time", "x-sql-datatype": "timestamp"},
    "timestamptz": {"type": "string", "format": "date-time", "x-sql-datatype": "timestamptz"},
    "uuid": {"type": "string", "format": "uuid"},
    "binary": {"type": "string", "contentEncoding": "base64"},
    "json": {"type": "string", "x-sql-datatype": "json"},
}  # fmt: skip


def to_jsonschema(ctype: CType, *, nullable: bool = True) -> dict[str, Any]:
    """The contract's JSON Schema property for ``ctype``."""
    schema: dict[str, Any]
    if ctype.kind in _SCALARS:
        schema = dict(_SCALARS[ctype.kind])
    elif ctype.kind == "decimal":
        precision, scale = ctype.decimal_params
        schema = {
            "type": "string",
            "format": "x-singer.decimal",
            "precision": precision,
            "scale": scale,
        }
    elif ctype.kind == "string":
        schema = {"type": "string"}
        if ctype.length is not None:
            schema["maxLength"] = ctype.length
    elif ctype.kind == "struct":
        schema = {
            "type": "object",
            "properties": {name: to_jsonschema(member) for name, member in ctype.members},
        }
    else:
        schema = {"type": "array", "items": to_jsonschema(ctype.list_item)}
    if nullable:
        schema["type"] = [schema["type"], "null"]
    return schema
