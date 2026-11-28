"""Numeric casts beyond the corpus, and round / clamp / scale (WBS 5.3)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from map_conform.plan.ops import StepError
from tests.transforms.test_builtins import run


@pytest.mark.parametrize(
    ("value", "target", "kwargs", "expected"),
    [
        ("-$12.50", "decimal(6,2)", {}, Decimal("-12.50")),
        ("$-12.50", "decimal(6,2)", {}, Decimal("-12.50")),
        ("+€3", "decimal(6,2)", {}, Decimal("3.00")),
        ("(€1.234,50)", "decimal(8,2)", {"locale": "eu", "parens_negative": True},
         Decimal("-1234.50")),
        ("1 234,5", "decimal(8,2)", {"thousands": " ", "decimal_point": ","}, Decimal("1234.50")),
        (".5", "decimal(4,2)", {}, Decimal("0.50")),
        ("5.", "decimal(4,2)", {}, Decimal("5.00")),
        ("12.5%", "float64", {"percent": "strip"}, 12.5),
        (0.1, "decimal(4,2)", {}, Decimal("0.10")),
        (3.0, "int64", {}, 3),
        (1e15, "int64", {}, 1000000000000000),
        (Decimal("2.50"), "int32", {"rounding": "half_even"}, 2),
        ("2.675", "decimal(5,2)", {"rounding": "half_even"}, Decimal("2.68")),
        ("2.665", "decimal(5,2)", {"rounding": "half_even"}, Decimal("2.66")),
        ("9.999", "decimal(4,2)", {"rounding": "down"}, Decimal("9.99")),
        ("1" * 40, "decimal(50,0)", {}, Decimal("1" * 40)),
        (float("nan"), "decimal(6,2)", {}, None),
        (float("inf"), "int64", {}, None),
        ("-0.00", "decimal(4,2)", {}, Decimal("-0.00")),
        ("0x7FFF_FFFF", "int32", {}, 2**31 - 1),
        ("-0b1", "int16", {}, -1),
        ("0o_777", "int64", {"rounding": "half_up"}, 511),
        ("1_000", "int64", {}, 1000),
        ("12.0", "int64", {}, 12),
        ("1e3", "int64", {}, 1000),
    ],
)  # fmt: skip
def test_grammar_edges(
    value: object, target: str, kwargs: dict[str, Any], expected: object
) -> None:
    """Signs around currency, explicit separators, JSON floats, NaN, rounding modes."""
    assert (
        run({"cast": target.split("(", maxsplit=1)[0], **kwargs}, value, target=target) == expected
    )


@pytest.mark.parametrize(
    ("value", "target", "kwargs", "reason"),
    [
        ("1.005", "decimal(4,2)", {"rounding": "error"}, "more fraction digits"),
        (float("nan"), "float64", {"nan": "error"}, "not a finite number"),
        (True, "int64", {}, "a boolean is not a number"),
        ("1e400", "float32", {}, "does not fit"),
        ("12,34", "int64", {}, "groups of three"),
        ("1.2.3", "decimal(5,2)", {}, "not a number"),
        ("$", "decimal(5,2)", {}, "not a number"),
        ("€€5", "decimal(5,2)", {}, "at most one currency marker"),
        ({"a": 1}, "int64", {}, "dict is not a number"),
        ("0x10000", "int16", {}, "outside int16"),
        ("1__0", "int64", {}, "not a number"),
        ("0x", "int64", {}, "not a number"),
        ("0x1F", "decimal(5,0)", {}, "not a number"),
    ],
)
def test_grammar_errors(value: object, target: str, kwargs: dict[str, Any], reason: str) -> None:
    """Each malformed number fails with a reason."""
    with pytest.raises(StepError, match=reason):
        run({"cast": target.split("(", maxsplit=1)[0], **kwargs}, value, target=target)


def test_round_clamp_scale_after_the_cast() -> None:
    """Numeric builtins run on typed values."""
    assert run([{"cast": "float64"}, {"round": 1}], "2.25", target="float64") == 2.3  # noqa: PLR2004
    assert run([{"cast": "decimal"}, {"round": 1}], "2.25", target="decimal(5,2)") == Decimal(
        "2.30"
    )
    assert run([{"cast": "int64"}, {"clamp": {"min": 0, "max": 10}}], "42", target="int64") == 10  # noqa: PLR2004
    assert run([{"cast": "int64"}, {"clamp": {"max": 10, "on_out_of_range": "null"}}], "42",
               target="int64") is None  # fmt: skip
    with pytest.raises(StepError, match="outside"):
        run([{"cast": "int64"}, {"clamp": {"min": 0, "on_out_of_range": "error"}}], "-1",
            target="int64")  # fmt: skip
    assert run([{"cast": "decimal"}, {"scale": 0.01}], "1234", target="decimal(8,2)") == Decimal(
        "12.34"
    )
    assert run([{"cast": "int64"}, {"scale": 100}], "12", target="int64") == 1200  # noqa: PLR2004
    with pytest.raises(StepError, match="not a whole number"):
        run([{"cast": "int64"}, {"scale": 0.5}], "3", target="int64")


@pytest.mark.parametrize("target", ["int64", "decimal(10,2)"])
def test_huge_exponents_are_cell_errors(target: str) -> None:
    """1E200 is an error naming the value, not a crash (found by the parity suite)."""
    with pytest.raises(StepError, match="too large for any numeric column"):
        run({"cast": target.split("(", maxsplit=1)[0]}, "1E200", target=target)
