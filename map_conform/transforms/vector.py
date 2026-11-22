"""Arrow implementations of the vectorisable builtins (detailed design §10.2, WBS 8.4).

A vector op takes the whole column and returns ``(result, todo)``. ``todo`` marks the rows
the op does not compute itself; the executor sends those through the scalar chain, so every
row gets exactly the scalar result (the *splice*, WBS 8.5). An op claims a row only when its
Arrow kernel is known to agree with the scalar code there, so it never fails: anything that
would be an error, or that needs the full grammar, is left to the scalar path.

The common case is claimed, the rest is spliced:

- **Text** ops claim rows of printable ASCII (plus tab, newline, carriage return), where
  Arrow's string kernels and Python's ``str`` methods agree; other rows go row-wise.
- **Numeric casts** claim plain numbers (``-12``, ``3.50``) under the default grammar
  (``us`` locale, no separators set) and integer, float or decimal input; currency,
  separators, parentheses, percent and locales go row-wise.
- **Boolean casts** claim the configured true/false tokens and boolean input.
- **Temporal casts** to timestamptz, timestamp and date whose first format is ``iso`` and
  whose zone is UTC claim strict ISO 8601 text (date, or date and time to the second) and
  Arrow timestamps.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pyarrow as pa
import pyarrow.compute as _compute

from map_conform.transforms.numeric import INT_BOUNDS
from map_conform.types.canonical import CType
from map_conform.types.to_arrow import to_arrow

Vector = Callable[[pa.Array, Any, CType], tuple[pa.Array, pa.Array]]
"""``(column, kwargs, column type) -> (result, todo mask)``."""

_SAFE = r"^[\x20-\x7e\t\n\r]*$"
_INTEGER = r"^[+-]?[0-9]{1,18}$"
_DECIMAL = r"^[+-]?[0-9]{1,20}(\.[0-9]{1,18})?$"
_FLOAT = r"^[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][+-]?[0-9]+)?$"
_ISO = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}([T ][0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?"
    r"(Z|z|[+-][0-9]{2}:[0-9]{2})?)?$"
)
_ZONED = r"(Z|z|[+-][0-9]{2}:[0-9]{2})$"

# The pyarrow stubs type compute kernels as returning unions of arrays, chunked arrays and
# scalars, so array-in, array-out code cannot be checked through them. The parity suite
# (tests/parity) checks this module against the scalar path instead.
_pa: Any = pa
pc: Any = _compute


# --- masks --------------------------------------------------------------------------------------


def _bool(mask: pa.Array, *, null: bool = False) -> pa.Array:
    return pc.fill_null(mask, null)


def everything(column: pa.Array) -> pa.Array:
    """Every non-null row is todo (for input types an op does not handle)."""
    return pc.is_valid(column)


def _strings(column: pa.Array) -> bool:
    return pa.types.is_string(column.type) or pa.types.is_large_string(column.type)


def unsafe_text(column: pa.Array) -> pa.Array:
    """Rows that are not plain printable ASCII (nulls are safe)."""
    return pc.invert(_bool(pc.match_substring_regex(column, _SAFE), null=True))


def _or(*masks: pa.Array) -> pa.Array:
    out = masks[0]
    for mask in masks[1:]:
        out = pc.or_(out, mask)
    return out


def _text_op(
    fn: Callable[[pa.Array], pa.Array],
) -> Callable[[pa.Array], tuple[pa.Array, pa.Array]]:
    def run(column: pa.Array) -> tuple[pa.Array, pa.Array]:
        if not _strings(column):
            return _pa.nulls(len(column), pa.string()), everything(column)
        return fn(column), unsafe_text(column)

    return run


# --- text ---------------------------------------------------------------------------------------


def _ascii(chars: str | None) -> bool:
    return chars is None or all(" " <= c <= "~" for c in chars)


def trim(column: pa.Array, k: Any, _t: CType) -> tuple[pa.Array, pa.Array]:
    """``trim``: whitespace, or the given characters."""
    if not _ascii(k.chars):
        return _pa.nulls(len(column), pa.string()), everything(column)
    kernel = (
        pc.utf8_trim_whitespace
        if k.chars is None
        else (lambda c: pc.utf8_trim(c, characters=k.chars))
    )
    return _text_op(kernel)(column)


def strip_chars(column: pa.Array, k: Any, _t: CType) -> tuple[pa.Array, pa.Array]:
    """``strip_chars``: the listed characters from both ends."""
    if not _ascii(k.chars):
        return _pa.nulls(len(column), pa.string()), everything(column)
    return _text_op(lambda c: pc.utf8_trim(c, characters=k.chars))(column)


def lower(column: pa.Array, _k: Any, _t: CType) -> tuple[pa.Array, pa.Array]:
    """``lower`` on ASCII text."""
    return _text_op(pc.ascii_lower)(column)


def upper(column: pa.Array, _k: Any, _t: CType) -> tuple[pa.Array, pa.Array]:
    """``upper`` on ASCII text."""
    return _text_op(pc.ascii_upper)(column)


def left(column: pa.Array, k: Any, _t: CType) -> tuple[pa.Array, pa.Array]:
    """``left``: the first n characters."""
    if k.n < 0:
        return _pa.nulls(len(column), pa.string()), everything(column)
    return _text_op(lambda c: pc.utf8_slice_codeunits(c, 0, k.n))(column)


def right(column: pa.Array, k: Any, _t: CType) -> tuple[pa.Array, pa.Array]:
    """``right``: the last n characters."""
    if k.n <= 0:
        return _pa.nulls(len(column), pa.string()), everything(column)
    return _text_op(lambda c: pc.utf8_slice_codeunits(c, -k.n, 2**31 - 1))(column)


def set_null(column: pa.Array, _k: Any, _t: CType) -> tuple[pa.Array, pa.Array]:
    """``set_null``: every row null."""
    return _pa.nulls(len(column), column.type), _pa.repeat(_pa.scalar(False), len(column))  # noqa: FBT003


def _null_tokens(text: pa.Array, tokens: tuple[str, ...], *, case_sensitive: bool) -> pa.Array:
    """Rows equal to a token (ASCII rows; the caller sends the others row-wise)."""
    if not tokens:
        return _pa.repeat(_pa.scalar(False), len(text))  # noqa: FBT003
    if case_sensitive:
        return _bool(pc.is_in(text, value_set=_pa.array(tokens)))
    folded = _pa.array([t.casefold() for t in tokens])
    return _bool(pc.is_in(pc.ascii_lower(text), value_set=folded))


def null_tokens(column: pa.Array, k: Any, _t: CType) -> tuple[pa.Array, pa.Array]:
    """``null_tokens``: null for any token, the value otherwise."""
    if not _strings(column) or not all(_ascii(t) for t in k.tokens):
        return _pa.nulls(len(column), pa.string()), everything(column)
    hit = _null_tokens(column, k.tokens, case_sensitive=k.case_sensitive)
    return pc.if_else(hit, _pa.scalar(None, pa.string()), column), unsafe_text(column)


# --- cleanup shared by casts ------------------------------------------------------------------


def _clean(column: pa.Array, options: Any) -> tuple[pa.Array, pa.Array]:
    """Trim and null tokens, as ``casts.clean`` does; non-ASCII rows are todo."""
    text = pc.utf8_trim_whitespace(column) if options.trim else column
    if not all(_ascii(t) for t in options.null_tokens):
        return text, everything(column)
    hit = _null_tokens(text, options.null_tokens, case_sensitive=options.null_tokens_case_sensitive)
    return pc.if_else(hit, _pa.scalar(None, pa.string()), text), unsafe_text(column)


def _matches(column: pa.Array, pattern: str) -> pa.Array:
    return _bool(pc.match_substring_regex(column, pattern))


# --- casts ----------------------------------------------------------------------------------------


def cast_string(column: pa.Array, args: Any, target: CType) -> tuple[pa.Array, pa.Array]:
    """Cast to string from text: cleanup, empty strings, length limits."""
    options = args.options
    if not _strings(column):
        return _pa.nulls(len(column), pa.string()), everything(column)
    trimmed = pc.utf8_trim_whitespace(column) if options.trim else column
    empty = _bool(pc.equal(trimmed, ""))
    cleaned, todo = _clean(column, options)
    if options.empty_string_for_string == "keep":
        cleaned = pc.if_else(empty, _pa.scalar(""), cleaned)
    else:
        cleaned = pc.if_else(empty, _pa.scalar(None, pa.string()), cleaned)
    limit = target.length if target.length is not None else options.max_length
    if limit is not None:
        too_long = _bool(pc.greater(pc.utf8_length(cleaned), limit))
        todo = _or(todo, too_long)  # truncation or the error: the scalar path decides
    return cleaned, todo


def _numeric_text(column: pa.Array, options: Any, pattern: str) -> tuple[pa.Array, pa.Array]:
    """Cleaned text that is a plain number under the default grammar; todo for the rest."""
    cleaned, todo = _clean(column, options)
    default_grammar = (
        options.locale == "us" and options.thousands is None and options.decimal_point is None
    )
    if not default_grammar:
        return cleaned, everything(column)
    plain = pc.or_(pc.is_null(cleaned), _matches(cleaned, pattern))
    unsigned = pc.replace_substring_regex(cleaned, r"^\+", "")  # Arrow does not parse "+"
    return unsigned, _or(todo, pc.invert(_bool(plain)))


def _bounded_int(values: pa.Array, target: CType) -> tuple[pa.Array, pa.Array]:
    low, high = INT_BOUNDS[target.kind]
    outside = _bool(pc.or_(pc.less(values, low), pc.greater(values, high)))
    safe = pc.if_else(outside, _pa.scalar(None, values.type), values)
    return pc.cast(safe, to_arrow(target)), outside


def cast_int(column: pa.Array, args: Any, target: CType) -> tuple[pa.Array, pa.Array]:
    """Cast to int16/32/64 from integers and plain integer text."""
    if pa.types.is_integer(column.type):
        return _bounded_int(pc.cast(column, pa.int64()), target)
    if not _strings(column):
        return _pa.nulls(len(column), to_arrow(target)), everything(column)
    text, todo = _numeric_text(column, args.options, _INTEGER)
    values = pc.cast(pc.if_else(todo, _pa.scalar(None, pa.string()), text), pa.int64())
    result, outside = _bounded_int(values, target)
    return result, _or(todo, outside)


def cast_float(column: pa.Array, args: Any, target: CType) -> tuple[pa.Array, pa.Array]:
    """Cast to float32/64 from finite numbers and plain number text."""
    arrow_type = to_arrow(target)
    if pa.types.is_integer(column.type) or pa.types.is_floating(column.type):
        values = pc.cast(column, pa.float64())
    elif _strings(column):
        text, todo = _numeric_text(column, args.options, _FLOAT)
        values = pc.cast(pc.if_else(todo, _pa.scalar(None, pa.string()), text), pa.float64())
        finite = _bool(pc.is_finite(values), null=True)
        result = pc.cast(values, arrow_type, safe=False)
        overflow = _bool(pc.invert(pc.is_finite(result)))
        return result, _or(todo, pc.invert(finite), overflow)
    else:
        return _pa.nulls(len(column), arrow_type), everything(column)
    finite = _bool(pc.is_finite(values), null=True)
    result = pc.cast(values, arrow_type, safe=False)
    overflow = _bool(pc.invert(pc.is_finite(result)))
    return result, _or(pc.invert(finite), overflow)


def cast_decimal(column: pa.Array, args: Any, target: CType) -> tuple[pa.Array, pa.Array]:
    """Cast to decimal(p,s) from integers and plain decimal text, rounding half away from 0."""
    precision, scale = target.decimal_params
    rounding = args.options.rounding or "half_up"
    if rounding != "half_up":
        return _pa.nulls(len(column), to_arrow(target)), everything(column)
    if pa.types.is_integer(column.type):
        wide, todo = (
            pc.cast(column, pa.decimal128(38, 18)),
            _pa.repeat(_pa.scalar(value=False), len(column)),
        )
    elif _strings(column):
        text, todo = _numeric_text(column, args.options, _DECIMAL)
        wide = pc.cast(pc.if_else(todo, _pa.scalar(None, pa.string()), text), pa.decimal128(38, 18))
    else:
        return _pa.nulls(len(column), to_arrow(target)), everything(column)
    rounded = pc.round(wide, ndigits=scale, round_mode="half_towards_infinity")
    limit = Decimal(10) ** (precision - scale)
    too_big = _bool(pc.greater_equal(pc.abs(rounded), _pa.scalar(limit, pa.decimal128(38, 18))))
    safe = pc.if_else(too_big, _pa.scalar(None, rounded.type), rounded)
    return pc.cast(safe, to_arrow(target)), _or(todo, too_big)


def cast_boolean(column: pa.Array, args: Any, _target: CType) -> tuple[pa.Array, pa.Array]:
    """Cast to boolean from booleans and the configured true/false tokens."""
    options = args.options
    if pa.types.is_boolean(column.type):
        return column, _pa.repeat(_pa.scalar(False), len(column))  # noqa: FBT003
    tokens = (*options.true_values, *options.false_values)
    if not _strings(column) or not all(_ascii(t) for t in tokens):
        return _pa.nulls(len(column), pa.bool_()), everything(column)
    text, todo = _clean(column, options)
    if not options.case_sensitive:
        text = pc.ascii_lower(text)
    fold = (lambda t: t) if options.case_sensitive else str.lower
    is_true = _bool(pc.is_in(text, value_set=_pa.array([fold(t) for t in options.true_values])))
    is_false = _bool(pc.is_in(text, value_set=_pa.array([fold(t) for t in options.false_values])))
    known = _or(is_true, is_false, pc.is_null(text))
    result = pc.if_else(is_true, True, pc.if_else(is_false, False, _pa.scalar(None, pa.bool_())))  # noqa: FBT003
    return result, _or(todo, pc.invert(known), pc.and_(is_true, is_false))


def _precision(values: pa.Array, precision: str) -> pa.Array:
    if precision == "s":
        return pc.floor_temporal(values, unit="second")
    if precision == "ms":
        return pc.floor_temporal(values, unit="millisecond")
    return values


def _year_bounds(values: pa.Array, options: Any) -> pa.Array:
    years = pc.year(values)
    outside = _pa.repeat(_pa.scalar(False), len(values))  # noqa: FBT003
    if options.min_year is not None:
        outside = pc.or_(outside, _bool(pc.less(years, options.min_year)))
    if options.max_year is not None:
        outside = pc.or_(outside, _bool(pc.greater(years, options.max_year)))
    return outside


def _iso_utc(text: pa.Array) -> pa.Array:
    """Claimed ISO text as UTC instants.

    A space becomes T, a date gets midnight, a naive value gets Z (only claimed when the zone
    is UTC), and a lowercase z becomes Z.
    """
    text = pc.replace_substring(text, " ", "T")
    text = pc.replace_substring_regex(text, r"^([0-9]{4}-[0-9]{2}-[0-9]{2})$", r"\1T00:00:00")
    text = pc.replace_substring_regex(text, r"z$", "Z")
    zoned = _matches(text, _ZONED)
    text = pc.if_else(zoned, text, pc.binary_join_element_wise(text, "Z", ""))
    return pc.cast(text, pa.timestamp("us", tz="UTC"))


def cast_temporal(column: pa.Array, args: Any, target: CType) -> tuple[pa.Array, pa.Array]:
    """Cast to timestamptz, timestamp or date from ISO text or Arrow timestamps (zone UTC)."""
    options = args.options
    kind = target.kind
    arrow_type = to_arrow(target)
    nothing = _pa.nulls(len(column), arrow_type)
    if options.tz != "UTC" or not options.formats or options.formats[0] != "iso":
        return nothing, everything(column)
    if pa.types.is_timestamp(column.type):
        utc = pc.cast(column, pa.timestamp("us", tz="UTC"))  # naive values are UTC
        todo = _pa.repeat(_pa.scalar(False), len(column))  # noqa: FBT003
    elif _strings(column):
        text, todo = _clean(column, options)
        iso = pc.or_(pc.is_null(text), _matches(text, _ISO))
        todo = _or(todo, pc.invert(_bool(iso)))
        try:
            utc = _iso_utc(pc.if_else(todo, _pa.scalar(None, pa.string()), text))
        except (pa.ArrowInvalid, pa.ArrowNotImplementedError):
            return nothing, everything(column)  # e.g. a month 13: the scalar path reports it
    else:
        return nothing, everything(column)
    todo = _or(todo, _year_bounds(utc, options))
    if kind == "timestamptz":
        result = _precision(utc, options.output_precision)
    elif kind == "timestamp":  # the wall time in UTC
        result = _precision(pc.cast(utc, pa.timestamp("us")), options.output_precision)
    else:
        result = pc.cast(pc.cast(utc, pa.timestamp("us")), pa.date32())
    return result, todo


TRANSFORMS: dict[str, Vector] = {
    "trim": trim,
    "strip_chars": strip_chars,
    "lower": lower,
    "upper": upper,
    "left": left,
    "right": right,
    "set_null": set_null,
    "null_tokens": null_tokens,
}
"""Builtins with an Arrow implementation, by name."""

CASTS: dict[str, Vector] = {
    "string": cast_string,
    **dict.fromkeys(("int16", "int32", "int64"), cast_int),
    **dict.fromkeys(("float32", "float64"), cast_float),
    "decimal": cast_decimal,
    "boolean": cast_boolean,
    **dict.fromkeys(("timestamptz", "timestamp", "date"), cast_temporal),
}
"""Casts with an Arrow implementation, by target kind."""
