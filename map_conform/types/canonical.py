"""The canonical type system: parse and print CType strings (detailed design §4).

A CType string such as ``decimal(18,2)``, ``varchar(40)`` or ``struct<street: string>`` is
parsed into a frozen :class:`CType`. Aliases are normalised, so ``str()`` always gives the
canonical spelling. Mappings to JSON Schema and Arrow live beside this module.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from typing import Literal

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

Kind = Literal[
    "boolean",
    "int16",
    "int32",
    "int64",
    "float32",
    "float64",
    "decimal",
    "string",
    "date",
    "time",
    "timestamp",
    "timestamptz",
    "uuid",
    "binary",
    "json",
    "struct",
    "list",
]

MAX_DECIMAL_PRECISION = 76
"""decimal256 holds 76 digits; decimal128 holds 38."""

_SCALARS: dict[str, Kind] = {
    "boolean": "boolean",
    "bool": "boolean",
    "int16": "int16",
    "smallint": "int16",
    "int32": "int32",
    "int": "int32",
    "integer": "int32",
    "int64": "int64",
    "bigint": "int64",
    "long": "int64",
    "float32": "float32",
    "real": "float32",
    "float": "float32",
    "float64": "float64",
    "double": "float64",
    "string": "string",
    "text": "string",
    "date": "date",
    "time": "time",
    "timestamp": "timestamp",
    "timestamp_ntz": "timestamp",
    "timestamptz": "timestamptz",
    "timestamp_tz": "timestamptz",
    "uuid": "uuid",
    "binary": "binary",
    "bytes": "binary",
    "blob": "binary",
    "json": "json",
    "variant": "json",
}
_DECIMALS = {"decimal", "numeric"}
_STRINGS = {"string", "varchar"}
_LISTS = {"list", "array"}
_MEMBER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class CTypeError(ValueError):
    """A string that is not a valid CType."""


@dataclass(frozen=True)
class CType:
    """A canonical type. Only the fields that apply to ``kind`` are set."""

    kind: Kind
    precision: int | None = None
    scale: int | None = None
    length: int | None = None
    members: tuple[tuple[str, CType], ...] = ()
    item: CType | None = None

    def __post_init__(self) -> None:
        """Reject shapes no parse could produce."""
        if self.kind == "decimal" and (self.precision is None or self.scale is None):
            raise CTypeError(f"decimal needs a precision and scale: {self!r}")
        if self.kind == "list" and self.item is None:
            raise CTypeError(f"list needs an item type: {self!r}")

    @property
    def decimal_params(self) -> tuple[int, int]:
        """``(precision, scale)`` of a decimal."""
        if self.precision is None or self.scale is None:
            raise CTypeError(f"{self} is not a decimal")
        return self.precision, self.scale

    @property
    def list_item(self) -> CType:
        """The item type of a list."""
        if self.item is None:
            raise CTypeError(f"{self} is not a list")
        return self.item

    @override
    def __str__(self) -> str:
        """The canonical spelling, e.g. ``decimal(18,2)`` or ``list<string>``."""
        if self.kind == "decimal":
            return f"decimal({self.precision},{self.scale})"
        if self.kind == "string" and self.length is not None:
            return f"string({self.length})"
        if self.kind == "struct":
            return "struct<" + ", ".join(f"{n}: {t}" for n, t in self.members) + ">"
        if self.kind == "list":
            return f"list<{self.item}>"
        return self.kind


_MULTI_WORD = (
    (re.compile(r"\bdouble\s+precision\b", re.IGNORECASE), "double"),
    (re.compile(r"\btimestamp\s+with\s+time\s+zone\b", re.IGNORECASE), "timestamptz"),
    (re.compile(r"\btimestamp\s+without\s+time\s+zone\b", re.IGNORECASE), "timestamp"),
    (re.compile(r"\bcharacter\s+varying\b", re.IGNORECASE), "varchar"),
)
"""SQL type names of several words, as taps write them in x-sql-datatype hints."""


def parse_ctype(text: str) -> CType:
    """Parse a CType string, accepting the documented aliases and SQL multi-word names.

    Raises:
        CTypeError: if ``text`` is not a valid CType.
    """
    for pattern, alias in _MULTI_WORD:
        text = pattern.sub(alias, text)
    parser = _Parser(text)
    ctype = parser.ctype()
    parser.skip_space()
    if parser.pos != len(text):
        raise parser.error("unexpected trailing text")
    return ctype


def ctype_problem(text: str) -> str | None:
    """Return why ``text`` is not a valid CType, or None if it is."""
    try:
        parse_ctype(text)
    except CTypeError as exc:
        return str(exc)
    return None


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def error(self, message: str) -> CTypeError:
        return CTypeError(f"{message} at position {self.pos} in {self.text!r}")

    def skip_space(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def word(self) -> str:
        self.skip_space()
        match = re.compile(r"[A-Za-z_][A-Za-z0-9_]*").match(self.text, self.pos)
        if not match:
            raise self.error("expected a type name")
        self.pos = match.end()
        return match.group(0)

    def expect(self, char: str) -> None:
        self.skip_space()
        if not self.text.startswith(char, self.pos):
            raise self.error(f"expected {char!r}")
        self.pos += 1

    def peek(self, char: str) -> bool:
        self.skip_space()
        return self.text.startswith(char, self.pos)

    def integer(self) -> int:
        self.skip_space()
        match = re.compile(r"\d+").match(self.text, self.pos)
        if not match:
            raise self.error("expected an integer")
        self.pos = match.end()
        return int(match.group(0))

    def ctype(self) -> CType:
        name = self.word().lower()
        if name in _DECIMALS:
            return self._decimal()
        if name in _STRINGS and self.peek("("):
            self.expect("(")
            length = self.integer()
            self.expect(")")
            if length < 1:
                raise self.error("string length must be at least 1")
            return CType("string", length=length)
        if name == "varchar":
            raise self.error("varchar needs a length; use string for unbounded text")
        if name in _LISTS:
            self.expect("<")
            item = self.ctype()
            self.expect(">")
            return CType("list", item=item)
        if name == "struct":
            return self._struct()
        if name in _SCALARS:
            return CType(_SCALARS[name])
        raise self.error(f"unknown type {name!r}")

    def _decimal(self) -> CType:
        if not self.peek("("):
            raise self.error("decimal needs a precision and scale, e.g. decimal(18,2)")
        self.expect("(")
        precision = self.integer()
        self.expect(",")
        scale = self.integer()
        self.expect(")")
        if not 1 <= precision <= MAX_DECIMAL_PRECISION:
            raise self.error(f"decimal precision must be 1-{MAX_DECIMAL_PRECISION}")
        if scale > precision:
            raise self.error("decimal scale cannot exceed its precision")
        return CType("decimal", precision=precision, scale=scale)

    def _struct(self) -> CType:
        self.expect("<")
        members: list[tuple[str, CType]] = []
        while True:
            name = self.word()
            if not _MEMBER.match(name):
                raise self.error(f"invalid struct member name {name!r}")
            if any(name == existing for existing, _ in members):
                raise self.error(f"duplicate struct member {name!r}")
            self.expect(":")
            members.append((name, self.ctype()))
            if self.peek(","):
                self.expect(",")
                continue
            self.expect(">")
            return CType("struct", members=tuple(members))
