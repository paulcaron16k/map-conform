"""Declared shapes for nested columns (WBS 8.10, decided 2026-11-22).

A column's ``shape`` is a JSON Schema for its object (or array) value. It alone decides the
column's type, and, when the column is flattened, the flattened columns and their types, so
the output SCHEMA and the RECORD and BATCH types do not change when the tap's schema drifts.

Applied to a value, a shape:

- **drops members it does not declare**, reporting each one so the executor can count it and
  log it once per stream;
- **fills a missing or null member** with the member's JSON Schema ``default``;
- **normalises an empty object or array** to the member's ``default`` when it has one, so
  ``{}``, ``[]`` and a missing member all land the same way: ``null``, ``{}`` or ``[]``.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

_MISSING = object()

Report = Callable[[str], None]
"""Called with the dotted path of each member a shape drops."""


def _types(schema: Mapping[str, Any]) -> set[str]:
    declared = schema.get("type", [])
    return {declared} if isinstance(declared, str) else set(declared)


@dataclass(frozen=True)
class Shape:
    """A compiled JSON Schema for one nested value."""

    schema: Mapping[str, Any]
    default: Any = _MISSING
    members: Mapping[str, Shape] | None = None
    """For an object with ``properties``: its declared members."""
    item: Shape | None = None
    """For an array with ``items``: the item shape."""
    open_members: bool = field(default=False)
    """An object without ``properties``: any members are kept."""

    @classmethod
    def of(cls, schema: Mapping[str, Any]) -> Shape:
        """Compile a JSON Schema."""
        types = _types(schema)
        members = None
        if "properties" in schema:
            members = {k: cls.of(v) for k, v in schema["properties"].items()}
        item = cls.of(schema["items"]) if isinstance(schema.get("items"), Mapping) else None
        return cls(
            schema,
            schema.get("default", _MISSING),
            members,
            item,
            open_members="object" in types and members is None,
        )

    @property
    def has_default(self) -> bool:
        """Whether the schema gives a ``default``."""
        return self.default is not _MISSING

    def fill(self) -> Any:  # noqa: ANN401 -- a JSON value
        """A fresh copy of the default (or None)."""
        return copy.deepcopy(self.default) if self.has_default else None

    def conform(self, value: object, path: str, report: Report) -> object:
        """The value with undeclared members dropped and defaults applied."""
        if isinstance(value, str) and (self.members is not None or self.item is not None):
            try:
                value = json.loads(value, parse_float=Decimal)  # JSON text of a nested value
            except json.JSONDecodeError:
                return value  # the column's cast reports it
        if value is None or (value in ({}, []) and isinstance(value, (dict, list))):
            return self.fill() if self.has_default else value
        if self.members is not None and isinstance(value, Mapping):
            out: dict[str, object] = {}
            for name, member in self.members.items():
                inner = f"{path}.{name}" if path else name
                out[name] = member.conform(value.get(name), inner, report)
                if out[name] is None and name not in value and not member.has_default:
                    del out[name]  # stays missing; the cast or flattening makes it null
            for name in value:
                if name not in self.members:
                    report(f"{path}.{name}" if path else name)
            return out
        if self.item is not None and isinstance(value, list):
            return [self.item.conform(v, f"{path}[*]", report) for v in value]
        return value
