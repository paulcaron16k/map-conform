"""Casts to struct and list (declared nested types and ``nested: keep``).

The value is a mapping (struct) or a list, or JSON text holding one. Members are cast
recursively by their declared types with neutral options: nested values are data, so they are
not trimmed and have no null tokens; temporal members are ISO. Members missing from the value
are null; keys the struct does not declare are dropped, since the declared shape wins. The
executor renames nested keys to their conformed names before this cast runs.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from map_conform.errors import StepFailed
from map_conform.transforms import casts, numeric, temporal
from map_conform.transforms.registry import RAW, Registry, Transform
from map_conform.types.canonical import CType

if TYPE_CHECKING:
    from map_conform.plan.ops import CastArgs
    from map_conform.transforms.registry import Context

_NUMBER = numeric.NumberCast(trim=False)
_STRING = casts.StringCast(trim=False)
_BOOLEAN = casts.BooleanCast(trim=False)
_UUID = casts.UuidCast(trim=False)
_BINARY = casts.BinaryCast(trim=False)
_TEMPORAL = temporal.TemporalCast(trim=False)
_JSON = casts.JsonCast(parse_strings=False)

_MEMBER_CASTS: dict[str, tuple[Callable[..., Any], Any]] = {
    **dict.fromkeys(("int16", "int32", "int64"), (numeric.cast_int, _NUMBER)),
    **dict.fromkeys(("float32", "float64"), (numeric.cast_float, _NUMBER)),
    "decimal": (numeric.cast_decimal, _NUMBER),
    "string": (casts.cast_string, _STRING),
    "boolean": (casts.cast_boolean, _BOOLEAN),
    "uuid": (casts.cast_uuid, _UUID),
    "binary": (casts.cast_binary, _BINARY),
    "json": (casts.cast_json, _JSON),
    **dict.fromkeys(
        ("date", "time", "timestamp", "timestamptz"), (temporal.cast_temporal, _TEMPORAL)
    ),
}


@dataclass(frozen=True)
class NestedCast:
    """Options for casts to struct and list."""

    parse_strings: bool = True


@dataclass(frozen=True)
class _MemberArgs:
    target: CType
    options: Any


def cast_member(value: object, target: CType, ctx: Context) -> object:
    """Cast one nested value to its declared type."""
    if value is None:
        return None
    if target.kind in ("struct", "list"):
        return _cast_nested(value, target, ctx, parse_strings=False)
    caster, options = _MEMBER_CASTS[target.kind]
    return caster(value, _MemberArgs(target, options), ctx)


def _cast_nested(value: object, target: CType, ctx: Context, *, parse_strings: bool) -> object:
    if isinstance(value, str) and parse_strings:
        try:
            value = json.loads(value, parse_float=Decimal)
        except json.JSONDecodeError as exc:
            raise StepFailed(f"not JSON for a {target.kind}") from exc
    if target.kind == "struct":
        if not isinstance(value, Mapping):
            raise StepFailed(f"a struct needs an object, got {type(value).__name__}")
        out: dict[str, object] = {}
        for name, member in target.members:
            try:
                out[name] = cast_member(value.get(name), member, ctx)
            except StepFailed as exc:
                raise StepFailed(f"member {name!r}: {exc.reason}") from exc
        return out
    if not isinstance(value, list):
        raise StepFailed(f"a list needs an array, got {type(value).__name__}")
    item = target.list_item
    result: list[object] = []
    for index, element in enumerate(value):
        try:
            result.append(cast_member(element, item, ctx))
        except StepFailed as exc:
            raise StepFailed(f"item {index}: {exc.reason}") from exc
    return result


def cast_nested(value: object, args: CastArgs, ctx: Context) -> object:
    """Cast to a struct or list."""
    options: NestedCast = args.options
    return _cast_nested(value, args.target, ctx, parse_strings=options.parse_strings)


def register(registry: Registry) -> None:
    """Add the struct and list casts."""
    accepts = frozenset({RAW, "string", "json", "struct", "list"})
    transform = Transform("cast", cast_nested, kwargs=NestedCast, accepts=accepts)
    registry.register_cast({"struct", "list"}, transform)
