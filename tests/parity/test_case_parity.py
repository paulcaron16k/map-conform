"""case lowered to case_when gives the scalar results (WBS 8.6)."""

from __future__ import annotations

import string
from typing import Any

import pyarrow as pa
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from map_conform.plan.lower import lower_when
from map_conform.plan.vector import VectorChain
from tests.parity.harness import _executor, assert_parity
from tests.plan.test_expressions import DESIGN_CASE

STRING = {"type": ["null", "string"]}
LOWERED: list[tuple[str, dict[str, Any]]] = [
    ("int64", {"case": [
        {"when": "is_blank(value)", "then": "set_null"},
        {"when": r"matches('^\d+$', value)", "then": {"cast": "int64"}},
        {"else": {"cast": "int64", "thousands": ","}},
    ]}),
    ("string", {"case": [
        {"when": "value in ['y', 'Y', 'yes']", "then": [{"strip_chars": "ys"}, "upper"]},
        {"when": "not (value == 'n' or value == 'no')", "then": "lower"},
    ]}),
    ("decimal(10,2)", {"case": [
        {"when": "value != 'N/A' and not is_null(value)", "then": {"cast": "decimal"}},
    ]}),
    ("boolean", {"case": [
        {"when": "value in ['1', '0']", "then": {"cast": "boolean", "true_values": ["1"],
                                                 "false_values": ["0"]}},
        {"else": {"cast": "boolean"}},
    ]}),
]  # fmt: skip
VALUES = st.lists(
    st.one_of(st.none(), st.text(alphabet=string.printable, max_size=6),
              st.sampled_from(["", " ", "y", "Y", "yes", "n", "no", "N/A", "1", "0", "12",
                               "1,234", "true", "é", "a\nb", "3.149"])),
    min_size=1, max_size=12,
)  # fmt: skip


def spec_for(type_: str, transform: dict[str, Any], on_error: str = "null") -> dict[str, Any]:
    """Column c with the case transform."""
    column = {"type": type_, "transform": transform}
    return {"defaults": {"on_error": on_error}, "streams": {"s": {"columns": {"c": column}}}}


@pytest.mark.parametrize(("type_", "transform"), LOWERED)
def test_lowered_cases_are_vectorised(type_: str, transform: dict[str, Any]) -> None:
    """These cases take the columnar path."""
    executor = _executor(spec_for(type_, transform), {"c": STRING})
    assert isinstance(executor.plan.columns[0].vector, VectorChain)


@settings(max_examples=50, deadline=None)
@given(VALUES, st.sampled_from(range(len(LOWERED))), st.sampled_from(["null", "reject", "raise"]))
def test_lowered_case_parity(values: list[str | None], which: int, on_error: str) -> None:
    """Generated text through each lowered case equals the scalar path."""
    type_, transform = LOWERED[which]
    table = pa.table({"c": pa.array(values, pa.string())})
    assert_parity(spec_for(type_, transform, on_error), {"c": STRING}, table)


def test_design_case_parity() -> None:
    """The design's case lowers; its America/Chicago rows go to the scalar path, and agree."""
    executor = _executor(spec_for("timestamptz", DESIGN_CASE), {"c": STRING})
    assert isinstance(executor.plan.columns[0].vector, VectorChain)
    values = ["  ", "46095.5", "03/14/2026 09:30", "2026-03-14", None, "x"]
    assert_parity(spec_for("timestamptz", DESIGN_CASE), {"c": STRING},
                  pa.table({"c": pa.array(values, pa.string())}))  # fmt: skip


@pytest.mark.parametrize(
    ("text", "lowers"),
    [
        ("is_null(value)", True),
        ("value > 3", True),
        ("value in ['a', 1]", True),
        ("matches('(?<=a)b', value)", False),  # lookbehind is not RE2
        ("other == 1", False),  # reads another column
        ("len(value) > 2", False),
        ("value.startswith('x')", False),
    ],
)
def test_what_lowers(text: str, lowers: bool) -> None:  # noqa: FBT001 -- parametrized
    """Only the documented forms lower."""
    assert (lower_when(text) is not None) is lowers


def test_ordered_comparisons_leave_nulls_to_python() -> None:
    """Value > 3 with a null raises in Python, so null rows are not claimed."""
    mask = lower_when("value > 3")
    assert mask is not None
    result, todo = mask(pa.array([5, None, 1]))
    assert result.to_pylist() == [True, False, False]
    assert todo.to_pylist() == [False, True, False]
