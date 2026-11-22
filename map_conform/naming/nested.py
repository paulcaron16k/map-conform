"""Conform member names inside struct shapes (``naming.nested``).

A struct's members are conformed like a stream's columns: the same pipeline, with
collisions checked within each struct. Lists are transparent: the members of
``list<struct<...>>`` are the struct's. Two shapes are supported:

- declared CTypes (``struct<customerID: string, ...>``), and
- tap SCHEMA objects (``{"type": "object", "properties": {...}}``), for undeclared columns
  kept as typed structs (``nested: keep``).

Each returns the conformed shape and a :class:`MemberNames` tree, which
:func:`rename_value` uses to rename the keys of record values at run time.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from map_conform.naming.conform import NameConformer
    from map_conform.types.canonical import CType


def _empty() -> Mapping[str, Any]:
    return MappingProxyType({})


@dataclass(frozen=True)
class MemberNames:
    """Source-to-conformed member names of one struct, and of the structs inside it."""

    names: Mapping[str, str] = field(default_factory=_empty)
    children: Mapping[str, MemberNames] = field(default_factory=_empty)


def conform_ctype(ctype: CType, conformer: NameConformer) -> tuple[CType, MemberNames | None]:
    """Conform the member names of a struct CType, recursively.

    Returns:
        The conformed CType and its name tree, or the CType unchanged and None when it has no
        struct inside or ``naming.nested`` is off.
    """
    if not conformer.naming.nested:
        return ctype, None
    if ctype.kind == "list" and ctype.item is not None:
        item, names = conform_ctype(ctype.item, conformer)
        return replace(ctype, item=item), names
    if ctype.kind != "struct":
        return ctype, None
    sources = [name for name, _ in ctype.members]
    conformed = [c.name for c in conformer.conform_all(sources)]
    members: list[tuple[str, CType]] = []
    children: dict[str, MemberNames] = {}
    for (source, member_type), name in zip(ctype.members, conformed, strict=True):
        inner, inner_names = conform_ctype(member_type, conformer)
        members.append((name, inner))
        if inner_names is not None:
            children[source] = inner_names
    tree = MemberNames(
        MappingProxyType(dict(zip(sources, conformed, strict=True))),
        MappingProxyType(children),
    )
    return replace(ctype, members=tuple(members)), tree


def conform_schema(
    schema: Mapping[str, Any], conformer: NameConformer
) -> tuple[dict[str, Any], MemberNames | None]:
    """Conform the property names of a JSON Schema object, recursively.

    ``required`` lists are renamed with their properties. Other keywords are kept.

    Returns:
        A new schema and its name tree, or a copy and None when there is nothing to conform.
    """
    out = dict(schema)
    if not conformer.naming.nested:
        return out, None
    if isinstance(schema.get("items"), Mapping):
        out["items"], names = conform_schema(schema["items"], conformer)
        return out, names
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return out, None
    sources = list(properties)
    conformed = [c.name for c in conformer.conform_all(sources)]
    mapping = dict(zip(sources, conformed, strict=True))
    new_properties: dict[str, Any] = {}
    children: dict[str, MemberNames] = {}
    for source, name in mapping.items():
        new_properties[name], inner = conform_schema(properties[source], conformer)
        if inner is not None:
            children[source] = inner
    out["properties"] = new_properties
    if isinstance(schema.get("required"), list):
        out["required"] = [mapping.get(r, r) for r in schema["required"]]
    return out, MemberNames(MappingProxyType(mapping), MappingProxyType(children))


def rename_value(value: object, names: MemberNames) -> object:
    """Rename the keys of a nested record value; lists are walked item by item.

    Keys the tree does not know are kept as they are.
    """
    if isinstance(value, Mapping):
        return {
            names.names.get(key, key): (
                rename_value(item, names.children[key]) if key in names.children else item
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [rename_value(item, names) for item in value]
    return value
