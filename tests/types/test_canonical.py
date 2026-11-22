"""CType strings parse, normalise aliases and reject malformed types."""

from __future__ import annotations

import pytest

from map_conform.types.canonical import CType, CTypeError, ctype_problem, parse_ctype


@pytest.mark.parametrize(
    ("text", "canonical"),
    [
        ("boolean", "boolean"),
        ("bool", "boolean"),
        ("smallint", "int16"),
        ("int", "int32"),
        ("integer", "int32"),
        ("bigint", "int64"),
        ("long", "int64"),
        ("real", "float32"),
        ("float", "float32"),
        ("double", "float64"),
        ("decimal(18,2)", "decimal(18,2)"),
        ("numeric( 10 , 0 )", "decimal(10,0)"),
        ("decimal(76,76)", "decimal(76,76)"),
        ("text", "string"),
        ("string(40)", "string(40)"),
        ("varchar(255)", "string(255)"),
        ("timestamp_ntz", "timestamp"),
        ("timestamp_tz", "timestamptz"),
        ("TimestampTZ", "timestamptz"),
        ("double precision", "float64"),
        ("timestamp with time zone", "timestamptz"),
        ("TIMESTAMP WITHOUT TIME ZONE", "timestamp"),
        ("character varying(30)", "string(30)"),
        ("bytes", "binary"),
        ("blob", "binary"),
        ("variant", "json"),
        ("array<string>", "list<string>"),
        ("list<decimal(10,2)>", "list<decimal(10,2)>"),
        ("struct<street: string, zip:string(10)>", "struct<street: string, zip: string(10)>"),
        ("struct<a: list<struct<b: int>>>", "struct<a: list<struct<b: int32>>>"),
    ],
)
def test_parse_and_canonical_spelling(text: str, canonical: str) -> None:
    """Aliases normalise, and the canonical spelling parses back to the same CType."""
    ctype = parse_ctype(text)
    assert str(ctype) == canonical
    assert parse_ctype(canonical) == ctype


def test_structure() -> None:
    """Parameters and members are kept on the CType."""
    assert parse_ctype("decimal(12,4)") == CType("decimal", precision=12, scale=4)
    struct = parse_ctype("struct<a: int64, b: list<uuid>>")
    assert struct.members == (("a", CType("int64")), ("b", CType("list", item=CType("uuid"))))


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("decimel", "unknown type 'decimel'"),
        ("decimal", "needs a precision and scale"),
        ("decimal(0,0)", "precision must be 1-76"),
        ("decimal(77,2)", "precision must be 1-76"),
        ("decimal(5,6)", "scale cannot exceed"),
        ("varchar", "varchar needs a length"),
        ("string(0)", "at least 1"),
        ("list<>", "expected a type name"),
        ("list<string", "expected '>'"),
        ("struct<a: int, a: int>", "duplicate struct member 'a'"),
        ("struct<>", "expected a type name"),
        ("int64 extra", "trailing text"),
        ("", "expected a type name"),
    ],
)
def test_invalid_types(text: str, problem: str) -> None:
    """Malformed types are rejected with a reason."""
    with pytest.raises(CTypeError, match=problem):
        parse_ctype(text)
    assert problem in (ctype_problem(text) or "")


def test_ctype_problem_is_none_for_valid() -> None:
    """A valid type has no problem."""
    assert ctype_problem("timestamptz") is None
