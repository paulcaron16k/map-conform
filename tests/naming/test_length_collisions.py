"""Length limits, collisions, and property tests over arbitrary names (WBS 3.3)."""

from __future__ import annotations

import dataclasses
import hashlib
import re

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from map_conform.naming.conform import NameConformer, NamingError
from map_conform.spec.model import NamingDefaults

GRAMMAR = re.compile(r"^[a-z_][a-z0-9_]*$")
LONG = "The quarterly revenue figure for the north-eastern regional sales division (adjusted)"


def conformer(**overrides: object) -> NameConformer:
    """A conformer with the defaults, optionally overridden."""
    return NameConformer(dataclasses.replace(NamingDefaults(), **overrides))  # type: ignore[arg-type]


# --- Length -----------------------------------------------------------------------------------


def test_long_names_truncate_with_a_hash_of_the_whole_name() -> None:
    """Head, '_', then 6 hex digits of the SHA-256 of the untruncated conformed name."""
    full = conformer(max_length=1000).conform(LONG).name
    result = conformer().conform(LONG)
    digest = hashlib.sha256(full.encode()).hexdigest()[:6]
    assert result.name == f"{full[:56].rstrip('_')}_{digest}"
    assert len(result.name) <= 63  # noqa: PLR2004
    assert result.notes == (f"truncated from {len(full)} characters",)


def test_names_differing_only_after_the_limit_stay_distinct() -> None:
    """Two long names with the same head get different hashes."""
    a = conformer(max_length=20).conform("customer lifetime value 2024").name
    b = conformer(max_length=20).conform("customer lifetime value 2025").name
    assert a != b
    assert a[:13] == b[:13]


def test_truncation_never_leaves_a_double_underscore() -> None:
    """A head ending in '_' is trimmed before the hash is added."""
    name = conformer(max_length=12).conform("abcd efgh ijkl").name
    assert "__" not in name
    assert len(name) <= 12  # noqa: PLR2004


def test_truncate_error() -> None:
    """truncate: error refuses long names."""
    with pytest.raises(NamingError, match="is longer than 63"):
        conformer(truncate="error").conform(LONG)


# --- Collisions -------------------------------------------------------------------------------


def test_collision_is_an_error_by_default() -> None:
    """Two sources that conform alike fail, naming both."""
    with pytest.raises(NamingError, match=r"'order_id'.*it conforms to 'order_id', as 'Order ID'"):
        conformer().conform_all(["Order ID", "order_id"])


def test_collision_suffix_keeps_genuine_names() -> None:
    """Later duplicates get the next free suffix; a real order_id_2 keeps its name."""
    results = conformer(on_collision="suffix").conform_all(
        ["Order ID", "order_id", "ORDER-ID", "order_id_2", "Name"]
    )
    assert [r.name for r in results] == [
        "order_id",
        "order_id_3",
        "order_id_4",
        "order_id_2",
        "name",
    ]
    assert results[1].notes == ("renamed from 'order_id': 'Order ID' has that name",)


def test_collisions_fold_case() -> None:
    """Case-preserved names that differ only in case still collide."""
    results = conformer(case="preserve", on_collision="suffix").conform_all(["Id", "ID", "id"])
    assert [r.name for r in results] == ["Id", "ID_2", "id_3"]


def test_suffix_respects_the_length_limit() -> None:
    """A suffixed name is shortened so it still fits."""
    results = conformer(max_length=8, on_collision="suffix").conform_all(["abcdefgh", "ABCDEFGH"])
    assert [r.name for r in results] == ["abcdefgh", "abcdef_2"]


# --- Properties -------------------------------------------------------------------------------

NAMES = st.text(max_size=120)
CONFIGS = st.builds(
    NamingDefaults,
    case=st.sampled_from(["snake", "lower", "upper", "preserve"]),
    split_camel=st.booleans(),
    ascii=st.sampled_from(["transliterate", "strip", "keep"]),
    leading_digit=st.sampled_from(["prefix", "letter"]),
    max_length=st.integers(min_value=8, max_value=80),
    reserved_words=st.sampled_from(["suffix", "prefix", "ignore"]),
)


@settings(deadline=None, max_examples=300)
@given(NAMES)
def test_default_output_obeys_the_grammar(source: str) -> None:
    """Anything conforms to [a-z_][a-z0-9_]*, at most 63 long, with no doubled underscore."""
    name = conformer().conform(source).name
    assert GRAMMAR.match(name), name
    assert len(name) <= 63  # noqa: PLR2004
    assert "__" not in name


@settings(deadline=None, max_examples=300)
@given(NAMES, CONFIGS)
def test_conforming_is_idempotent(source: str, naming: NamingDefaults) -> None:
    """For any configuration, conforming an output again changes nothing and loses nothing."""
    once = NameConformer(naming).conform(source)
    twice = NameConformer(naming).conform(once.name)
    assert twice.name == once.name
    assert not twice.lossy


@settings(deadline=None, max_examples=200)
@given(st.lists(NAMES, max_size=25))
def test_suffix_policy_always_gives_unique_names(sources: list[str]) -> None:
    """With on_collision: suffix, outputs are unique under case folding and within the limit."""
    names = [r.name for r in conformer(on_collision="suffix").conform_all(sources)]
    assert len({n.casefold() for n in names}) == len(names)
    assert all(len(n) <= 63 for n in names)  # noqa: PLR2004


@settings(deadline=None, max_examples=200)
@given(st.lists(NAMES, max_size=25))
def test_error_policy_never_returns_duplicates(sources: list[str]) -> None:
    """With on_collision: error, either every name is unique or the call fails."""
    try:
        names = [r.name for r in conformer().conform_all(sources)]
    except NamingError:
        assume(condition=False)
    assert len({n.casefold() for n in names}) == len(names)
