"""The naming: sdk preset reproduces the Singer SDK's conform_name (WBS 12.10, ADR-0008)."""

from __future__ import annotations

import csv
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st
from singer_sdk.sql.sink import SQLSink

from map_conform.naming.conform import NameConformer, NamingError
from map_conform.spec.load import resolve_stream
from map_conform.spec.model import NamingDefaults, parse_spec
from tests.fixtures.paths import FIXTURES
from tests.plan.test_expressions import STRING, plan_for

SDK = NameConformer(NamingDefaults(preset="sdk"))


def sdk_conform_name(name: str) -> str:
    """The SDK's SQL sink conform_name (it does not use self)."""
    return SQLSink.conform_name(cast("SQLSink", None), name)


def golden_sources() -> list[str]:
    """Every source name in the naming golden table."""
    with (FIXTURES / "corpus" / "names.csv").open(encoding="utf-8", newline="") as f:
        return [row["source"] for row in csv.DictReader(f)]


def assert_same(name: str) -> None:
    """Equal to the SDK's, or an error where the SDK fails (nothing left)."""
    try:
        expected = sdk_conform_name(name)
    except IndexError:
        with pytest.raises(NamingError, match="nothing is left under naming: sdk"):
            SDK.conform(name)
        return
    assert SDK.conform(name).name == expected


@pytest.mark.parametrize("name", golden_sources())
def test_golden_names_match_the_sdk(name: str) -> None:
    """Byte for byte on the golden names."""
    assert_same(name)


@given(st.text(max_size=40))
def test_generated_names_match_the_sdk(name: str) -> None:
    """Byte for byte on generated names, including Unicode, digits and whitespace."""
    assert_same(name)


@given(st.text(alphabet="aB1 _-.\t%Ü", max_size=20))
def test_generated_separator_heavy_names_match_the_sdk(name: str) -> None:
    """Names made of the characters the SDK treats specially."""
    assert_same(name)


def test_lossy_changes_are_noted() -> None:
    """Dropped characters and the digit letter are reported as notes."""
    conformed = SDK.conform("1 Café%")
    assert conformed.name == "b_caf"
    assert conformed.lossy


def test_shorthand_and_merging() -> None:
    """naming: sdk is {preset: sdk}; a stream's options merge into it."""
    spec = parse_spec({
        "version": 1,
        "defaults": {"naming": "sdk"},
        "streams": {"s": {"naming": {"on_collision": "suffix"}}, "t": {}},
    })  # fmt: skip
    assert spec.defaults.naming.preset == "sdk"
    s = resolve_stream(spec, "s")
    assert s is not None
    assert (s.settings.naming.preset, s.settings.naming.on_collision) == ("sdk", "suffix")
    raw: dict[str, Any] = {
        "version": 1,
        "streams": {"*": {"naming": "sdk"}, "s": {"naming": {"on_collision": "suffix"}}},
    }
    merged = resolve_stream(parse_spec(raw), "s")
    assert merged is not None
    assert merged.settings.naming.preset == "sdk"


def test_bad_preset_name() -> None:
    """Only sdk is a preset name."""
    with pytest.raises(Exception, match="expected a mapping of naming options or 'sdk'"):
        parse_spec({"version": 1, "defaults": {"naming": "postgres"}})


def test_plan_uses_the_preset() -> None:
    """Column names in a plan follow the SDK: no camel split, no reserved-word suffix."""
    plan, _ = plan_for(
        {}, {"customerID": STRING, "1st Place": STRING, "select": STRING},
        defaults={"naming": "sdk"},
    )  # fmt: skip
    assert [c.name for c in plan.columns] == ["customerid", "bst_place", "select"]
