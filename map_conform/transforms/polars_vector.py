r"""polars implementations for ``engine: polars`` (detailed design §10.2, WBS 8.7).

With the ``polars`` extra, a column (``engine: polars``) or a stream (``defaults.engine``)
uses these vector ops where they exist, and the Arrow ones elsewhere. They cover what Arrow
does not vectorise: regular expressions and strptime-style date formats. They follow the
same rule as every vector op: claim only rows where the result is the scalar one.

- ``regex_replace`` and ``regex_extract`` claim printable-ASCII rows without line breaks,
  for patterns that compile in polars and cannot match the empty string (Python and Rust
  differ on empty matches), with the ``i`` flag at most. Python replacement references
  (``\\1``, ``\\g<1>``, ``\\g<name>``) are translated.
- Temporal casts whose first format is a strptime pattern of ``%Y %m %d %H %M %S`` and
  literals claim rows that parse and print back to the same text, so padding and other
  leniencies stay with Python's ``strptime``. The zone must be UTC.
"""

from __future__ import annotations

import importlib.util
import re
from typing import TYPE_CHECKING, Any

import pyarrow as pa

from map_conform.transforms import vector
from map_conform.types.to_arrow import to_arrow

if TYPE_CHECKING:
    from map_conform.types.canonical import CType

# The pyarrow stubs cannot follow array-in, array-out kernels; tests/parity checks this module.
_pa: Any = pa
pc: Any = vector.pc

_SIMPLE_FORMAT = re.compile(r"^(?:%[YmdHMS]|[^%])+$")
_BREAKS = r"[\r\n]"


def available() -> bool:
    """Whether polars is installed."""
    return importlib.util.find_spec("polars") is not None


def _pl() -> Any:  # noqa: ANN401 -- the polars module
    import polars as pl  # noqa: PLC0415 -- optional dependency

    return pl


def _claimable_text(column: pa.Array) -> pa.Array:
    """Todo rows: not printable ASCII, or containing a line break."""
    breaks = pc.fill_null(pc.match_substring_regex(column, _BREAKS), vector.FALSE)
    return pc.or_(vector.unsafe_text(column), breaks)


def _pattern(pattern: str, flags: str) -> str | None:
    """The polars pattern, or None when it cannot be claimed."""
    if set(flags) - {"i"}:
        return None
    try:
        if re.compile(pattern).search("") is not None:
            return None  # can match empty: Python and Rust place empty matches differently
    except re.error:
        return None
    full = f"(?i){pattern}" if "i" in flags else pattern
    try:
        _pl().Series([""]).str.contains(full)
    except Exception:  # noqa: BLE001 -- polars rejects the pattern
        return None
    return full


def _replacement(repl: str) -> str | None:
    """A Python ``re.sub`` replacement in polars syntax, or None when it has other escapes."""
    out: list[str] = []
    i = 0
    while i < len(repl):
        char = repl[i]
        if char == "$":
            out.append("$$")
        elif char == "\\":
            group = re.match(r"\\(?:(\d{1,2})|g<(\w+)>)", repl[i:])
            if group is None:
                return None
            out.append("${" + (group.group(1) or group.group(2)) + "}")
            i += len(group.group(0))
            continue
        else:
            out.append(char)
        i += 1
    return "".join(out)


def regex_replace(column: pa.Array, k: Any, _t: CType) -> tuple[pa.Array, pa.Array]:  # noqa: ANN401
    """``regex_replace`` with polars."""
    pattern = _pattern(k.pattern, k.flags)
    repl = _replacement(k.repl)
    if pattern is None or repl is None or not vector.is_text(column):
        return _pa.nulls(len(column), pa.string()), vector.everything(column)
    series = _pl().from_arrow(column)
    result = series.str.replace_all(pattern, repl).to_arrow()
    return pc.cast(result, pa.string()), _claimable_text(column)


def regex_extract(column: pa.Array, k: Any, _t: CType) -> tuple[pa.Array, pa.Array]:  # noqa: ANN401
    """``regex_extract`` with polars (numbered groups)."""
    pattern = _pattern(k.pattern, k.flags)
    if pattern is None or not isinstance(k.group, int) or not vector.is_text(column):
        return _pa.nulls(len(column), pa.string()), vector.everything(column)
    groups = re.compile(k.pattern).groups
    if k.group > groups:
        return _pa.nulls(len(column), pa.string()), vector.everything(column)
    series = _pl().from_arrow(column)
    result = series.str.extract(pattern, k.group).to_arrow()
    return pc.cast(result, pa.string()), _claimable_text(column)


def cast_temporal(column: pa.Array, args: Any, target: CType) -> tuple[pa.Array, pa.Array]:  # noqa: ANN401
    """Temporal casts whose first format is a simple strptime pattern."""
    options = args.options
    fmt = options.formats[0] if options.formats else "iso"
    arrow_type = to_arrow(target)
    if fmt == "iso" or not _SIMPLE_FORMAT.match(fmt) or options.tz != "UTC":
        return vector.cast_temporal(column, args, target)
    if target.kind == "time" or not vector.is_text(column):
        return _pa.nulls(len(column), arrow_type), vector.everything(column)
    text, todo = vector.clean(column, options)
    series = _pl().from_arrow(text)
    parsed = series.str.to_datetime(fmt, strict=False, time_unit="us")
    printed = parsed.dt.strftime(fmt).to_arrow()
    exact = pc.fill_null(pc.equal(pc.cast(printed, pa.string()), text), vector.FALSE)
    todo = pc.or_(todo, pc.and_(pc.is_valid(text), pc.invert(exact)))
    naive = pc.cast(parsed.to_arrow(), pa.timestamp("us"))
    todo = pc.or_(todo, vector.year_bounds(naive, options))
    if target.kind == "timestamptz":
        result = pc.assume_timezone(naive, timezone="UTC")
    elif target.kind == "timestamp":
        result = naive
    else:
        result = pc.cast(naive, pa.date32())
    return pc.cast(result, arrow_type), todo


TRANSFORMS: dict[str, vector.Vector] = {
    "regex_replace": regex_replace,
    "regex_extract": regex_extract,
}
"""Builtins polars vectorises, by name."""

CASTS: dict[str, vector.Vector] = dict.fromkeys(("timestamptz", "timestamp", "date"), cast_temporal)
"""Casts polars vectorises (over the Arrow ones), by target kind."""
