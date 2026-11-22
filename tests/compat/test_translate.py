"""SDK stream-map settings translate into the hand-written native spec (WBS 12.1, 12.2)."""

from __future__ import annotations

from typing import Any

import pytest

from map_conform.spec._struct import Issues
from map_conform.spec.model import parse_spec
from map_conform.spec.stream_maps import COMPAT_DEFAULTS, sdk_type, translate
from map_conform.types.canonical import CType
from tests.compat.harness import ours_run
from tests.compat.sdk_cases import MYSTREAM

COMPAT = {k: dict(v) if isinstance(v, dict) else v for k, v in COMPAT_DEFAULTS.items()}


def translated(settings: dict[str, Any]) -> dict[str, Any] | None:
    """Translate, asserting there were no problems."""
    issues = Issues()
    spec = translate(settings, issues)
    assert not issues, [str(i) for i in issues.items]
    return spec


def native(streams: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """A hand-written native spec with the compatibility defaults."""
    return {"version": 1, "defaults": COMPAT, "streams": streams, **extra}


@pytest.mark.parametrize(
    ("stream_maps", "expected"),
    [
        ({"s": None}, native({"s": {"drop": True}})),
        ({"s": "__NULL__"}, native({"s": {"drop": True}})),
        ({"__else__": None, "s": {}}, native({"s": {}}, **{"else": "drop"})),
        ({"s*": {"__alias__": "renamed"}}, native({"s*": {"alias": "renamed"}})),
        ({"s": {"__alias__": "a.b"}}, native({"s": {"alias": "a.b"}})),
        (
            {"s": {"__alias__": "'x_' + __stream_name__"}},
            native({"s": {"alias": {"expr": "'x_' + __stream_name__"}}}),
        ),
        ({"copy": {"__source__": "s"}}, native({"copy": {"source": "s"}})),
        ({"s": {"__filter__": "n > 1"}}, native({"s": {"filter": "record['n'] > 1"}})),
        ({"s": {"__key_properties__": ["id"]}}, native({"s": {"key_properties": ["id"]}})),
        ({"s": {"__key_properties__": None}}, native({"s": {"key_properties": []}})),
        ({"s": {"__else__": None}}, native({"s": {"undeclared": "drop"}})),
        ({"s": {"x": None, "y": "__NULL__"}},
         native({"s": {"columns": {"x": {"drop": True}, "y": {"drop": True}}}})),
        (
            {"s": {"h": "md5(email)", "u": "self.upper()"}},
            native({"s": {"columns": {
                "h": {"expr": "md5(record['email'])", "infer_type": "sdk"},
                "u": {"expr": "self.upper()", "infer_type": "sdk"},
            }}}),
        ),
    ],
)  # fmt: skip
def test_each_feature(stream_maps: dict[str, Any], expected: dict[str, Any]) -> None:
    """Each SDK feature becomes its native equivalent, and both parse to the same spec."""
    spec = translated({"stream_maps": stream_maps})
    assert spec == expected
    assert parse_spec(spec) == parse_spec(expected)


def test_faker_and_flattening_settings() -> None:
    """faker_config and flattening_* become defaults, with or without stream_maps."""
    spec = translated({
        "faker_config": {"seed": 1, "locale": "en_US"},
        "flattening_enabled": True,
        "flattening_max_depth": 2,
        "flattening_separator": ".",
    })  # fmt: skip
    assert spec == {
        "version": 1,
        "defaults": {
            "faker": {"seed": 1, "locale": "en_US"},
            "nested": "flatten",
            "flatten": {"separator": ".", "max_depth": 2},
        },
    }
    assert translated({"flattening_enabled": False}) is None
    assert translated({}) is None


@pytest.mark.parametrize(
    ("stream_maps", "message"),
    [
        ({"__else__": "keep"}, "stream_maps.__else__: only __else__: null is supported"),
        ({"__other__": None}, "stream_maps.__other__: option '__other__' is not expected"),
        ({"s": "x"}, "stream_maps.s: a stream map is a mapping, null or __NULL__"),
        ({"s": {"c": 1}}, "stream_maps.s.c: expected an expression string or null"),
        ({"s": {"__else__": "x"}}, "stream_maps.s.__else__: only __else__: null"),
        ({"s": {"__filter__": 1}}, "stream_maps.s.__filter__: a filter is an expression string"),
    ],
)
def test_unsupported_settings(stream_maps: dict[str, Any], message: str) -> None:
    """What the SDK refuses is refused here, at its setting path."""
    issues = Issues()
    translate({"stream_maps": stream_maps}, issues)
    assert message in str(issues.items[0])


@pytest.mark.parametrize(
    ("expr", "properties", "dropped", "expected"),
    [
        ("float(x)", {}, False, CType("float64")),
        ("int(count-1)", {}, False, CType("int64")),
        ("str(1)", {}, False, CType("string")),
        ("bool(x)", {}, False, CType("boolean")),
        ("json.dumps(x)", {}, False, CType("string")),
        ("datetime.date.today()", {}, False, CType("date")),
        ("datetime.datetime.fromisoformat(x).date()", {}, False, CType("date")),
        ("datetime.datetime.fromisoformat(x)", {}, False, CType("timestamptz")),
        ("'[masked]'", {}, False, CType("string")),
        ("md5(record['x'])", {}, False, CType("string")),
        ("md5(record['x'])", {"c": {"type": "integer"}}, False, {"type": "integer"}),
        ("record['n']", {"n": {"type": "number"}}, True, {"type": "number"}),
        ("record['n']", {"c": {"type": "integer"}}, True, CType("string")),
    ],
)
def test_sdk_type_inference(
    expr: str,
    properties: dict[str, Any],
    dropped: bool,  # noqa: FBT001 -- a parametrized flag
    expected: object,
) -> None:
    """The SDK's _eval_type rules: prefixes, literals, then the existing or passthrough type."""
    ctype, schema = sdk_type(expr, "c", properties, undeclared_dropped=dropped)
    assert (ctype if ctype is not None else schema) == expected


def test_record_column_is_the_records_struct() -> None:
    """_data: record is typed by the tap SCHEMA, as the SDK declares it."""
    ctype, schema = sdk_type("record", "c", {"a": {"type": "string"}}, undeclared_dropped=True)
    assert ctype is None
    assert schema == {"type": ["object", "null"], "properties": {"a": {"type": "string"}}}


def test_native_spec_wins_column_by_column(capsys: pytest.CaptureFixture[str]) -> None:
    """A native column overrides the translated one key by key; compat defaults yield too."""
    stream_maps = {"mystream": {"fixed": "int(count-1)", "__else__": None}}
    spec = {"version": 1, "defaults": {"metadata": "sdc"},
            "streams": {"mystream": {"columns": {"fixed": {"type": "string"}}}}}  # fmt: skip
    out = ours_run(MYSTREAM, stream_maps, {"spec": spec})
    schema = next(m[2] for m in out if m[0] == "SCHEMA")
    assert schema["properties"]["fixed"]["type"] == ["string", "null"]
    assert "_sdc_extracted_at" in schema["properties"]
    record = next(m[2] for m in out if m[0] == "RECORD")
    assert record["fixed"] == "20"
    capsys.readouterr()


def test_config_is_stream_map_config_under_spec_vars() -> None:
    """Config in expressions: stream_map_config, with spec_vars winning."""
    stream_maps = {"mystream": {"a": "config['a']", "b": "config['b']", "__else__": None}}
    settings = {"stream_map_config": {"a": "sdk", "b": "sdk"}, "spec_vars": {"b": "native"}}
    out = ours_run(MYSTREAM, stream_maps, settings)
    record = next(m[2] for m in out if m[0] == "RECORD")
    assert (record["a"], record["b"]) == ("sdk", "native")
