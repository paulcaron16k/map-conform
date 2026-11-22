"""CType -> Arrow data type (detailed design §4, ADR-0011).

``uuid`` is the ``arrow.uuid`` extension type, which parquet stores as
``fixed_len_byte_array(16)`` with the UUID logical type; ``uuid_as="string"`` gives plain
strings for readers without that support. Decimals up to 38 digits are decimal128, wider
ones decimal256. json is its JSON text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import pyarrow as pa

if TYPE_CHECKING:
    from map_conform.types.canonical import CType

DECIMAL128_MAX = 38

_SCALARS: dict[str, pa.DataType] = {
    "boolean": pa.bool_(),
    "int16": pa.int16(),
    "int32": pa.int32(),
    "int64": pa.int64(),
    "float32": pa.float32(),
    "float64": pa.float64(),
    "string": pa.string(),
    "date": pa.date32(),
    "time": pa.time64("us"),
    "timestamp": pa.timestamp("us"),
    "timestamptz": pa.timestamp("us", tz="UTC"),
    "binary": pa.binary(),
    "json": pa.string(),
}


def to_arrow(ctype: CType, *, uuid_as: Literal["uuid", "string"] = "uuid") -> pa.DataType:
    """The Arrow type that holds values of ``ctype``."""
    if ctype.kind in _SCALARS:
        return _SCALARS[ctype.kind]
    if ctype.kind == "uuid":
        return pa.uuid() if uuid_as == "uuid" else pa.string()
    if ctype.kind == "decimal":
        precision, scale = ctype.decimal_params
        if precision <= DECIMAL128_MAX:
            return pa.decimal128(precision, scale)
        return pa.decimal256(precision, scale)
    if ctype.kind == "struct":
        return pa.struct(
            [pa.field(name, to_arrow(member, uuid_as=uuid_as)) for name, member in ctype.members]
        )
    return pa.list_(to_arrow(ctype.list_item, uuid_as=uuid_as))
