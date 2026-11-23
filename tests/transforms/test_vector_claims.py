"""Vector casts hand rows on for any option their kernel does not understand (MAPC-132)."""

from __future__ import annotations

import dataclasses
from typing import Any

import pyarrow as pa
import pytest

from map_conform.plan.ops import CastArgs
from map_conform.transforms import polars_vector, vector
from map_conform.transforms.builtins import builtin_registry
from map_conform.types.canonical import parse_ctype

TEXT = pa.array(["12", "7", None])


def _args(kind: str, **changes: Any) -> CastArgs:
    options = builtin_registry().casts[kind].kwargs()
    return CastArgs(parse_ctype(kind if kind != "decimal" else "decimal(10,2)"),
                    dataclasses.replace(options, **changes))  # fmt: skip


@pytest.mark.parametrize("kind", ["int64", "decimal", "float64"])
def test_plain_numbers_are_claimed_with_default_options(kind: str) -> None:
    """The baseline: plain numbers run in the kernel."""
    args = _args(kind)
    _, todo = vector.CASTS[kind](TEXT, args, args.target)
    assert todo.to_pylist() == [False, False, False]


@pytest.mark.parametrize(
    ("kind", "change"),
    [
        ("int64", {"locale": "eu"}),
        ("decimal", {"thousands": "'"}),
        ("float64", {"decimal_point": ","}),
    ],
)
def test_grammar_options_hand_every_row_on(kind: str, change: dict[str, Any]) -> None:
    """A changed number grammar is not the kernel's: every value runs row-wise (nulls stay)."""
    args = _args(kind, **change)
    _, todo = vector.CASTS[kind](TEXT, args, args.target)
    assert todo.to_pylist() == [True, True, False]


def test_an_option_the_kernel_does_not_know_hands_every_row_on() -> None:
    """A cast option added later is honoured by the row path until its kernel learns it."""

    @dataclasses.dataclass(frozen=True)
    class Future:
        trim: bool = True
        null_tokens: tuple[str, ...] = ()
        null_tokens_case_sensitive: bool = False
        brand_new: str = "off"

    def kernel(column: pa.Array, _args: Any, _target: Any) -> tuple[pa.Array, pa.Array]:  # noqa: ANN401
        return column, pa.array([False] * len(column))

    understood = frozenset({"trim", "null_tokens", "null_tokens_case_sensitive"})
    guarded = vector.claims(kernel, understood)
    target = parse_ctype("string")
    _, todo = guarded(TEXT, CastArgs(target, Future()), target)
    assert todo.to_pylist() == [False, False, False]
    _, todo = guarded(TEXT, CastArgs(target, Future(brand_new="on")), target)
    assert todo.to_pylist() == [True, True, False]


def test_every_cast_kernel_is_guarded() -> None:
    """Each Arrow and polars cast table entry goes through claims()."""
    for table in (vector.CASTS, polars_vector.CASTS):
        for kind, fn in table.items():
            assert getattr(fn, "__qualname__", None) == "claims.<locals>.run", kind
