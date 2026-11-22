"""ConformError context and the on_error policy (WBS 7.2)."""

from __future__ import annotations

import pytest

from map_conform.errors import ConformError, RowRejected, apply_policy


def error(value: object = "$12,3x") -> ConformError:
    """A representative error."""
    return ConformError(stream="orders", column="amount", row=17, value=value,
                        rule="cast: decimal(10,2)", reason="not a number")  # fmt: skip


def test_message_names_stream_column_row_value_and_rule() -> None:
    """The message says where, what, and what to do about it."""
    assert str(error()) == (
        "stream 'orders', column 'amount', row 17: cast: decimal(10,2) failed on '$12,3x': "
        "not a number. Fix the column's transform in the spec, set on_error, or drop the column."
    )


def test_long_values_are_shortened() -> None:
    """A huge value does not flood the log."""
    message = str(error("x" * 500))
    assert "'xxxx" in message
    assert "..." in message
    assert len(message) < 300  # noqa: PLR2004


def test_policies() -> None:
    """raise, null, keep, reject."""
    err = error()
    with pytest.raises(ConformError) as caught:
        apply_policy("raise", err, "$12,3x")
    assert caught.value is err
    assert apply_policy("null", err, "$12,3x") is None
    assert apply_policy("keep", err, "$12,3x") == "$12,3x"
    with pytest.raises(RowRejected) as rejected:
        apply_policy("reject", err, "$12,3x")
    assert rejected.value.error is err
