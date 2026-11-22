"""Masking parity with pipelinewise-transform-field (WBS 12.5).

Each pipelinewise transformation type has a case: what pipelinewise produces, and what
map-conform produces. They agree, except where pipelinewise is buggy; those cases say what
pipelinewise gets wrong and assert the corrected behaviour.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

import pytest

from tests.plan.test_expressions import INTEGER, STRING, conform, plan_for, problems

NUMBER = {"type": ["null", "number"]}


def sha256(text: str) -> str:
    """Hex SHA-256, as pipelinewise computes it."""
    return hashlib.sha256(text.encode()).hexdigest()


def one(column: dict[str, Any], value: object, tap: dict[str, Any] = STRING) -> object:
    """Conform one value of column c."""
    (row,) = conform({"c": column}, {"c": tap}, {"c": value})
    assert row is not None
    return row["c"]


# --- the pipelinewise types -------------------------------------------------------------------


def test_set_null() -> None:
    """SET-NULL; pipelinewise leaves a non-null SCHEMA, map-conform makes the column nullable."""
    assert one({"type": "string", "transform": "set_null"}, "x") is None
    plan, _ = plan_for({"c": {"type": "string", "transform": "set_null"}}, {"c": STRING})
    assert plan.schema["properties"]["c"]["type"] == ["string", "null"]
    found = problems(
        {"c": {"type": "string", "nullable": False, "transform": "set_null"}}, {"c": STRING}
    )
    assert "set_null makes the column nullable" in found[0]


def test_hash() -> None:
    """HASH: the SHA-256 hex digest of the value."""
    assert one({"type": "string", "transform": "hash"}, "abc") == sha256("abc")


@pytest.mark.parametrize("n", [3, 12])
def test_hash_skip_first(n: int) -> None:
    """HASH-SKIP-FIRST-n keeps n characters; pipelinewise reads one digit, so 12 became 1."""
    value = "0123456789abcdefgh"
    out = one({"type": "string", "transform": {"hash": {"skip_first": n}}}, value)
    assert out == value[:n] + sha256(value[n:])


def test_mask_date() -> None:
    """MASK-DATE keeps the year; map-conform also clears the time of day (pipelinewise keeps it)."""
    out = one({"type": "timestamptz", "transform": ["cast", "redact_date"]}, "2026-03-14T09:26:53Z")
    assert out == "2026-01-01T00:00:00.000000Z"
    assert one({"type": "date", "transform": ["cast", "redact_date"]}, "2026-03-14") == "2026-01-01"


@pytest.mark.parametrize(
    ("column_type", "tap", "expected"),
    [
        ("int64", INTEGER, 0),
        ("float64", NUMBER, 0.0),
        ("decimal(10,2)", NUMBER, "0.00"),
        # pipelinewise writes the int 0 into a string column; here it is the string "0".
        ("string", STRING, "0"),
    ],
)
def test_mask_number(column_type: str, tap: dict[str, Any], expected: object) -> None:
    """MASK-NUMBER gives 0 in the column's own type."""
    assert one({"type": column_type, "transform": "mask_number"}, 123, tap) == expected


def test_mask_number_after_the_cast() -> None:
    """Masking a typed number keeps the type."""
    column = {"type": "decimal(10,2)", "transform": ["cast", {"mask_number": 7}]}
    assert one(column, "1.5") == "7.00"


def test_mask_hidden() -> None:
    """MASK-HIDDEN on a string column."""
    assert one({"type": "string", "transform": "mask_hidden"}, "secret") == "hidden"
    assert one({"type": "string", "transform": {"mask_hidden": "***"}}, "secret") == "***"


def test_mask_hidden_on_a_number_column_is_refused() -> None:
    """A compile error, where pipelinewise writes "hidden" into numeric columns.

    Targets reject that value; here the error says to declare the column a string.
    """
    found = problems({"c": {"type": "int64", "transform": "mask_hidden"}}, {"c": INTEGER})
    assert "mask_hidden works only in string columns, not int64" in found[0]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("abcdef", "ab**ef"), ("abcd", "****"), ("abc", "***"), ("", "")],
)
def test_mask_string_skip_ends(value: str, expected: str) -> None:
    """MASK-STRING-SKIP-ENDS-2; a value too short to show both ends is masked entirely."""
    column = {"type": "string", "transform": {"mask": {"keep_first": 2, "keep_last": 2}}}
    assert one(column, value) == expected


def test_when_equals_zero() -> None:
    """Pipelinewise's `when: equals: 0` never matched (0 is falsy); here it does."""
    columns = {
        "qty": {"type": "int64"},
        "c": {"type": "string", "transform": {"set_null": None, "when": "qty == 0"}},
    }
    out = conform(
        columns, {"qty": INTEGER, "c": STRING}, {"qty": 0, "c": "a"}, {"qty": 1, "c": "b"}
    )
    assert out == [{"qty": 0, "c": None}, {"qty": 1, "c": "b"}]


# --- beyond pipelinewise ------------------------------------------------------------------------


@pytest.mark.parametrize("algo", ["md5", "sha1", "sha256", "sha512"])
def test_hash_algorithms(algo: str) -> None:
    """Every hash algorithm, salted."""
    out = one({"type": "string", "transform": {"hash": {"algo": algo, "salt": "s"}}}, "abc")
    assert out == hashlib.new(algo, b"sabc").hexdigest()


def test_tokenize_is_keyed_and_stable() -> None:
    """Tokenize is HMAC-SHA256 with the key: stable for an input, different for another key."""
    column = {"type": "string", "transform": {"tokenize": "k1"}}
    expected = hmac.new(b"k1", b"alice", hashlib.sha256).hexdigest()
    assert one(column, "alice") == expected
    assert one(column, "alice") == expected
    assert one({"type": "string", "transform": {"tokenize": "k2"}}, "alice") != expected
    assert one(column, None) is None


def test_tokenize_needs_a_key() -> None:
    """Key is required."""
    found = problems({"c": {"type": "string", "transform": "tokenize"}}, {"c": STRING})
    assert "tokenize.key: required" in found[0] or "key: required" in found[0]
