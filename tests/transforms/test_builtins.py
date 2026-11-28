"""Text builtins, binary and json casts, privacy builtins, wire encoding (WBS 5.2, 5.5, 5.6)."""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from decimal import Decimal
from typing import Any

import pytest

from map_conform.plan.chain import ChainCompiler
from map_conform.plan.ops import StepError
from map_conform.spec._struct import Issues
from map_conform.spec.model import Defaults, parse_spec
from map_conform.transforms.builtins import builtin_registry
from map_conform.transforms.privacy import RedactDateKwargs
from map_conform.transforms.registry import Context
from map_conform.types.canonical import parse_ctype
from map_conform.types.wire import to_wire


def run(transform: Any, value: object, target: str = "string", **column: Any) -> object:  # noqa: ANN401
    """Compile one column's chain with the real builtins and run it on a value."""
    spec = parse_spec(
        {
            "version": 1,
            "streams": {
                "s": {"columns": {"c": {"type": target, "transform": transform, **column}}}
            },
        }
    )
    col = spec.streams["s"].spec.columns["c"]
    issues = Issues()
    compiled = ChainCompiler(builtin_registry(), spec.defaults, {}, issues).compile(
        col.transform, col, parse_ctype(target), "c"
    )
    assert compiled is not None, [str(i) for i in issues.items]
    return compiled.run(value, Context("s", "c", Defaults(), parse_ctype(target), row=1))


def problems(transform: Any, target: str = "string") -> list[str]:  # noqa: ANN401
    """Compile problems for a chain."""
    spec = parse_spec(
        {
            "version": 1,
            "streams": {"s": {"columns": {"c": {"type": target, "transform": transform}}}},
        }
    )
    col = spec.streams["s"].spec.columns["c"]
    issues = Issues()
    ChainCompiler(builtin_registry(), spec.defaults, {}, issues).compile(
        col.transform, col, parse_ctype(target), "c"
    )
    return [str(i) for i in issues.items]


# --- text ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("transform", "value", "expected"),
    [
        ("trim", "  a b  ", "a b"),
        ({"trim": "*"}, "**a**", "a"),
        ({"strip_chars": "$, "}, " $1,234 ", "1,234"),
        ("lower", "AbC", "abc"),
        ("upper", "AbC", "ABC"),
        ("title", "ada lovelace", "Ada Lovelace"),
        ({"regex_replace": {"pattern": r"[^0-9]", "repl": ""}}, "A-12-b3", "123"),
        ({"regex_replace": {"pattern": "o", "repl": "0", "flags": "i"}}, "fOo", "f00"),
        ({"regex_extract": r"SKU-(\d+)"}, "item SKU-42 x", "42"),
        ({"regex_extract": {"pattern": r"(?P<n>\d+)", "group": "n"}}, "a7", "7"),
        ({"regex_extract": r"(\d+)"}, "none", None),
        ("normalize_unicode", "ﬁle", "file"),
        ({"normalize_unicode": "NFD"}, "é", "é"),
        ("normalize_whitespace", "  a \t\n b  ", "a b"),
        ("remove_control_chars", "a\x00b\x1fc\x7f", "abc"),
        ({"pad": {"width": 5, "fill": "0"}}, "42", "00042"),
        ({"pad": {"width": 4, "side": "right", "fill": "."}}, "ab", "ab.."),
        ({"left": 3}, "abcdef", "abc"),
        ({"right": 2}, "abcdef", "ef"),
        ({"right": 0}, "abc", ""),
        ({"substring": {"start": 1, "length": 3}}, "abcdef", "bcd"),
        ({"substring": {"start": 2}}, "abcdef", "cdef"),
        ({"map_values": {"Y": "yes", "N": "no"}}, "Y", "yes"),
        ({"map_values": {"Y": "yes"}}, "Q", "Q"),
        ({"map_values": {"values": {"Y": "yes"}, "default": "other"}}, "Q", "other"),
        ({"map_values": {"values": {"y": "yes"}, "case_sensitive": False}}, "Y", "yes"),
        ({"null_tokens": ["unknown"]}, "Unknown", None),
        ({"null_tokens": {"tokens": ["unknown"], "case_sensitive": True}}, "Unknown", "Unknown"),
        ("trim", 42, "42"),
    ],
)
def test_text_builtins(transform: Any, value: object, expected: object) -> None:  # noqa: ANN401
    """Each text builtin, before the string cast."""
    assert run(transform, value) == expected


def test_split_produces_a_list_of_strings() -> None:
    """Split changes the stage to list<string>, so no cast is needed."""
    assert run({"split": ";"}, "a; b ;c", target="list<string>") == ["a", "b", "c"]
    assert run({"split": {"sep": ",", "trim": False}}, "a, b", target="list<string>") == ["a", " b"]


def test_text_step_failures() -> None:
    """Bad regex groups and fills fail on the value with a reason."""
    with pytest.raises(StepError, match="no group 2"):
        run({"regex_extract": {"pattern": r"(\d)", "group": 2}}, "1")
    with pytest.raises(StepError, match="fill must be one character"):
        run({"pad": {"width": 3, "fill": "ab"}}, "x")
    with pytest.raises(StepError, match="unknown regex flag"):
        run({"regex_replace": {"pattern": "a", "flags": "q"}}, "a")
    with pytest.raises(StepError, match="a text step got dict"):
        run("trim", {"a": 1})


# --- binary and json -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "value", "expected"),
    [
        ({}, "aGVsbG8=", b"hello"),
        ({"encoding": "hex"}, "68656c6c6f", b"hello"),
        ({"encoding": "utf8"}, "héllo", "héllo".encode()),
    ],
)
def test_binary_cast(kwargs: dict[str, Any], value: str, expected: bytes) -> None:
    """Strict base64, hex or UTF-8 text."""
    assert run({"cast": "binary", **kwargs}, value, target="binary") == expected


def test_binary_cast_is_strict() -> None:
    """Invalid base64 fails rather than decoding loosely."""
    with pytest.raises(StepError, match="not valid base64"):
        run({"cast": "binary"}, "aGVsbG8*", target="binary")
    with pytest.raises(StepError, match="not valid hex"):
        run({"cast": "binary", "encoding": "hex"}, "zz", target="binary")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True), (False, False), (2, True), (1, True), (0, False), (-1, False),
        (0.5, True), (-0.5, False), (0.0, False), (Decimal("2.5"), True), (Decimal(0), False),
        (" YES ", True), ("Off", False), ("2", True), ("-1", False), ("0.0", False),
        ("-0.5", False), ("1e3", True),
    ],
    ids=repr,
)  # fmt: skip
def test_boolean_cast_reads_numbers_as_counters(value: object, *, expected: bool) -> None:
    """Words in any case; a number or numeric text: > 0 is true, 0 or less is false."""
    assert run({"cast": "boolean"}, value, target="boolean") is expected


@pytest.mark.parametrize(
    "value", [float("nan"), Decimal("NaN"), "inf", "maybe", {"a": 1}, [True]], ids=repr
)
def test_boolean_cast_refuses(value: object) -> None:
    """NaN, other text and containers fail loud."""
    with pytest.raises(StepError, match="boolean"):
        run({"cast": "boolean"}, value, target="boolean")


def test_json_cast() -> None:
    """JSON text is decoded once; decimals stay exact; other text is a JSON string."""
    assert run({"cast": "json"}, '{"a": 1.10, "b": [true]}', target="json") == {
        "a": Decimal("1.10"),
        "b": [True],
    }
    assert run({"cast": "json"}, "not json", target="json") == "not json"
    assert run({"cast": "json", "parse_strings": False}, "[1]", target="json") == "[1]"
    assert run({"cast": "json", "sort_keys": True}, {"b": 1, "a": 2}, target="json") == {
        "a": 2,
        "b": 1,
    }
    wired = to_wire(run({"cast": "json"}, '{"a": 1.10}', target="json"), parse_ctype("json"))
    assert wired == '{"a": 1.10}'  # an exact JSON number, as it came


# --- privacy -------------------------------------------------------------------------------


def test_hash_matches_pipelinewise() -> None:
    """HASH is the SHA-256 hex digest; HASH-SKIP-FIRST-n keeps n characters, any n."""
    assert run("hash", "secret") == hashlib.sha256(b"secret").hexdigest()
    skip = run({"hash": {"skip_first": 12}}, "AB-123456789-secret")
    assert skip == "AB-123456789" + hashlib.sha256(b"-secret").hexdigest()
    assert (
        run({"hash": {"algo": "md5", "salt": "pepper"}}, "x")
        == hashlib.md5(  # noqa: S324
            b"pepperx"
        ).hexdigest()
    )


def test_hash_of_typed_values_is_stable() -> None:
    """A value hashed after its cast uses canonical text, not Python's repr."""
    assert run(["trim", "hash"], " 2026-03-14 ") == hashlib.sha256(b"2026-03-14").hexdigest()


@pytest.mark.parametrize(
    ("kwargs", "value", "expected"),
    [
        ({"keep_first": 2, "keep_last": 2}, "4111111111111111", "41************11"),
        ({"keep_last": 4}, "123456789", "*****6789"),
        ({"keep_first": 2, "keep_last": 2}, "abc", "***"),
        ({"keep_first": 1, "char": "#"}, "abcd", "a###"),
    ],
)
def test_mask(kwargs: dict[str, Any], value: str, expected: str) -> None:
    """MASK-STRING-SKIP-ENDS-n; short values are masked entirely, not revealed."""
    assert run({"mask": kwargs}, value) == expected


def test_set_null_and_its_flag() -> None:
    """set_null makes any value null and marks the column nullable."""
    assert run("set_null", "anything") is None
    assert builtin_registry().transforms["set_null"].forces_nullable


def test_redact_date_keeps_the_type() -> None:
    """MASK-DATE keeps the year; to: month keeps the month too; time becomes midnight."""
    registry = builtin_registry().transforms["redact_date"]
    ctx = Context("s", "c", Defaults(), parse_ctype("date"))
    year, month = RedactDateKwargs(to="year"), RedactDateKwargs(to="month")
    assert registry.scalar(dt.date(2026, 3, 14), year, ctx) == dt.date(2026, 1, 1)
    assert registry.scalar(dt.date(2026, 3, 14), month, ctx) == dt.date(2026, 3, 1)
    moment = dt.datetime(2026, 3, 14, 9, 26, 53, tzinfo=dt.UTC)
    assert registry.scalar(moment, year, ctx) == dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


def test_privacy_type_checks() -> None:
    """redact_date needs a temporal value; hash yields a string column."""
    assert problems("redact_date") == ["c.transform: redact_date cannot take the raw value here"]
    hash_step = builtin_registry().transforms["hash"]
    assert str(hash_step.output_stage(parse_ctype("date"), None)) == "string"


# --- wire ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "ctype", "expected"),
    [
        (
            dt.datetime(2026, 3, 14, 9, 26, 53, 5, tzinfo=dt.timezone(dt.timedelta(hours=2))),
            "timestamptz",
            "2026-03-14T07:26:53.000005Z",
        ),
        (
            dt.datetime(2026, 3, 14, 9, 26, 53),  # noqa: DTZ001 -- naive on purpose
            "timestamp",
            "2026-03-14T09:26:53.000000",
        ),
        (dt.date(2026, 3, 14), "date", "2026-03-14"),
        (dt.time(9, 26), "time", "09:26:00.000000"),
        (Decimal("1E+3"), "decimal(10,2)", "1000"),
        (Decimal("1234.50"), "decimal(10,2)", "1234.50"),
        (
            uuid.UUID("{123E4567-E89B-12D3-A456-426614174000}"),
            "uuid",
            "123e4567-e89b-12d3-a456-426614174000",
        ),
        (b"hi", "binary", "aGk="),
        ({"a": [1, None]}, "json", '{"a": [1, null]}'),
        ({"d": dt.date(2026, 1, 2)}, "struct<d: date>", {"d": "2026-01-02"}),
        ([Decimal("1.5")], "list<decimal(5,2)>", ["1.5"]),
        (None, "int64", None),
        (True, "boolean", True),
    ],
)
def test_wire_forms(value: object, ctype: str, expected: object) -> None:
    """Each type's RECORD wire form (Clean-Landing Contract §3)."""
    assert to_wire(value, parse_ctype(ctype)) == expected


# --- nested --------------------------------------------------------------------------------


def test_struct_and_list_casts() -> None:
    """Members cast by declared type; missing members are null; undeclared keys dropped."""
    target = "struct<zip: string, qty: int32, at: timestamptz, tags: list<string>>"
    value = {"zip": "02139", "qty": 3.0, "at": "2026-03-14T09:00:00Z", "extra": 1, "tags": ["a"]}
    assert run(None, value, target=target) == {
        "zip": "02139",
        "qty": 3,
        "at": dt.datetime(2026, 3, 14, 9, tzinfo=dt.UTC),
        "tags": ["a"],
    }
    assert run(None, '{"zip": 1}', target="struct<zip: string, qty: int32>") == {
        "zip": "1",
        "qty": None,
    }
    assert run(None, "[1.5, 2]", target="list<decimal(4,1)>") == [Decimal("1.5"), Decimal("2.0")]


def test_nested_cast_errors_name_the_member() -> None:
    """A failing member or item says which."""
    with pytest.raises(StepError, match=r"member 'qty': not a number"):
        run(None, {"qty": "x"}, target="struct<qty: int32>")
    with pytest.raises(StepError, match="item 1: not a number"):
        run(None, [1, "x"], target="list<int32>")
    with pytest.raises(StepError, match="a struct needs an object"):
        run(None, [1], target="struct<a: int32>")
