"""Casts to string, boolean, uuid, binary and json (detailed design §6.4).

Every cast from a raw value first applies the value cleanup from the stream's ``values``
defaults (or the column's overrides): trim strings, then turn null tokens into null. For a
string column, ``""`` follows ``empty_string_for_string`` instead of the null tokens.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal

from map_conform.errors import StepFailed
from map_conform.transforms.registry import RAW, Registry, Transform

if TYPE_CHECKING:
    from map_conform.plan.chain import CastArgs
    from map_conform.spec.model import ColumnSpec, Defaults
    from map_conform.transforms.registry import Context

_EMPTY = object()
"""Returned by :func:`clean` for a string column's empty string kept as empty."""


@dataclass(frozen=True)
class Cleanup:
    """The value cleanup every cast from a raw value applies."""

    trim: bool = True
    null_tokens: tuple[str, ...] = ()
    null_tokens_case_sensitive: bool = False


def cleanup_defaults(settings: Defaults, column: ColumnSpec | None) -> dict[str, Any]:
    """Cleanup options from the stream defaults, overridden by the column."""
    values = settings.values
    return {
        "trim": column.trim if column and column.trim is not None else values.trim,
        "null_tokens": list(
            column.null_tokens if column and column.null_tokens is not None else values.null_tokens
        ),
        "null_tokens_case_sensitive": values.null_tokens_case_sensitive,
    }


def clean(value: object, options: Cleanup, *, keep_empty: bool = False) -> object:
    """Trim a string and map null tokens to None; non-strings pass through."""
    if not isinstance(value, str):
        return value
    text = value.strip() if options.trim else value
    if text == "" and keep_empty:
        return _EMPTY
    if options.null_tokens_case_sensitive:
        return None if text in options.null_tokens else text
    folded = text.casefold()
    return None if any(folded == t.casefold() for t in options.null_tokens) else text


# --- string ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class StringCast(Cleanup):
    """Options for casts to string."""

    empty_string_for_string: Literal["keep", "null"] = "keep"
    max_length: int | None = None
    on_overflow: Literal["truncate", "error"] = "error"


def _string_defaults(settings: Defaults, column: ColumnSpec | None) -> dict[str, Any]:
    out = cleanup_defaults(settings, column)
    out["empty_string_for_string"] = settings.values.empty_string_for_string
    if column is not None:
        out["max_length"] = column.max_length
        out["on_overflow"] = column.on_overflow
    return out


def cast_string(value: object, args: CastArgs, _ctx: Context) -> object:
    """Cast to string: scalars become their text; containers are refused."""
    options: StringCast = args.options
    cleaned = clean(value, options, keep_empty=options.empty_string_for_string == "keep")
    if cleaned is _EMPTY:
        return ""
    if cleaned is None:
        return None
    if isinstance(cleaned, bool):
        text = "true" if cleaned else "false"
    elif isinstance(cleaned, (int, float, Decimal)):
        text = str(cleaned)
    elif isinstance(cleaned, str):
        text = cleaned
    else:
        raise StepFailed(f"a string column got {type(cleaned).__name__}; declare it json")
    limit = args.target.length if args.target.length is not None else options.max_length
    if limit is not None and len(text) > limit:
        if options.on_overflow == "error":
            raise StepFailed(f"{len(text)} characters is longer than {limit}")
        text = text[:limit]
    return text


# --- boolean --------------------------------------------------------------------------------


@dataclass(frozen=True)
class BooleanCast(Cleanup):
    """Options for casts to boolean."""

    true_values: tuple[str, ...] = ("true",)
    false_values: tuple[str, ...] = ("false",)
    case_sensitive: bool = False


def _boolean_defaults(settings: Defaults, column: ColumnSpec | None) -> dict[str, Any]:
    out = cleanup_defaults(settings, column)
    out["true_values"] = list(
        column.true_values if column and column.true_values else settings.boolean.true_values
    )
    out["false_values"] = list(
        column.false_values if column and column.false_values else settings.boolean.false_values
    )
    return out


def cast_boolean(value: object, args: CastArgs, _ctx: Context) -> object:
    """Cast to boolean: listed words, real booleans, and the numbers 0 and 1."""
    options: BooleanCast = args.options
    cleaned = clean(value, options)
    if cleaned is None or isinstance(cleaned, bool):
        return cleaned
    if isinstance(cleaned, (int, float, Decimal)):
        if cleaned in (0, 1):
            return cleaned == 1
        raise StepFailed("only the numbers 0 and 1 are booleans")
    if not isinstance(cleaned, str):
        raise StepFailed(f"{type(cleaned).__name__} is not a boolean")
    if options.case_sensitive:
        if cleaned in options.true_values:
            return True
        if cleaned in options.false_values:
            return False
    else:
        folded = cleaned.casefold()
        if any(folded == t.casefold() for t in options.true_values):
            return True
        if any(folded == f.casefold() for f in options.false_values):
            return False
    raise StepFailed("not one of the true_values or false_values")


# --- uuid -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class UuidCast(Cleanup):
    """Options for casts to uuid."""

    version: int | None = None


def cast_uuid(value: object, args: CastArgs, _ctx: Context) -> object:
    """Cast to uuid: braces, missing dashes and capitals are accepted."""
    options: UuidCast = args.options
    cleaned = clean(value, options)
    if cleaned is None or isinstance(cleaned, uuid.UUID):
        return cleaned
    try:
        parsed = uuid.UUID(str(cleaned))
    except ValueError as exc:
        raise StepFailed("not a UUID") from exc
    if options.version is not None and parsed.version != options.version:
        raise StepFailed(f"a version {parsed.version} UUID, not version {options.version}")
    return parsed


# --- binary ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class BinaryCast(Cleanup):
    """Options for casts to binary."""

    encoding: Literal["base64", "hex", "utf8"] = "base64"


def cast_binary(value: object, args: CastArgs, _ctx: Context) -> object:
    """Cast to binary from strict base64, hex or UTF-8 text."""
    options: BinaryCast = args.options
    cleaned = clean(value, options)
    if cleaned is None or isinstance(cleaned, bytes):
        return cleaned
    text = str(cleaned)
    try:
        if options.encoding == "base64":
            return base64.b64decode(text, validate=True)
        if options.encoding == "hex":
            return bytes.fromhex(text)
    except (binascii.Error, ValueError) as exc:
        raise StepFailed(f"not valid {options.encoding}") from exc
    return text.encode("utf-8")


# --- json -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class JsonCast:
    """Options for casts to json (no value cleanup: text is data here)."""

    parse_strings: bool = True
    sort_keys: bool = False
    null_tokens: tuple[str, ...] = field(default=())


def cast_json(value: object, args: CastArgs, _ctx: Context) -> object:
    """Cast to json: text that is already JSON is decoded, not encoded twice.

    Decimals stay exact; the value is encoded as JSON text on the wire.
    """
    options: JsonCast = args.options
    if isinstance(value, str):
        if value in options.null_tokens:
            return None
        if options.parse_strings:
            try:
                value = json.loads(value, parse_float=Decimal)
            except json.JSONDecodeError:
                return value
    if options.sort_keys and isinstance(value, dict):
        return dict(sorted(value.items()))
    return value


def register(registry: Registry) -> None:
    """Add these casts."""
    registry.register_cast({"string"}, Transform(
        "cast", cast_string, kwargs=StringCast, defaults=_string_defaults,
        accepts=frozenset({RAW, "string", "boolean", "int16", "int32", "int64", "float32",
                           "float64", "decimal", "uuid"}),
    ))  # fmt: skip
    registry.register_cast({"boolean"}, Transform(
        "cast", cast_boolean, kwargs=BooleanCast, defaults=_boolean_defaults,
        accepts=frozenset({RAW, "string", "boolean"}),
    ))  # fmt: skip
    registry.register_cast({"uuid"}, Transform(
        "cast", cast_uuid, kwargs=UuidCast, defaults=cleanup_defaults,
        accepts=frozenset({RAW, "string", "uuid"}),
    ))  # fmt: skip
    registry.register_cast({"binary"}, Transform(
        "cast", cast_binary, kwargs=BinaryCast, defaults=cleanup_defaults,
        accepts=frozenset({RAW, "string", "binary"}),
    ))  # fmt: skip
    registry.register_cast({"json"}, Transform(
        "cast", cast_json, kwargs=JsonCast, accepts=frozenset({RAW, "string", "json"}),
    ))  # fmt: skip
