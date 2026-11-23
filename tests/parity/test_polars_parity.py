"""engine: polars gives the scalar results (WBS 8.7)."""

from __future__ import annotations

import string
from typing import Any

import pyarrow as pa
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from map_conform.plan import compile as compile_module
from map_conform.plan.vector import VectorChain
from map_conform.transforms import polars_vector
from tests.parity.harness import _executor, assert_parity

STRING = {"type": ["null", "string"]}
ALPHABET = string.ascii_letters + string.digits + " -_.$\\"
TEXT = st.lists(
    st.one_of(st.none(), st.text(alphabet=ALPHABET, max_size=10),
              st.text(max_size=5), st.sampled_from(["", "a\nb", "ab12cd", "AB-12", "x$1"])),
    min_size=1, max_size=10,
)  # fmt: skip
REGEX = [
    {"regex_replace": {"pattern": r"\d+", "repl": "#"}},
    {"regex_replace": {"pattern": r"([a-z]+)-(\d+)", "repl": r"\2:\1"}},
    {"regex_replace": {"pattern": r"(?P<w>[A-Z])", "repl": r"<\g<w>>$"}},
    {"regex_replace": {"pattern": "ab", "repl": "X", "flags": "i"}},
    {"regex_extract": {"pattern": r"([a-z]+)(\d+)", "group": 2}},
    {"regex_extract": r"\d+"},
]
DATES = st.lists(
    st.one_of(st.none(), st.dates().map(lambda d: d.strftime("%m/%d/%Y")),
              st.sampled_from(["3/4/2026", "13/01/2026", "02/30/2026", " 03/14/2026 ", "x", ""])),
    min_size=1, max_size=10,
)  # fmt: skip


def spec_for(steps: Any, type_: str = "string", engine: str = "polars") -> dict[str, Any]:  # noqa: ANN401
    """Column c with the steps, on the given engine."""
    column = {"type": type_, "transform": steps, "engine": engine}
    return {"defaults": {"on_error": "null"}, "streams": {"s": {"columns": {"c": column}}}}


def test_every_polars_kernel_has_parity_cases() -> None:
    """A step or cast kind given a polars kernel must be added to these parity cases."""
    steps = {next(iter(s)) for s in REGEX if isinstance(s, dict)}
    assert set(polars_vector.TRANSFORMS) <= steps
    assert set(polars_vector.CASTS) <= {"timestamptz", "timestamp", "date"}  # strptime test


@pytest.mark.parametrize("step", REGEX)
def test_regex_steps_are_vectorised_on_polars_only(step: Any) -> None:  # noqa: ANN401
    """Regular expressions vectorise on polars and stay row-wise on Arrow."""
    assert isinstance(_executor(spec_for(step), {"c": STRING}).plan.columns[0].vector, VectorChain)
    assert _executor(spec_for(step, engine="arrow"), {"c": STRING}).plan.columns[0].vector is None


@settings(max_examples=40, deadline=None)
@given(TEXT, st.sampled_from(range(len(REGEX))))
def test_regex_parity(values: list[str | None], which: int) -> None:
    """Generated text through each regex step on polars equals Python's re."""
    table = pa.table({"c": pa.array(values, pa.string())})
    assert_parity(spec_for(REGEX[which]), {"c": STRING}, table)


@settings(max_examples=40, deadline=None)
@given(DATES, st.sampled_from(["timestamptz", "timestamp", "date"]))
def test_strptime_parity(values: list[str | None], type_: str) -> None:
    """The strptime formats on polars equal Python's strptime, padding leniency included."""
    cast = {"cast": type_, "formats": ["%m/%d/%Y", "iso"]}
    table = pa.table({"c": pa.array(values, pa.string())})
    assert_parity(spec_for(cast, type_), {"c": STRING}, table)


def test_stream_default_engine() -> None:
    """defaults.engine: polars applies to every column."""
    column = {"type": "string", "transform": {"regex_replace": {"pattern": "a", "repl": "b"}}}
    spec = {"defaults": {"engine": "polars"}, "streams": {"s": {"columns": {"c": column}}}}
    assert _executor(spec, {"c": STRING}).plan.columns[0].vector is not None


def test_polars_extra_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without polars, engine: polars is a compile error naming the extra."""
    monkeypatch.setattr(compile_module, "polars_available", lambda: False)
    with pytest.raises(Exception, match="engine: polars needs the polars extra"):
        _executor(spec_for("trim"), {"c": STRING})
