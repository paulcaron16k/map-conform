"""The Singer SDK's own stream-map test cases (``tests/core/test_mapper.py``, v0.54.9).

``MYSTREAM`` and ``SAMPLE`` are the SDK tests' input streams; ``CASES`` are their stream-map
configs, by the SDK's test ids. Values that the SDK tests build from Python objects (its
``CustomObj``) are given as the text they serialize to, since map-conform reads JSON.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

Stream = tuple[dict[str, Any], list[str], list[dict[str, Any]]]
"""(SCHEMA, key properties, records)."""

MYSTREAM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "email": {"type": ["string"]},
        "count": {"type": ["integer", "null"]},
        "user": {
            "type": ["object", "null"],
            "properties": {
                "id": {"type": ["integer", "null"]},
                "sub": {
                    "type": ["object", "null"],
                    "properties": {
                        "num": {"type": ["integer", "null"]},
                        "custom_obj": {"type": ["string", "null"]},
                    },
                    "additionalProperties": True,
                },
                "some_numbers": {"type": ["array", "null"], "items": {"type": ["number"]}},
            },
            "additionalProperties": True,
        },
        "joined_at": {"type": ["string", "null"], "format": "date-time"},
    },
    "required": ["email"],
}


def _user(n: int, obj: str, numbers: tuple[str, str]) -> dict[str, Any]:
    return {
        "id": n,
        "sub": {"num": n, "custom_obj": f"obj-{obj}"},
        "some_numbers": [Decimal(numbers[0]), Decimal(numbers[1])],
    }


MYSTREAM: dict[str, Stream] = {
    "mystream": (
        MYSTREAM_SCHEMA,
        [],
        [
            {"email": "alice@example.com", "count": 21,
             "user": _user(1, "hello", ("3.14", "2.718")), "joined_at": "2022-01-01T00:00:00Z"},
            {"email": "bob@example.com", "count": 13, "user": _user(2, "world", ("10.32", "1.618")),
             "joined_at": "2022-01-01T00:00:00Z"},
            {"email": "charlie@example.com", "count": 19,
             "user": _user(3, "hello", ("1.414", "1.732")), "joined_at": "2022-01-01T00:00:00Z"},
        ],
    )
}  # fmt: skip


def _strings(*names: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {name: {"type": ["string", "null"]} for name in names},
    }


SAMPLE: dict[str, Stream] = {
    "repositories": (
        _strings("name", "owner_email", "description", "create_date"),
        [],
        [
            {"name": name, "owner_email": f"sample{i}@example.com",
             "description": f"Comment {'ABCD'[i - 1]}", "create_date": f"{2018 + i}-01-01"}
            for i, name in enumerate(
                ["tap-something", "my-tap-something", "target-something", "not-atap"], 1
            )
        ],
    ),
    "foobars": (_strings("the", "brown"), [], [{"the": "quick"}, {"brown": "fox"}]),
    "singular": (_strings("foo"), [], [{"foo": "bar"}]),
    "nested_jellybean": (
        {
            "type": "object",
            "properties": {
                "id": {"type": ["integer", "null"]},
                "custom_fields": {
                    "type": ["array", "null"],
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": ["integer", "null"]},
                            "value": {"oneOf": [{"type": ["string"]}, {"type": ["integer"]},
                                                {"type": ["boolean"]}]},
                        },
                    },
                },
            },
        },
        [],
        [
            {"id": 123, "custom_fields": [{"id": 1, "value": "abc"}, {"id": 2, "value": 1212},
                                          {"id": 3, "value": None}]},
            {"id": 124, "custom_fields": [{"id": 1, "value": "foo"}, {"id": 2, "value": 9009},
                                          {"id": 3, "value": True}]},
        ],
    ),
}  # fmt: skip

_NO_FLAT = {"flattening_enabled": False, "flattening_max_depth": 0}
_CUSTOM = 'dict([(x["id"], x["value"]) for x in custom_fields])'

CASES: dict[str, tuple[dict[str, Stream], dict[str, Any], dict[str, Any]]] = {
    # test_mapped_stream
    "no_map": (MYSTREAM, {}, _NO_FLAT),
    "keep_all_fields": (MYSTREAM, {"mystream": {"email_hash": "md5(email)"}}, _NO_FLAT),
    "only_mapped_fields": (MYSTREAM, {"mystream": {
        "email_hash": "md5(email)", "email_hash_sha256": "sha256(email)",
        "fixed_count": "int(count-1)", "__else__": None}}, _NO_FLAT),
    "only_mapped_fields_null_string": (MYSTREAM, {"mystream": {
        "email_hash": "md5(email)", "fixed_count": "int(count-1)", "__else__": "__NULL__"}},
        _NO_FLAT),
    "changed_key_properties": (MYSTREAM, {"mystream": {
        "email_hash": "md5(email)", "__key_properties__": ["email_hash"], "__else__": None}},
        _NO_FLAT),
    "sourced_stream_1": (MYSTREAM, {"mystream": None,
                                    "sourced_stream_1": {"__source__": "mystream"}}, _NO_FLAT),
    "sourced_stream_1_null_string": (MYSTREAM, {
        "mystream": "__NULL__", "sourced_stream_1": {"__source__": "mystream"}}, _NO_FLAT),
    "sourced_stream_2": (MYSTREAM, {"sourced_stream_2": {"__source__": "mystream"},
                                    "__else__": None}, _NO_FLAT),
    "aliased_stream": (MYSTREAM, {"mystream": {"__alias__": "aliased_stream"}}, _NO_FLAT),
    "aliased_stream_not_expr": (MYSTREAM, {"mystream": {"__alias__": "aliased.stream"}},
                                _NO_FLAT),
    "aliased_stream_quoted": (MYSTREAM, {"mystream": {"__alias__": "'__stream_name__'"}},
                              _NO_FLAT),
    "builtin_variable_stream_name": (MYSTREAM, {"mystream": {"source_table": "__stream_name__"}},
                                     _NO_FLAT),
    "builtin_variable_stream_name_alias": (MYSTREAM, {
        "mystream": {"__alias__": "'aliased_' + __stream_name__"}}, _NO_FLAT),
    "builtin_variable_stream_name_alias_expr": (MYSTREAM, {
        "mystream": {"__alias__": "__stream_name__.upper()"}}, _NO_FLAT),
    "builtin_variable_original_stream_name_alias": (MYSTREAM, {"mystream": {
        "__alias__": "'aliased'", "stream_name": "__stream_name__",
        "original_stream_name": "__original_stream_name__"}}, _NO_FLAT),
    "builtin_variable_original_stream_name_no_alias": (MYSTREAM, {"mystream": {
        "stream_name": "__stream_name__", "original_stream_name": "__original_stream_name__"}},
        _NO_FLAT),
    "builtin_variable_self": (MYSTREAM, {"mystream": {"email": "self.upper()", "__else__": None}},
                              _NO_FLAT),
    "builtin_variable_underscore": (MYSTREAM, {
        "mystream": {"email": "_['email'].upper()", "__else__": None}}, _NO_FLAT),
    "flatten_depth_0": (MYSTREAM, {}, {"flattening_enabled": True, "flattening_max_depth": 0}),
    "flatten_depth_1": (MYSTREAM, {}, {"flattening_enabled": True, "flattening_max_depth": 1}),
    "flatten_all": (MYSTREAM, {}, {"flattening_enabled": True, "flattening_max_depth": 2}),
    "flatten_all_with_dot_separator": (MYSTREAM, {}, {
        "flattening_enabled": True, "flattening_max_depth": 2, "flattening_separator": "."}),
    "map_and_flatten": (MYSTREAM, {"mystream": {
        "email_hash": "md5(email)", "__key_properties__": ["email_hash"]}},
        {"flattening_enabled": True, "flattening_max_depth": 10}),
    "drop_property": (MYSTREAM, {"mystream": {"email": None}}, _NO_FLAT),
    "drop_property_null_string": (MYSTREAM, {"mystream": {"email": "__NULL__"}}, _NO_FLAT),
    "non_pk_passthrough": (MYSTREAM, {"mystream": {"count": "count", "__else__": None}},
                           _NO_FLAT),
    "record_to_column": (MYSTREAM, {"mystream": {"_data": "record", "__else__": None}}, _NO_FLAT),
    "fake_credit_card_number": (MYSTREAM, {
        "mystream": {"cc": "fake.credit_card_number()", "__else__": None}},
        {**_NO_FLAT, "faker_config": {"locale": "en_US", "seed": 123456}}),
    "fake_email_seed_instance": (MYSTREAM, {"mystream": {
        "email": "fake.seed_instance(email) or fake.email()", "__else__": None}},
        {**_NO_FLAT, "faker_config": {"locale": "en_US"}}),
    "dates": (MYSTREAM, {"mystream": {
        "joined_date": "datetime.datetime.fromisoformat(joined_at).date()",
        "joined_timestamp": "float(datetime.datetime.fromisoformat(joined_at).timestamp())",
        "some_datetime": "datetime.datetime.fromisoformat(config['some_date_string'])"}},
        {"stream_map_config": {"some_date_string": "2024-10-10T10:10:10Z"}}),
    "json_dumps": (MYSTREAM, {"mystream": {"user": "json.dumps(user, default=str)"}}, _NO_FLAT),
    "filter_records": (MYSTREAM, {"mystream": {"__filter__": "count < 20"}}, _NO_FLAT),
    "filter_records_cast_to_bool": (MYSTREAM, {"mystream": {"__filter__": "bool(count < 20)"}},
                                    _NO_FLAT),
    "remove_stream": (MYSTREAM, {"mystream": "__NULL__"}, _NO_FLAT),
    # test_map_transforms, test_clone_and_alias_transforms, test_filter_transforms,
    # test_wildcard_transforms
    "transform_expressions": (SAMPLE, {
        "repositories": {
            "repo_name": "_['name']",
            "email_domain": "owner_email.split('@')[1]",
            "email_hash": "md5(config['hash_seed'] + owner_email)",
            "description": "'[masked]'",
            "description2": "str('[masked]')",
            "create_year": "int(datetime.date.fromisoformat(create_date).year)",
            "int_test": "int('0')",
            "__else__": None,
        },
        "nested_jellybean": {
            "custom_fields": "__NULL__",
            "custom_field_1": f"{_CUSTOM}.get(1)",
            "custom_field_2": f"int({_CUSTOM}.get(2)) if {_CUSTOM}.get(2) else None",
            "custom_field_3": f"bool({_CUSTOM}.get(3)) if {_CUSTOM}.get(3) else None",
        },
    }, {"stream_map_config": {"hash_seed": "super_secret_hash_seed"}}),
    "clone_and_alias": (SAMPLE, {
        "repositories": {"__alias__": "repositories_aliased"},
        "repositories_clone_1": {"__source__": "repositories"},
        "repositories_clone_2": {"__source__": "repositories"},
        "__else__": None,
    }, {}),
    "filter": (SAMPLE, {
        "repositories": {
            "__filter__": "'tap-' in name or 'target-' in name",
            "name": "_['name']",
            "__else__": None,
        },
        "__else__": None,
    }, {}),
    "wildcard": (SAMPLE, {"*s": {"db_name": "'database'"}}, {}),
}  # fmt: skip
