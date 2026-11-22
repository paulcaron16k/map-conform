"""Flatten nested objects into columns, with the Singer SDK's semantics (WBS 12.7).

For ``nested: flatten``, undeclared object properties of the tap SCHEMA become columns named
by joining the path with ``flatten.separator``, down to ``flatten.max_depth`` levels. This is
the SDK's algorithm (``singer_sdk.helpers._flattening``) re-implemented, so that keys,
types and values are the same:

- A key at least ``max_key_length`` long is shortened from its first part on: each part is
  camelized and reduced to its capitals (``user_profile`` -> ``up``), or to its first three
  letters when that leaves one letter or none, until the key fits.
- Below the depth limit, objects and arrays become JSON text, and their SCHEMA type a string.
- A typeless property becomes a nullable string; for ``anyOf``-style properties the first
  branch is used.
- Two paths flattening to the same key are an error.

Columns the spec declares by name (the object itself, or a source of a column) are not
flattened: the spec decides what happens to them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

from map_conform.types.jsontext import dumps

_LOWER = re.compile(r"[a-z]")
_CAMEL = re.compile(r"(?:^|_)(.)")


class FlattenError(ValueError):
    """Two nested paths flatten to the same column name."""


def _camelize(word: str) -> str:
    """``inflection.camelize``: upper the first letter and each letter after ``_``."""
    return _CAMEL.sub(lambda m: m.group(1).upper(), word)


def flatten_key(name: str, parents: list[str], separator: str, max_key_length: int) -> str:
    """The flattened key, shortened like the SDK's when it is too long."""
    parts = [*parents, name]
    index = 0
    while len(separator.join(parts)) >= max_key_length and index < len(parts):
        reduced = _LOWER.sub("", _camelize(parts[index]))
        parts[index] = (reduced if len(reduced) > 1 else parts[index][:3]).lower()
        index += 1
    return separator.join(parts)


def _types(schema: Mapping[str, Any]) -> list[str]:
    declared = schema.get("type", [])
    return [declared] if isinstance(declared, str) else list(declared)


@dataclass(frozen=True)
class Flattener:
    """Flattens one stream's SCHEMA properties and records."""

    separator: str
    max_depth: int
    max_key_length: int
    keep: frozenset[str]
    """Top-level properties the spec names; they are left as they are."""
    typed_leaves: bool = False
    """For a declared shape: arrays and objects below the depth keep their declared types
    (list, struct, json) instead of becoming JSON text as the SDK makes them."""

    def properties(self, properties: Mapping[str, Any]) -> dict[str, Any]:
        """The flattened SCHEMA properties, in the SDK's order.

        Raises:
            FlattenError: when two paths give the same key.
        """
        items: list[tuple[str, Any]] = []
        for name, schema in properties.items():
            if name in self.keep:
                items.append((name, schema))
            else:
                items.extend(self._schema({name: schema}, [], 0))
        out: dict[str, Any] = {}
        for key, schema in items:
            if key in out:
                msg = f"two nested paths flatten to the column {key!r}"
                raise FlattenError(msg)
            out[key] = schema
        return out

    def _schema(
        self, properties: Mapping[str, Any], parents: list[str], level: int
    ) -> list[tuple[str, Any]]:
        items: list[tuple[str, Any]] = []
        for name, schema in properties.items():
            key = flatten_key(name, parents, self.separator, self.max_key_length)
            if "type" in schema:
                types = _types(schema)
                if "object" in types and "properties" in schema and level < self.max_depth:
                    items.extend(self._schema(schema["properties"], [*parents, name], level + 1))
                elif self.typed_leaves:
                    items.append((key, schema))
                elif "array" in types or ("object" in types and self.max_depth > 0):
                    items.append(
                        (key, {"type": ["string", "null"] if "null" in types else "string"})
                    )
                else:
                    items.append((key, schema))
            elif (
                (composite := next(iter(schema.values()), None))
                and isinstance(composite, list)
                and (first := composite[0])
            ):
                # anyOf and friends: the first branch, made nullable (or dropped, as the SDK
                # does, when it is not a string, array or object)
                if isinstance(first, Mapping) and first.get("type") in (
                    "string",
                    "array",
                    "object",
                ):
                    items.append((key, {**first, "type": ["null", first["type"]]}))
            else:
                items.append((key, {"type": ["null", "string"]}))
        return items

    def record(self, record: Mapping[str, Any], schema: Mapping[str, Any]) -> dict[str, Any]:
        """The record with nested objects flattened as its SCHEMA was."""
        out: dict[str, Any] = {}
        for name, value in record.items():
            if name in self.keep:
                out[name] = value
            else:
                out.update(self._record({name: value}, schema, [], 0))
        return out

    def _record(
        self, node: Mapping[str, Any], schema: Mapping[str, Any], parents: list[str], level: int
    ) -> dict[str, Any]:
        items: dict[str, Any] = {}
        for name, value in node.items():
            key = flatten_key(name, parents, self.separator, self.max_key_length)
            if isinstance(value, MutableMapping) and key not in schema and level < self.max_depth:
                items.update(self._record(value, schema, [*parents, name], level + 1))
            elif isinstance(value, (dict, list)):
                items[key] = dumps(value, compact=True)
            else:
                items[key] = value
        return items
