"""Name conformer pipeline, steps 1-8 (detailed design §5)."""

from __future__ import annotations

import csv
import dataclasses
import re

import pytest

from map_conform.naming.conform import NameConformer, NamingError
from map_conform.spec.model import NamingDefaults
from tests.fixtures.paths import FIXTURES

RESERVED_CASES = {"golden_reserved", "reserved_order", "reserved_user"}  # WBS 3.2


def golden() -> list[dict[str, str]]:
    """The names.csv golden table."""
    with (FIXTURES / "corpus" / "names.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def conformer(**overrides: object) -> NameConformer:
    """A conformer with the defaults, optionally overridden."""
    return NameConformer(dataclasses.replace(NamingDefaults(), **overrides))  # type: ignore[arg-type]


@pytest.mark.parametrize("row", golden(), ids=lambda r: r["case"])
def test_golden_table(row: dict[str, str]) -> None:
    """Every golden case conforms to its expected name with the defaults."""
    if row["case"] in RESERVED_CASES:
        pytest.skip("reserved words arrive with WBS 3.2")
    assert conformer().conform(row["source"]).name == row["expected"]


@pytest.mark.parametrize("row", golden(), ids=lambda r: r["case"])
def test_conforming_is_idempotent(row: dict[str, str]) -> None:
    """A conformed name conforms to itself, losslessly."""
    if row["case"] in RESERVED_CASES:
        pytest.skip("reserved words arrive with WBS 3.2")
    once = conformer().conform(row["source"]).name
    twice = conformer().conform(once)
    assert twice.name == once
    assert not twice.lossy


@pytest.mark.parametrize(
    ("source", "notes"),
    [
        ("customer_id", ()),
        ("Order Date (UTC)", ()),
        ("% Complete", ("dropped '%'",)),
        ("Amount ($)", ("dropped '$'",)),
        ("Ünïcode Näme", ("transliterated to ASCII",)),
        ("日本語 Name", ("dropped '日', '本', '語' (no transliteration)",)),
        (
            "Prix € (日)",
            ("dropped '€', '日' (no transliteration)",),
        ),
    ],
)
def test_lossy_changes_are_noted(source: str, notes: tuple[str, ...]) -> None:
    """Dropped symbols and transliteration are recorded; separators are not losses."""
    assert conformer().conform(source).notes == notes


def test_empty_result_is_named_by_ordinal() -> None:
    """Nothing usable left: col_<n>, with a note."""
    result = conformer().conform("%%%", ordinal=7)
    assert result.name == "col_7"
    assert result.notes[-1] == "nothing usable was left, so it is named col_7"
    assert conformer().conform("", ordinal=1).name == "col_1"


@pytest.mark.parametrize(
    ("overrides", "source", "expected"),
    [
        ({"case": "lower"}, "customerID Name", "customerid_name"),
        ({"case": "upper"}, "customerID Name", "CUSTOMERID_NAME"),
        ({"case": "preserve"}, "customerID Name", "customerID_Name"),
        ({"split_camel": False}, "customerID", "customerid"),
        ({"ascii": "strip"}, "Ünïcode Näme", "ncode_nme"),
        ({"ascii": "keep"}, "Ünïcode Näme", "ünïcode_näme"),
        ({"replace_invalid": ""}, "a.b-c d", "abcd"),
        ({"collapse": False}, "  a -- b ", "__a____b_"),
        ({"leading_digit": "letter"}, "2023 Revenue", "c023_revenue"),
        ({"leading_digit": "letter"}, "0th", "ath"),
    ],
)
def test_policies(overrides: dict[str, object], source: str, expected: str) -> None:
    """Each naming option changes only its own step."""
    assert conformer(**overrides).conform(source).name == expected


def test_leading_digit_error() -> None:
    """leading_digit: error refuses, naming the source."""
    with pytest.raises(NamingError, match=r"cannot conform '2023 Revenue': it starts with a digit"):
        conformer(leading_digit="error").conform("2023 Revenue")


def test_nfkc_normalises_compatibility_forms() -> None:
    """Fullwidth letters, ligatures and superscripts normalise before anything else."""
    assert conformer().conform("Ｏｒｄｅｒ ﬁle²").name == "order_file2"


GRAMMAR = re.compile(r"^[a-z_][a-z0-9_]*$")


@pytest.mark.parametrize("row", golden(), ids=lambda r: r["case"])
def test_outputs_obey_the_grammar(row: dict[str, str]) -> None:
    """Default output matches [a-z_][a-z0-9_]* with no doubled or edge underscores (bar one)."""
    name = conformer().conform(row["source"]).name
    assert GRAMMAR.match(name)
    assert "__" not in name
    assert not name.endswith("_") or row["case"] in RESERVED_CASES
