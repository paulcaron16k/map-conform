"""Numeric casts and builtins (detailed design §6.2).

One grammar serves int16/32/64, float32/64 and decimal(p,s) targets. After the value cleanup
(trim, null tokens) a string may have, in this order of removal:

- parentheses meaning negative (``parens_negative``);
- a trailing ``%`` (``percent: divide`` or ``strip``; otherwise an error);
- a trailing minus (``trailing_minus``);
- one currency symbol or ISO-4217 code, before or after, with an optional sign before it;
- a sign, then digits with thousands separators in valid groups of three, a decimal point,
  and an exponent.

An integer cast also reads PostgreSQL's integer literals (:func:`parse_integer_literal`):
``0x``/``0o``/``0b`` prefixes and single underscores between digits (``0x1F``, ``1_000``).

Separators come from ``locale`` (us ``1,234.5``, eu ``1.234,5``, ch ``1'234.5``) unless
``thousands`` / ``decimal_point`` are given. Arithmetic is exact (``Decimal``), so ``1.005``
rounds to ``1.01``. ``rounding`` defaults to ``half_up`` (away from zero) for decimals and to
``error`` for integers, so a fraction never silently becomes an integer; ``12.0`` is fine.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, Inexact, InvalidOperation
from decimal import Context as DecimalContext
from typing import TYPE_CHECKING, Any, Literal

from map_conform.errors import StepFailed
from map_conform.spec._struct import documented
from map_conform.transforms.casts import Cleanup, clean, cleanup_defaults
from map_conform.transforms.registry import NUMERIC, RAW, Registry, Transform

if TYPE_CHECKING:
    from map_conform.plan.ops import CastArgs
    from map_conform.spec.model import ColumnSpec, Defaults
    from map_conform.transforms.registry import Context

Rounding = Literal["half_up", "half_even", "down", "error"]

INT_BOUNDS = {
    "int16": (-(2**15), 2**15 - 1),
    "int32": (-(2**31), 2**31 - 1),
    "int64": (-(2**63), 2**63 - 1),
}
LOCALES = {"us": (",", "."), "eu": (".", ","), "ch": ("'", ".")}
CURRENCY_SYMBOLS = "$€£¥₹₩₽₺₪₫฿¢₱₦₴₸₡"
_CURRENCY = rf"(?:[{re.escape(CURRENCY_SYMBOLS)}]|[A-Z]{{3}})"
_LEADING_CURRENCY = re.compile(rf"^([+-]?)\s*{_CURRENCY}\s*")
_TRAILING_CURRENCY = re.compile(rf"\s*{_CURRENCY}$")
_ANY_CURRENCY = re.compile(_CURRENCY)
_EXPONENT = r"(?:[eE][+-]?\d+)?"
_PG_SPACE = "[ \t\n\r\v\f]*"
_INTEGER_LITERAL = re.compile(
    rf"{_PG_SPACE}(?P<sign>[+-]?)(?:"
    r"0[xX](?P<hex>_?[0-9a-fA-F]+(?:_[0-9a-fA-F]+)*)"
    r"|0[oO](?P<oct>_?[0-7]+(?:_[0-7]+)*)"
    r"|0[bB](?P<bin>_?[01]+(?:_[01]+)*)"
    rf"|(?P<dec>[0-9]+(?:_[0-9]+)*)){_PG_SPACE}"
)
_BASES = {"hex": 16, "oct": 8, "bin": 2, "dec": 10}
_MODES = {"half_up": ROUND_HALF_UP, "half_even": ROUND_HALF_EVEN, "down": ROUND_DOWN}
_EXACT = DecimalContext(prec=200, traps=[InvalidOperation])


@dataclass(frozen=True)
class NumberCast(Cleanup):
    """Options for casts to integers, floats and decimals."""

    locale: Literal["us", "eu", "ch"] = documented(
        "Separators: us is 1,234.56; eu is 1.234,56; ch is 1'234.56.", default="us"
    )
    thousands: str | None = documented(
        "Thousands separator, overriding the locale's.", default=None
    )
    decimal_point: str | None = documented("Decimal point, overriding the locale's.", default=None)
    parens_negative: bool = documented("(12.50) is -12.50.", default=False)
    trailing_minus: bool = documented("12.50- is -12.50.", default=False)
    percent: Literal["error", "divide", "strip"] = documented(
        "A trailing %: an error, divide by 100 (15% is 0.15), or drop the sign (15% is 15).",
        default="error",
    )
    rounding: Rounding | None = documented(
        "Digits beyond the scale: half_up (halves away from zero), half_even, down, or "
        "error. Unset: half_up for decimals, error for integers ('12.0' is always 12).",
        default=None,
    )
    nan: Literal["null", "error"] = documented("What NaN and infinity become.", default="null")


def parse_integer_literal(text: str) -> int | None:
    """An integer written as PostgreSQL 16 reads one (bigint input), or None.

    ASCII whitespace around; an optional sign; then decimal digits, or a ``0x``, ``0o`` or
    ``0b`` prefix in any case (with an optional underscore after it) and its digits. Single
    underscores may separate digits; leading zeros are fine. ``"7.0"``, ``"1e3"``, ``"1_"``,
    ``"0x"`` and non-ASCII digits are not integer literals.
    """
    match = _INTEGER_LITERAL.fullmatch(text)
    if match is None:
        return None
    base = next(name for name in _BASES if match[name] is not None)
    digits = match[base].replace("_", "")
    # Decimal, because int() refuses decimal text over 4300 digits; prefixed bases are exempt.
    number = int(Decimal(digits)) if base == "dec" else int(digits, _BASES[base])
    return -number if match["sign"] == "-" else number


def parse_number(text: str, options: NumberCast) -> Decimal:  # noqa: C901, PLR0912
    """Parse a numeric string exactly.

    Raises:
        StepFailed: when the text does not follow the grammar.
    """
    thousands, point = LOCALES[options.locale]
    thousands = options.thousands if options.thousands is not None else thousands
    point = options.decimal_point if options.decimal_point is not None else point
    s = text.strip()
    negative = False
    if s.startswith("(") and s.endswith(")"):
        if not options.parens_negative:
            raise StepFailed("parentheses need parens_negative: true")
        negative, s = True, s[1:-1].strip()
    percent = s.endswith("%")
    if percent:
        if options.percent == "error":
            raise StepFailed("'%' needs percent: divide (or strip)")
        s = s[:-1].strip()
    if s.endswith("-") and not s.startswith("-"):
        if not options.trailing_minus:
            raise StepFailed("a trailing minus needs trailing_minus: true")
        negative, s = not negative, s[:-1].strip()
    sign = ""
    if match := _LEADING_CURRENCY.match(s):
        sign, s = match.group(1), s[match.end() :]
    elif match := _TRAILING_CURRENCY.search(s):
        s = s[: match.start()]
    if _ANY_CURRENCY.search(s):
        raise StepFailed("at most one currency marker")
    s = sign + s.strip()
    if s and s[0] in "+-":  # note: "" in "+-" is True, so test s first
        negative, s = negative ^ (s[0] == "-"), s[1:]
    body = _normalise_body(s, thousands, point)
    try:
        number = _EXACT.create_decimal(body)
    except InvalidOperation as exc:
        raise StepFailed("not a number") from exc
    if negative:
        number = -number
    if percent and options.percent == "divide":
        number = _EXACT.divide(number, Decimal(100))
    return number


def _normalise_body(s: str, thousands: str, point: str) -> str:
    """Remove valid thousands separators and make the decimal point a '.'."""
    t, p = re.escape(thousands), re.escape(point)
    grouped = rf"\d{{1,3}}(?:{t}\d{{3}})+"
    plain = r"\d+"
    pattern = rf"^(?:{grouped}|{plain})?(?:{p}\d*)?{_EXPONENT}$"
    if not re.search(r"\d", s) or not re.match(pattern, s):
        if thousands and thousands in s:
            raise StepFailed(f"thousands separators {thousands!r} must form groups of three")
        raise StepFailed("not a number")
    return s.replace(thousands, "").replace(point, ".")


def _from_value(
    value: object, options: NumberCast, *, integer_literals: bool = False
) -> Decimal | None:
    """Any raw value as an exact Decimal; None for null or a NaN treated as null.

    ``integer_literals`` also reads text as :func:`parse_integer_literal` does, first.
    """
    cleaned = clean(value, options)
    if isinstance(cleaned, bool):
        raise StepFailed("a boolean is not a number")
    if isinstance(cleaned, (float, Decimal)) and not _is_finite(cleaned):
        if options.nan == "null":
            return None
        raise StepFailed(f"{cleaned} is not a finite number")
    if cleaned is None or isinstance(cleaned, Decimal):
        return cleaned
    if isinstance(cleaned, float):
        return Decimal(repr(cleaned))  # the shortest repr: 0.1 stays 0.1
    if isinstance(cleaned, int):
        return Decimal(cleaned)
    if isinstance(cleaned, str):
        literal = parse_integer_literal(cleaned) if integer_literals else None
        return parse_number(cleaned, options) if literal is None else Decimal(literal)
    raise StepFailed(f"{type(cleaned).__name__} is not a number")


def _is_finite(number: float | Decimal) -> bool:
    return number.is_finite() if isinstance(number, Decimal) else math.isfinite(number)


_MAX_DIGITS = 150
"""Larger numbers fit no column; quantizing them would overflow the decimal context."""


def _round(number: Decimal, exponent: Decimal, mode: Rounding) -> Decimal:
    if number.adjusted() >= _MAX_DIGITS:
        raise StepFailed(f"{number} is too large for any numeric column")
    if mode == "error":
        try:
            return number.quantize(exponent, context=DecimalContext(prec=200, traps=[Inexact]))
        except Inexact as exc:
            raise StepFailed(f"{number} has more fraction digits than the column allows") from exc
    return number.quantize(exponent, rounding=_MODES[mode], context=_EXACT)


def cast_int(value: object, args: CastArgs, _ctx: Context) -> object:
    """Cast to int16/32/64; a fraction is an error unless a rounding mode is set.

    Text follows the numeric grammar, and may also be ``0x``/``0o``/``0b``-prefixed or have
    underscores between digits.
    """
    options: NumberCast = args.options
    number = _from_value(value, options, integer_literals=True)
    if number is None:
        return None
    integral = _round(number, Decimal(1), options.rounding or "error")
    result = int(integral)
    low, high = INT_BOUNDS[args.target.kind]
    if not low <= result <= high:
        raise StepFailed(f"{result} is outside {args.target.kind}")
    return result


def cast_float(value: object, args: CastArgs, _ctx: Context) -> object:
    """Cast to float32/64; the result is finite or null."""
    options: NumberCast = args.options
    number = _from_value(value, options)
    if number is None:
        return None
    result = float(number)
    if not math.isfinite(result):
        raise StepFailed(f"{number} does not fit a {args.target.kind}")
    return result


def cast_decimal(value: object, args: CastArgs, _ctx: Context) -> object:
    """Cast to decimal(p,s): exactly s fraction digits, at most p digits."""
    options: NumberCast = args.options
    number = _from_value(value, options)
    if number is None:
        return None
    precision, scale = args.target.decimal_params
    result = _round(number, Decimal(1).scaleb(-scale), options.rounding or "half_up")
    digits = len(result.as_tuple().digits)
    if digits > precision and result != 0:
        raise StepFailed(f"{digits} digits > precision {precision}")
    return result


def _number_defaults(settings: Defaults, column: ColumnSpec | None) -> dict[str, Any]:
    return cleanup_defaults(settings, column)


# --- builtins after the cast -------------------------------------------------------------------


@dataclass(frozen=True)
class RoundKwargs:
    """Round to ``ndigits`` fraction digits (half_up)."""

    ndigits: int = 0


@dataclass(frozen=True)
class ClampKwargs:
    """Keep a number within bounds."""

    min: float | None = None
    max: float | None = None
    on_out_of_range: Literal["clamp", "null", "error"] = "clamp"


@dataclass(frozen=True)
class ScaleKwargs:
    """Multiply, e.g. 0.01 for cents to units."""

    factor: float = 1.0


def _round_step(value: object, k: RoundKwargs, _ctx: Context) -> object:
    if isinstance(value, Decimal):
        return value.quantize(Decimal(1).scaleb(-k.ndigits), rounding=ROUND_HALF_UP)
    if isinstance(value, float):
        exact = Decimal(repr(value)).quantize(Decimal(1).scaleb(-k.ndigits), rounding=ROUND_HALF_UP)
        return float(exact)
    return value


def _exact(value: object) -> Decimal:
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, (int, Decimal)):
        return Decimal(value)
    raise StepFailed(f"{type(value).__name__} is not a number")


def _clamp(value: object, k: ClampKwargs, _ctx: Context) -> object:
    number = _exact(value)
    bound: Decimal | None = None
    if k.min is not None and number < _exact(k.min):
        bound = _exact(k.min)
    elif k.max is not None and number > _exact(k.max):
        bound = _exact(k.max)
    if bound is None:
        return value
    if k.on_out_of_range == "null":
        return None
    if k.on_out_of_range == "error":
        raise StepFailed(f"{value} is outside [{k.min}, {k.max}]")
    if isinstance(value, Decimal):
        return bound
    return float(bound) if isinstance(value, float) else int(bound)


def _scale(value: object, k: ScaleKwargs, ctx: Context) -> object:
    factor = Decimal(repr(k.factor))
    if isinstance(value, Decimal):
        _, scale = ctx.target.decimal_params if ctx.target.kind == "decimal" else (0, 0)
        return (value * factor).quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
    if isinstance(value, int) and not isinstance(value, bool):
        result = Decimal(value) * factor
        if result != result.to_integral_value():
            raise StepFailed(f"{value} x {k.factor} is not a whole number")
        return int(result)
    if isinstance(value, float):
        return float(Decimal(repr(value)) * factor)
    return value


def register(registry: Registry) -> None:
    """Add the numeric casts and builtins."""
    accepts = frozenset({RAW, "string", *NUMERIC})
    registry.register_cast(
        {"int16", "int32", "int64"},
        Transform("cast", cast_int, kwargs=NumberCast, defaults=_number_defaults, accepts=accepts),
    )
    registry.register_cast(
        {"float32", "float64"},
        Transform(
            "cast", cast_float, kwargs=NumberCast, defaults=_number_defaults, accepts=accepts
        ),
    )
    registry.register_cast(
        {"decimal"},
        Transform(
            "cast", cast_decimal, kwargs=NumberCast, defaults=_number_defaults, accepts=accepts
        ),
    )
    registry.register(
        Transform(
            "round",
            _round_step,
            kwargs=RoundKwargs,
            positional="ndigits",
            accepts=frozenset({"float32", "float64", "decimal"}),
        )
    )
    registry.register(Transform("clamp", _clamp, kwargs=ClampKwargs, accepts=NUMERIC))
    registry.register(
        Transform("scale", _scale, kwargs=ScaleKwargs, positional="factor", accepts=NUMERIC)
    )
