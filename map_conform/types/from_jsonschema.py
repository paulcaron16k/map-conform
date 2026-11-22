"""Tap SCHEMA property -> CType, for columns the spec does not declare (detailed design §4).

Rules, in order:

1. A recognised ``x-sql-datatype`` hint wins (``smallint``, ``numeric(10,2)``, ...).
2. ``anyOf``/``oneOf``: branches of one scalar type give that type; null plus one type gives
   that type; anything else is json, with a warning.
3. Several non-null ``type`` values: json, with a warning. No type at all: json.
4. ``integer``: int64, or int16/int32 when ``minimum``/``maximum`` fit.
5. ``number``: float64, unless ``x-singer.decimal`` or ``precision``/``scale`` make it a
   decimal.
6. ``string``: ``format`` date / time / date-time (timestamptz) / uuid / x-singer.decimal,
   ``contentEncoding: base64`` (binary), else string, bounded by ``maxLength``.
7. ``object`` / ``array``: struct / list with ``nested: keep`` when the shape is typed;
   otherwise json.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from map_conform.types.canonical import CType, CTypeError, parse_ctype

INT16 = (-(2**15), 2**15 - 1)
INT32 = (-(2**31), 2**31 - 1)
DEFAULT_DECIMAL = (38, 9)
"""Precision and scale for an x-singer.decimal that gives neither."""

_FORMATS: dict[str, CType] = {
    "date": CType("date"),
    "time": CType("time"),
    "date-time": CType("timestamptz"),
    "uuid": CType("uuid"),
}
_JSON = CType("json")


@dataclass(frozen=True)
class TapType:
    """The CType inferred for a tap property, its nullability and anything worth a warning."""

    ctype: CType
    nullable: bool
    warnings: tuple[str, ...] = field(default=())


def from_jsonschema(schema: Mapping[str, Any], nested: Literal["json", "keep"] = "json") -> TapType:
    """Infer the CType of one tap SCHEMA property."""
    warnings: list[str] = []
    ctype, nullable = _infer(schema, nested, warnings)
    return TapType(ctype, nullable, tuple(warnings))


def _types(schema: Mapping[str, Any]) -> list[str]:
    declared = schema.get("type")
    if declared is None:
        return []
    return [declared] if isinstance(declared, str) else list(declared)


def _infer(schema: Mapping[str, Any], nested: str, warnings: list[str]) -> tuple[CType, bool]:
    hint = schema.get("x-sql-datatype")
    if isinstance(hint, str):
        try:
            ctype = parse_ctype(hint)
        except CTypeError:
            warnings.append(f"ignored unrecognised x-sql-datatype {hint!r}")
        else:
            return ctype, "null" in _types(schema) or not _types(schema)
    branches = schema.get("anyOf") or schema.get("oneOf")
    if isinstance(branches, list):
        return _infer_branches(branches, nested, warnings)
    types = _types(schema)
    nullable = "null" in types or not types
    non_null = [t for t in types if t != "null"]
    if not non_null:
        return _JSON, True
    if len(non_null) > 1:
        warnings.append(f"several types {non_null}: kept as json")
        return _JSON, nullable
    return _infer_one(non_null[0], schema, nested, warnings), nullable


def _infer_branches(branches: list[Any], nested: str, warnings: list[str]) -> tuple[CType, bool]:
    nullable = False
    inferred: list[CType] = []
    for branch in branches:
        if not isinstance(branch, Mapping):
            continue
        if _types(branch) == ["null"]:
            nullable = True
            continue
        ctype, branch_nullable = _infer(branch, nested, [])
        nullable = nullable or branch_nullable
        inferred.append(ctype)
    kinds = {c.kind for c in inferred}
    if len(kinds) == 1:
        if len(set(inferred)) == 1:
            return inferred[0], nullable
        if kinds <= {"string"}:  # string(5) | string: the unbounded one covers both
            return CType("string"), nullable
    warnings.append("anyOf/oneOf of different types: kept as json")
    return _JSON, nullable


def _infer_one(kind: str, schema: Mapping[str, Any], nested: str, warnings: list[str]) -> CType:
    if kind in _SHAPES:
        return _SHAPES[kind](schema, nested, warnings)
    if kind in _VALUES:
        return _VALUES[kind](schema)
    warnings.append(f"unknown type {kind!r}: kept as json")
    return _JSON


def _number(schema: Mapping[str, Any]) -> CType:
    if schema.get("format") == "x-singer.decimal" or "precision" in schema or "scale" in schema:
        return _decimal(schema)
    return CType("float64")


def _integer(schema: Mapping[str, Any]) -> CType:
    low, high = schema.get("minimum"), schema.get("maximum")
    if isinstance(low, int) and isinstance(high, int):
        if INT16[0] <= low and high <= INT16[1]:
            return CType("int16")
        if INT32[0] <= low and high <= INT32[1]:
            return CType("int32")
    return CType("int64")


def _decimal(schema: Mapping[str, Any]) -> CType:
    precision = schema.get("precision", DEFAULT_DECIMAL[0])
    scale = schema.get("scale", DEFAULT_DECIMAL[1] if "precision" not in schema else 0)
    return CType("decimal", precision=precision, scale=scale)


def _string(schema: Mapping[str, Any]) -> CType:
    fmt = schema.get("format")
    if fmt == "x-singer.decimal":
        return _decimal(schema)
    if isinstance(fmt, str) and fmt in _FORMATS:
        return _FORMATS[fmt]
    if schema.get("contentEncoding") == "base64":
        return CType("binary")
    length = schema.get("maxLength")
    if isinstance(length, int) and length > 0:
        return CType("string", length=length)
    return CType("string")


def _object(schema: Mapping[str, Any], nested: str, warnings: list[str]) -> CType:
    properties = schema.get("properties")
    if nested != "keep" or not isinstance(properties, Mapping) or not properties:
        return _JSON
    members = tuple((name, _infer(prop, nested, warnings)[0]) for name, prop in properties.items())
    return CType("struct", members=members)


def _array(schema: Mapping[str, Any], nested: str, warnings: list[str]) -> CType:
    items = schema.get("items")
    if nested != "keep" or not isinstance(items, Mapping):
        return _JSON
    return CType("list", item=_infer(items, nested, warnings)[0])


_VALUES: dict[str, Callable[[Mapping[str, Any]], CType]] = {
    "boolean": lambda _: CType("boolean"),
    "integer": _integer,
    "number": _number,
    "string": _string,
}
_SHAPES: dict[str, Callable[[Mapping[str, Any], str, list[str]], CType]] = {
    "object": _object,
    "array": _array,
}
