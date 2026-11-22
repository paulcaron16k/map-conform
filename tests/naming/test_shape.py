"""Declared shapes: stable flattened columns, empty values, dropped members (WBS 8.10)."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import pytest

from map_conform.naming.shape import Shape
from map_conform.spec.errors import SpecError
from map_conform.spec.load import load_spec
from tests.plan.test_expressions import plan_for

if TYPE_CHECKING:
    from pathlib import Path

SHAPE: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "name": {"type": ["string", "null"]},
        "tags": {"type": "array", "items": {"type": "string"}, "default": []},
        "prefs": {"type": "object", "default": {}},
        "address": {
            "type": "object",
            "properties": {"zip": {"type": "string"}, "geo": {"type": "object", "default": None}},
        },
    },
}
LEAVES = {
    "user__id": "int64",
    "user__name": "string",
    "user__tags": "list<string>",
    "user__prefs": "json",
    "user__address__zip": "string",
    "user__address__geo": "json",
}
DEFAULTS = {"naming": {"collapse": False}, "flatten": {"max_depth": 2}}
TAP: dict[str, Any] = {
    "id": {"type": "string"},
    "user": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
    },
}


def flattened(tap: dict[str, Any] = TAP, **column: Any) -> tuple[Any, Any]:
    """A plan whose user column is flattened from SHAPE."""
    spec = {"user": {"shape": SHAPE, "flatten": True, **column}}
    return plan_for(spec, tap, defaults=DEFAULTS)


def test_conform_drops_fills_and_normalises() -> None:
    """Undeclared members are reported and dropped; missing and empty members get defaults."""
    dropped: list[str] = []
    value = {"id": 1, "extra": 2, "tags": [], "address": {"zip": "1", "x": 3}}
    out = Shape.of(SHAPE).conform(value, "", dropped.append)
    assert out == {"id": 1, "tags": [], "prefs": {}, "address": {"zip": "1", "geo": None}}
    assert sorted(dropped) == ["address.x", "extra"]
    text = Shape.of(SHAPE).conform(json.dumps({"prefs": {}}), "", dropped.append)
    assert text == {"tags": [], "prefs": {}}  # JSON text is read; missing members stay missing


def test_empty_containers_take_the_default() -> None:
    """{} and [] land as the member's default: null, {} or []."""
    shape = Shape.of({"type": "object", "properties": {
        "a": {"type": "array", "default": None},
        "b": {"type": "object", "default": []},
        "c": {"type": "array"},
    }})  # fmt: skip
    assert shape.conform({"a": [], "b": {}, "c": []}, "", print) == {"a": None, "b": [], "c": []}


def test_flattened_columns_come_from_the_shape() -> None:
    """The leaf columns and their types come from the shape, not the tap."""
    plan, _ = flattened()
    assert {c.name: str(c.ctype) for c in plan.columns} == {"id": "string", **LEAVES}


@pytest.mark.parametrize(
    "drift",
    [
        {"user": {"type": "object", "properties": {"id": {"type": "string"}}}},  # widened
        {"user": {"type": "object", "properties": {"new": {"type": "boolean"}}}},  # added
        {"user": {"type": ["object", "null"]}},  # properties dropped
        {},  # the whole property dropped
    ],
)
def test_tap_schema_drift_leaves_the_schema_unchanged(drift: dict[str, Any]) -> None:
    """Byte for byte the same output SCHEMA whatever the tap says about the nested column."""
    baseline, _ = flattened()
    drifted, _ = flattened({"id": TAP["id"], **drift})
    assert json.dumps(drifted.schema, sort_keys=True) == json.dumps(baseline.schema, sort_keys=True)


def test_records_get_defaults_and_drop_members(caplog: pytest.LogCaptureFixture) -> None:
    """Missing, null and empty members land as their defaults; extras are counted, logged once."""
    _, executor = flattened()
    records = [
        {"id": "a", "user": {"id": 1, "name": "x", "tags": ["t"], "prefs": {"k": 1},
                             "address": {"zip": "9", "geo": {"lat": 1}}}},
        {"id": "b", "user": {"id": 2, "tags": [], "prefs": {}, "extra": 1}},
        {"id": "c", "user": None},
        {"id": "d", "user": {"extra": 2}},
    ]  # fmt: skip
    with caplog.at_level(logging.WARNING):
        out = [executor.run(r, {}, i) for i, r in enumerate(records, 1)]
    assert out[0] == {"id": "a", "user__id": 1, "user__name": "x", "user__tags": ["t"],
                      "user__prefs": '{"k": 1}', "user__address__zip": "9",
                      "user__address__geo": '{"lat": 1}'}  # fmt: skip
    empty: dict[str, Any] = {"user__tags": [], "user__prefs": "{}", "user__address__zip": None,
             "user__address__geo": None, "user__name": None}  # fmt: skip
    assert out[1] == {"id": "b", "user__id": 2, **empty}
    assert out[2] == {"id": "c", "user__id": None, **empty}
    assert executor.metrics.members_dropped == {("user", "extra"): 2}
    warnings = [r for r in caplog.records if "not in the declared shape" in r.getMessage()]
    assert len(warnings) == 1


def test_a_leaf_can_have_its_own_rules() -> None:
    """A spec for a leaf keeps its transform and takes its type from the shape."""
    _, executor = plan_for(
        {"user": {"shape": SHAPE, "flatten": True},
         "user__name": {"transform": "upper", "default": "?"}},
        TAP, defaults=DEFAULTS,
    )  # fmt: skip
    row = executor.run({"id": "a", "user": {"name": "ann"}}, {}, 1)
    assert row is not None
    assert row["user__name"] == "ANN"
    row = executor.run({"id": "a", "user": {}}, {}, 2)
    assert row is not None
    assert row["user__name"] == "?"


def test_stream_flattening_uses_the_shape() -> None:
    """With nested: flatten a shaped column is flattened from its shape, others from the tap."""
    tap = {**TAP, "other": {"type": "object", "properties": {"k": {"type": "string"}}}}
    plan, _ = plan_for({"user": {"shape": SHAPE}}, tap,
                       defaults={"nested": "flatten", "naming": "sdk",
                                 "flatten": {"max_depth": 2}})  # fmt: skip
    assert [c.name for c in plan.columns] == ["id", *LEAVES, "other__k"]


def test_unflattened_shape_types_the_column() -> None:
    """A shape on a column kept whole types it, fills defaults and drops members."""
    plan, executor = plan_for({"user": {"shape": SHAPE}}, TAP)
    user = next(c for c in plan.columns if c.name == "user_")  # user is a reserved word
    assert str(user.ctype).startswith("struct<id: int64, name: string, tags: list<string>")
    row = executor.run({"id": "a", "user": {"id": 1, "junk": 0}}, {}, 1)
    assert row is not None
    assert row["user_"]["tags"] == []
    assert row["user_"]["prefs"] == "{}"
    assert executor.metrics.members_dropped == {("user_", "junk"): 1}  # by output name


def test_shape_from_a_file(tmp_path: Path) -> None:
    """A shape given as a path is read relative to the spec file."""
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas" / "user.json").write_text(json.dumps(SHAPE))
    spec_file = tmp_path / "conform.yml"
    spec_file.write_text("version: 1\nstreams:\n  s:\n    columns:\n"
                         "      user: {shape: schemas/user.json, flatten: true}\n")  # fmt: skip
    spec = load_spec(spec_file)
    assert spec.streams["s"].spec.columns["user"].shape is not None
    spec_file.write_text(spec_file.read_text().replace("user.json", "nope.json"))
    with pytest.raises(SpecError, match=r"streams.s.columns.user.shape: cannot read"):
        load_spec(spec_file)
