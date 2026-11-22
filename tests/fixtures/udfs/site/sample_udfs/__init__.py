"""A sample UDF package, installed through its entry points (WBS 6.5 acceptance)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from map_conform import udf


@udf(returns="int32")
def fiscal_week(value: dt.date, *, start_month: int = 7) -> int:
    """Week of the fiscal year that starts on the first of start_month."""
    year = value.year if value.month >= start_month else value.year - 1
    start = dt.date(year, start_month, 1)
    return (value - start).days // 7 + 1


@udf(name="clean_sku", returns="string", vectorized=True)
def clean_sku(values: pa.Array) -> Any:  # noqa: ANN401 -- a pyarrow array
    """SKUs trimmed and uppercased, on whole arrays."""
    return pc.utf8_upper(pc.utf8_trim_whitespace(values))


def shout(value: object, *, suffix: str = "!") -> str:
    """A plain function: no decorator needed."""
    return f"{str(value).upper()}{suffix}"


def broken(value: object, option: int) -> object:
    """Its option is positional, so it cannot be a step."""
    return value, option
