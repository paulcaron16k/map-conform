"""Undeclared-column policy and the strict setting, through the mapper (WBS 5.9)."""

from __future__ import annotations

import pytest
from singer_sdk.exceptions import ConfigValidationError

from tests.test_mapper import RECORD, SCHEMA, run_mapper

DECLARED = {"Order ID": {"name": "order_id", "type": "int64"}}


def spec(undeclared: str | None = None) -> dict[str, object]:
    """A spec declaring only Order ID."""
    defaults = {**({"undeclared": undeclared} if undeclared else {})}
    return {
        "version": 1,
        "defaults": defaults,
        "streams": {"Customer Orders": {"columns": DECLARED}},
    }


def test_conform_is_the_default(capsys: pytest.CaptureFixture[str]) -> None:
    """Undeclared columns are conformed from the tap SCHEMA."""
    schema, record = run_mapper([SCHEMA, RECORD], capsys, spec())
    assert list(schema["schema"]["properties"]) == ["order_id", "amount", "updated_at"]
    assert schema["schema"]["properties"]["updated_at"]["x-sql-datatype"] == "timestamptz"
    assert record["record"]["amount"] == "$1,234.50"


def test_drop_removes_them(capsys: pytest.CaptureFixture[str]) -> None:
    """undeclared: drop keeps only declared columns."""
    schema, record = run_mapper([SCHEMA, RECORD], capsys, spec("drop"))
    assert list(schema["schema"]["properties"]) == ["order_id"]
    assert record["record"] == {"order_id": 42}


def test_error_names_each_one(capsys: pytest.CaptureFixture[str]) -> None:
    """undeclared: error fails at the SCHEMA, naming every undeclared column."""
    with pytest.raises(ConfigValidationError) as caught:
        run_mapper([SCHEMA], capsys, spec("error"))
    assert caught.value.errors == [
        "streams[\"Customer Orders\"].columns: undeclared column 'Amount' (undeclared: error)",
        "streams[\"Customer Orders\"].columns: undeclared column 'Updated At' (undeclared: error)",
    ]


def test_strict_setting_overrides_the_spec(capsys: pytest.CaptureFixture[str]) -> None:
    """strict: true makes undeclared columns errors even when the spec says conform."""
    with pytest.raises(ConfigValidationError, match="Invalid"):
        run_mapper([SCHEMA], capsys, spec("conform"), strict=True)
