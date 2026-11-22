"""Row executor semantics: sources, defaults, nullability, enum, nested, on_error (WBS 5.8)."""

from __future__ import annotations

from typing import Any

import pytest

from map_conform.errors import ConformError, RowRejected
from map_conform.plan.compile import compile_stream
from map_conform.plan.row import RowExecutor
from map_conform.spec.load import resolve_stream
from map_conform.spec.model import parse_spec
from map_conform.transforms.builtins import builtin_registry

PROPERTIES = {
    "a": {"type": ["string", "null"]},
    "b": {"type": ["string", "null"]},
    "obj": {"type": ["object", "null"], "properties": {"zipCode": {"type": "string"}}},
}


def executor(columns: dict[str, Any], **defaults: Any) -> RowExecutor:
    """An executor for stream s with the given columns."""
    spec = parse_spec(
        {
            "version": 1,
            "defaults": {"metadata": "none", **defaults},
            "streams": {"s": {"columns": columns}},
        }
    )
    resolved = resolve_stream(spec, "s")
    assert resolved is not None
    plan = compile_stream(spec, resolved, {"properties": PROPERTIES}, builtin_registry())
    return RowExecutor(plan, resolved.settings)


def run(columns: dict[str, Any], record: dict[str, Any], **defaults: Any) -> dict[str, Any]:
    """Conform one record."""
    out = executor(columns, **defaults).run(record, {}, row=1)
    assert out is not None
    return out


def test_missing_and_coalesced_sources() -> None:
    """A list of sources takes the first non-null, and consumes them; missing is null."""
    out = run({"c": {"source": ["a", "b"], "type": "string"}}, {"b": "from b"})
    assert out["c"] == "from b"
    assert "a" not in out
    assert "b" not in out
    assert run({}, {})["a"] is None


def test_default_fills_null_results() -> None:
    """A null token or missing value takes the typed default."""
    assert run({"a": {"type": "int64", "default": "0"}}, {"a": "N/A"})["a"] == 0


def test_non_nullable_null_is_an_error_even_under_null_policy() -> None:
    """A null in a column declared nullable: false fails, whatever on_error says."""
    with pytest.raises(ConformError, match="nullable: false failed"):
        run({"a": {"type": "int64", "nullable": False}}, {"a": None})
    with pytest.raises(ConformError, match="cast: int64 failed on 'x'"):
        run({"a": {"type": "int64", "nullable": False, "on_error": "null"}}, {"a": "x"})


def test_policies_per_column() -> None:
    """null, keep (string only), reject."""
    assert run({"a": {"type": "int64", "on_error": "null"}}, {"a": "x"})["a"] is None
    assert run({"a": {"type": "string(2)", "on_error": "keep"}}, {"a": "xyz"})["a"] == "xyz"
    with pytest.raises(RowRejected):
        run({"a": {"type": "int64", "on_error": "reject"}}, {"a": "x"})


def test_enum_is_checked_on_the_wire_value() -> None:
    """A value outside enum fails under on_error."""
    columns = {"a": {"type": "decimal(5,2)", "enum": ["1", "2.5"]}}
    assert run(columns, {"a": "2.50"})["a"] == "2.50"
    with pytest.raises(ConformError, match=r"enum failed on '3': '3.00' is not allowed"):
        run(columns, {"a": "3"})


def test_nested_members_are_renamed_then_cast() -> None:
    """Source keys become conformed member names before the struct cast; JSON text too."""
    out = run({}, {"obj": {"zipCode": "02139", "extra": 1}}, nested="keep")
    assert out["obj"] == {"zip_code": "02139"}
    assert run({}, {"obj": '{"zipCode": "1"}'}, nested="keep")["obj"] == {"zip_code": "1"}
    assert run({}, {"obj": {"zipCode": "x"}})["obj"] == '{"zipCode": "x"}'
