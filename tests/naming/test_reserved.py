"""Reserved words: data files and the step-9 policy."""

from __future__ import annotations

import dataclasses
from typing import get_args

import pytest

from map_conform.naming.conform import NameConformer, NamingError
from map_conform.naming.reserved import DATA, dialect_words, reserved_words
from map_conform.spec.model import Dialect, NamingDefaults

DIALECTS = get_args(Dialect)


def conformer(**overrides: object) -> NameConformer:
    """A conformer with the defaults, optionally overridden."""
    return NameConformer(dataclasses.replace(NamingDefaults(), **overrides))  # type: ignore[arg-type]


@pytest.mark.parametrize("dialect", DIALECTS)
def test_data_file_has_provenance_and_clean_words(dialect: str) -> None:
    """Each list names its source and holds unique lowercase identifiers."""
    lines = (DATA / f"{dialect}.txt").read_text(encoding="utf-8").splitlines()
    header = [line for line in lines if line.startswith("#")]
    words = [line for line in lines if line and not line.startswith("#")]
    assert any("retrieved 2026-11-22" in line for line in header)
    assert words == sorted(set(words))
    assert all(w.isidentifier() and w == w.lower() for w in words)
    assert dialect_words(dialect) == frozenset(words)


def test_every_dialect_has_a_file() -> None:
    """The Dialect literal and the data files agree."""
    assert {p.stem for p in DATA.glob("*.txt")} == set(DIALECTS)


def test_common_column_names_are_not_reserved_by_default() -> None:
    """The default lists leave date, year and value alone; ansi would not."""
    defaults = reserved_words(NamingDefaults().reserved_dialects)
    assert {"select", "order", "user", "qualify", "left"} <= defaults
    assert not {"date", "year", "value", "count", "account", "schema"} & defaults
    assert {"date", "year", "value"} <= dialect_words("ansi")


@pytest.mark.parametrize(
    ("overrides", "source", "expected"),
    [
        ({}, "select", "select_"),
        ({}, "Order", "order_"),
        ({}, "QUALIFY", "qualify_"),
        ({}, "date", "date"),
        ({"reserved_words": "prefix"}, "select", "_select"),
        ({"reserved_words": "ignore"}, "select", "select"),
        ({"reserved_dialects": ("ansi",)}, "date", "date_"),
        ({"reserved_dialects": ("snowflake",)}, "user", "user"),
        ({"reserved_dialects": ("postgres",)}, "user", "user_"),
        ({"case": "upper"}, "select", "SELECT_"),
        ({"case": "preserve"}, "Select", "Select_"),
    ],
)
def test_reserved_policy(overrides: dict[str, object], source: str, expected: str) -> None:
    """Matching ignores case; the policy decides the fix."""
    assert conformer(**overrides).conform(source).name == expected


def test_reserved_error() -> None:
    """reserved_words: error refuses."""
    with pytest.raises(NamingError, match="'select' is a reserved word"):
        conformer(reserved_words="error").conform("Select")


@pytest.mark.parametrize("policy", ["suffix", "prefix"])
def test_reserved_fix_is_idempotent(policy: str) -> None:
    """Conforming a fixed reserved word gives the same name back."""
    fixed = conformer(reserved_words=policy).conform("select").name
    assert conformer(reserved_words=policy).conform(fixed).name == fixed
