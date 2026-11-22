"""Row and columnar executors agree: corpus, generated values, mixed plans (WBS 8.4-8.5)."""

from __future__ import annotations

import string
from typing import Any

import pyarrow as pa
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from map_conform.plan.vector import VectorChain
from tests.parity.harness import _executor, assert_parity
from tests.transforms.corpus import cases

TABLES = ["numeric.csv", "temporal.csv", "boolean.csv", "text.csv", "uuid.csv"]
STRING = {"type": ["null", "string"]}


def one_column(type_: str, kwargs: dict[str, Any], on_error: str = "null") -> dict[str, Any]:
    """A spec with column c cast to type_."""
    kind = type_.split("(", 1)[0].split("<", 1)[0]
    column = {"type": type_, "transform": {"cast": kind, **kwargs}}
    return {"defaults": {"on_error": on_error}, "streams": {"s": {"columns": {"c": column}}}}


@pytest.mark.parametrize("table", TABLES)
def test_corpus_parity(table: str) -> None:
    """Every corpus case (as one column of a batch) gives the same result through both."""
    for case in cases(table):
        column = pa.table({"c": pa.array([case.input, None, case.input], pa.string())})
        assert_parity(one_column(case.type, case.kwargs), {"c": STRING}, column)
        assert_parity(one_column(case.type, case.kwargs, "raise"), {"c": STRING}, column)


def test_corpus_columns_are_vectorised() -> None:
    """The common casts really take the columnar path."""
    for type_ in ("int64", "decimal(10,2)", "float64", "boolean", "timestamptz", "date", "string"):
        executor = _executor(one_column(type_, {}), {"c": STRING})
        assert isinstance(executor.plan.columns[0].vector, VectorChain), type_


TEXT = st.one_of(
    st.text(alphabet=string.digits + "+-.eE ,$%()", max_size=12),
    st.text(alphabet=string.printable, max_size=10),
    st.text(max_size=8),
    st.sampled_from(["", " ", "NULL", "n/a", "true", "FALSE", "Yes", "0", "1",
                     "2026-03-14", "2026-03-14T09:26:53Z", "2026-03-14 09:26:53.123+02:00",
                     "2026-02-30", "99999999999999999999", "1e400", "-0", "0042"]),
)  # fmt: skip


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(st.one_of(st.none(), TEXT), min_size=1, max_size=12),
       st.sampled_from(["int16", "int64", "decimal(10,2)", "float32", "float64", "boolean",
                        "timestamptz", "timestamp", "date", "string", "string(3)"]),
       st.sampled_from(["null", "keep", "reject", "raise"]))  # fmt: skip
def test_generated_text_parity(values: list[str | None], type_: str, on_error: str) -> None:
    """Arbitrary text through each vectorised cast, under every on_error policy."""
    if on_error == "keep" and not type_.startswith("string"):
        on_error = "null"
    table = pa.table({"c": pa.array(values, pa.string())})
    assert_parity(one_column(type_, {}, on_error), {"c": STRING}, table)


@settings(max_examples=40, deadline=None)
@given(st.lists(st.one_of(st.none(), st.integers(-(2**40), 2**40)), min_size=1, max_size=10),
       st.sampled_from(["int16", "int32", "int64", "decimal(8,2)", "float64"]))  # fmt: skip
def test_typed_integer_input_parity(values: list[int | None], type_: str) -> None:
    """Integer parquet columns into numeric types."""
    table = pa.table({"c": pa.array(values, pa.int64())})
    assert_parity(one_column(type_, {}), {"c": {"type": ["null", "integer"]}}, table)


@settings(max_examples=40, deadline=None)
@given(st.lists(st.text(max_size=6), min_size=1, max_size=10),
       st.sampled_from([["trim"], ["upper"], ["lower"], [{"left": 2}], [{"right": 2}],
                        [{"strip_chars": "x-"}], [{"null_tokens": ["A", "b"]}], ["set_null"],
                        ["trim", "upper", {"left": 3}]]))  # fmt: skip
def test_text_builtin_parity(values: list[str], steps: list[Any]) -> None:
    """Vectorised text builtins, alone and chained."""
    column = {"type": "string", "transform": steps}
    spec = {"defaults": {"on_error": "null"}, "streams": {"s": {"columns": {"c": column}}}}
    assert_parity(spec, {"c": STRING}, pa.table({"c": pa.array(values, pa.string())}))


def test_mixed_plan_parity() -> None:
    """Vectorised and row-wise columns, expressions, a filter, rejects and defaults together."""
    spec = {
        "defaults": {"on_error": "reject"},
        "streams": {"s": {
            "filter": "qty is None or qty < 100",
            "columns": {
                "id": {"type": "int64", "nullable": False},
                "qty": {"type": "int32"},
                "price": {"type": "decimal(10,2)", "parse": {"parens_negative": True}},
                "total": {"type": "decimal(12,2)", "expr": "(qty or 0) * (price or 0)"},
                "name": {"type": "string", "transform": ["trim", "upper"], "default": "?"},
                "code": {"type": "uuid", "on_error": "null"},
                "at": {"type": "timestamptz", "on_error": "null"},
            },
        }},
    }  # fmt: skip
    properties = dict.fromkeys(("id", "qty", "price", "name", "code", "at"), STRING)
    rows: list[dict[str, str | None]] = [
        {"id": "1", "qty": "3", "price": "2.50", "name": " ann ", "code": "x",
         "at": "2026-03-14T09:26:53Z"},
        {"id": "2", "qty": "500", "price": "(1.25)", "name": None, "code": None, "at": "nope"},
        {"id": "3", "qty": "x", "price": "1", "name": "Bé", "code": None, "at": None},
        {"id": "4", "qty": "1", "price": "1.005", "name": "z", "code": None, "at": None},
        {"id": "5", "qty": None, "price": "$1,000.00", "name": "", "code": None,
         "at": "2026-03-14 10:00:00"},
    ]  # fmt: skip
    table = pa.table({k: pa.array([r[k] for r in rows], pa.string()) for k in properties})
    outcome = assert_parity(spec, properties, table)
    assert outcome.error is None
    assert outcome.rejected == [3]  # qty "x"; row 2 is filtered (qty 500)
    assert outcome.table is not None
    assert outcome.table.column("id").to_pylist() == [1, 4, 5]
    rows[3]["id"] = None  # a null in a nullable: false column always raises
    table = pa.table({k: pa.array([r[k] for r in rows], pa.string()) for k in properties})
    assert "column 'id', row 4: nullable: false" in (
        assert_parity(spec, properties, table).error or ""
    )
