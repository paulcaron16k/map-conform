"""nested: flatten has the Singer SDK's flattening semantics (WBS 12.7).

Keys, SCHEMA properties and records are compared with the SDK's own functions in
``singer_sdk.helpers._flattening``.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from singer_sdk.helpers._flattening import flatten_key as sdk_flatten_key
from singer_sdk.helpers._flattening import flatten_record as sdk_flatten_record
from singer_sdk.helpers._flattening import flatten_schema as sdk_flatten_schema

from map_conform.naming.flatten import Flattener, FlattenError, flatten_key
from tests.plan.test_expressions import plan_for, problems

OBJ = "object"
NESTED: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "foo": {
            "type": ["object", "null"],
            "properties": {
                "bar": {
                    "type": ["object", "null"],
                    "properties": {
                        "baz": {"type": OBJ, "properties": {"qux": {"type": "string"}}},
                        "n": {"type": ["number", "null"]},
                    },
                },
                "tags": {"type": "array", "items": {"type": "string"}},
            },
        },
        "loose": {},
        "either": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "user_profile_with_a_rather_long_name": {
            "type": OBJ,
            "properties": {"address_line_number_one": {"type": "string"}},
        },
    },
}
RECORD: dict[str, Any] = {
    "id": "1",
    "foo": {
        "bar": {"baz": {"qux": "q"}, "n": Decimal("3.14")},
        "tags": ["a", "b"],
    },
    "loose": {"k": [1, Decimal("2.5")]},
    "either": "x",
    "user_profile_with_a_rather_long_name": {"address_line_number_one": "a1"},
}

names = st.text(alphabet="abcdefXYZ_0", min_size=1, max_size=12)


@given(names, st.lists(names, max_size=4), st.sampled_from(["__", ".", "_"]), st.integers(1, 40))
def test_keys_match_the_sdk(name: str, parents: list[str], separator: str, limit: int) -> None:
    """flatten_key, including its shortening of long keys."""
    expected = sdk_flatten_key(name, parents, separator, max_key_length=limit)
    assert flatten_key(name, parents, separator, limit) == expected


@pytest.mark.parametrize("depth", [0, 1, 2, 3])
@pytest.mark.parametrize(("separator", "limit"), [("__", 255), (".", 255), ("__", 20)])
def test_schema_and_records_match_the_sdk(depth: int, separator: str, limit: int) -> None:
    """SCHEMA properties and records, at each depth, separator and key length."""
    expected_schema = sdk_flatten_schema(
        copy.deepcopy(NESTED), depth, separator, max_key_length=limit
    )
    flattener = Flattener(separator, depth, limit, frozenset())
    properties = flattener.properties(NESTED["properties"])
    assert properties == expected_schema["properties"]
    expected_record = sdk_flatten_record(
        copy.deepcopy(RECORD), expected_schema, depth, separator, max_key_length=limit
    )
    assert flattener.record(RECORD, properties) == expected_record


def test_duplicate_keys_are_errors() -> None:
    """Two paths giving the same key fail, as in the SDK."""
    properties = {
        "a__b": {"type": "string"},
        "a": {"type": OBJ, "properties": {"b": {"type": "string"}}},
    }
    with pytest.raises(FlattenError, match="'a__b'"):
        Flattener("__", 1, 255, frozenset()).properties(properties)
    found = problems({}, properties, defaults={"nested": "flatten"})
    assert found == ["streams.s.nested: two nested paths flatten to the column 'a__b'"]


def test_plan_flattens_undeclared_objects() -> None:
    """Flattened keys become columns; declared ones are typed; named objects are kept."""
    properties = {
        "id": {"type": "string"},
        "user": {
            "type": OBJ,
            "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
        },
        "meta": {"type": OBJ, "properties": {"k": {"type": "string"}}},
    }
    columns = {"user__age": {"type": "int16"}, "meta": {"type": "json"}}
    plan, executor = plan_for(
        columns, properties, defaults={"nested": "flatten", "naming": {"collapse": False}}
    )
    assert {c.name: str(c.ctype) for c in plan.columns} == {
        "id": "string",
        "user__name": "string",
        "user__age": "int16",
        "meta": "json",
    }
    record = {"id": "1", "user": {"name": "a", "age": 7}, "meta": {"k": "v"}}
    assert executor.run(record, {}, 1) == {
        "id": "1",
        "user__name": "a",
        "user__age": 7,
        "meta": '{"k": "v"}',
    }


def test_default_naming_collapses_the_separator() -> None:
    """With the default naming, user__name conforms to user_name; naming: sdk keeps it."""
    properties = {"user": {"type": OBJ, "properties": {"name": {"type": "string"}}}}
    plan, _ = plan_for({}, properties, defaults={"nested": "flatten"})
    assert [c.name for c in plan.columns] == ["user_name"]
    plan, _ = plan_for({}, properties, defaults={"nested": "flatten", "naming": "sdk"})
    assert [c.name for c in plan.columns] == ["user__name"]
