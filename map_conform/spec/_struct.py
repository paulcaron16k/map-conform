"""Strict parsing, dumping and JSON Schema generation for the spec's frozen dataclasses.

One set of type hints drives all three, so the model, the parser and the shipped JSON Schema
cannot drift apart (the Zamboni pattern). Parsing collects every problem with its path rather
than stopping at the first.

Supported annotations: ``str``, ``int``, ``float``, ``bool``, ``None``, ``Any``, ``Literal``,
unions, ``tuple[T, ...]``, ``Mapping[str, T]``, dataclasses, and classes that implement
:class:`Custom`.

Field metadata keys: ``key`` (the spec spelling, e.g. ``else`` for ``else_``), ``doc``
(becomes the schema ``description``) and ``check`` (``value -> problem | None``).
"""

from __future__ import annotations

import dataclasses
import functools
import re
import sys
import types
import typing
from collections.abc import Mapping
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    Protocol,
    TypeVar,
    Union,
    get_args,
    get_origin,
    runtime_checkable,
)

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

DC = TypeVar("DC", bound="DataclassInstance")

_PLAIN_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class Issue:
    """One problem found in a spec, at a path such as ``streams["sheets-*"].columns.id``."""

    path: str
    message: str

    @override
    def __str__(self) -> str:
        """``path: message``."""
        return f"{self.path or '<root>'}: {self.message}"


class Issues:
    """Collects :class:`Issue` objects while a document is parsed."""

    def __init__(self) -> None:
        """Start empty."""
        self.items: list[Issue] = []

    def add(self, path: str, message: str) -> None:
        """Record a problem at ``path``."""
        self.items.append(Issue(path, message))

    def __bool__(self) -> bool:
        """True when any problem was recorded."""
        return bool(self.items)


class Invalid:
    """The type of :data:`INVALID`: a value that had problems, already recorded."""

    @override
    def __repr__(self) -> str:
        """``INVALID``."""
        return "INVALID"


INVALID = Invalid()
"""The one instance of :class:`Invalid`; compare with ``is``."""


@runtime_checkable
class Dumpable(Protocol):
    """A value that knows its own plain-data form."""

    def spec_dump(self) -> object:
        """Return the plain data form of this value."""


class Custom(Protocol):
    """A type that parses, dumps and describes itself."""

    @classmethod
    def spec_parse(cls, data: object, path: str, issues: Issues) -> Any:  # noqa: ANN401
        """Parse ``data`` found at ``path``; return the value or ``INVALID``."""

    def spec_dump(self) -> object:
        """Return the plain data form of this value."""

    @classmethod
    def spec_schema(cls, defs: dict[str, Any]) -> dict[str, Any]:
        """Return the JSON Schema of this type, registering shared parts in ``defs``."""


def child(path: str, key: str | int) -> str:
    """The path of ``key`` inside ``path``: ``a.b``, ``a["odd key"]`` or ``a[3]``."""
    if isinstance(key, int):
        return f"{path}[{key}]"
    if _PLAIN_KEY.match(key):
        return f"{path}.{key}" if path else key
    quoted = key.replace("\\", "\\\\").replace('"', '\\"')
    return f'{path}["{quoted}"]'


def spec_key(field: dataclasses.Field[Any]) -> str:
    """The key a dataclass field is written as in a spec."""
    return field.metadata.get("key", field.name)


@functools.cache
def _hints(cls: type[DataclassInstance]) -> dict[str, Any]:
    return typing.get_type_hints(cls)


def fields_of(cls: type[DataclassInstance]) -> list[tuple[dataclasses.Field[Any], Any]]:
    """The dataclass fields of ``cls`` with their resolved annotations."""
    hints = _hints(cls)
    return [(f, hints[f.name]) for f in dataclasses.fields(cls)]


def _has_default(field: dataclasses.Field[Any]) -> bool:
    return (
        field.default is not dataclasses.MISSING or field.default_factory is not dataclasses.MISSING
    )


def _default(field: dataclasses.Field[Any]) -> object:
    if field.default is not dataclasses.MISSING:
        return field.default
    if field.default_factory is not dataclasses.MISSING:
        return field.default_factory()
    return dataclasses.MISSING


def _type_name(data: object) -> str:
    return {
        type(None): "null",
        bool: "a boolean",
        int: "an integer",
        float: "a number",
        str: "a string",
        list: "a list",
        dict: "a mapping",
    }.get(type(data), type(data).__name__)


def _is_union(tp: object) -> bool:
    return get_origin(tp) in (Union, types.UnionType)


def freeze(data: object) -> object:
    """Make plain data immutable: lists become tuples, mappings become read-only."""
    if isinstance(data, Mapping):
        return types.MappingProxyType({k: freeze(v) for k, v in data.items()})
    if isinstance(data, (list, tuple)):
        return tuple(freeze(v) for v in data)
    return data


def freeze_mapping(data: Mapping[str, object]) -> Mapping[str, Any]:
    """:func:`freeze` for a mapping, typed as one."""
    return types.MappingProxyType({k: freeze(v) for k, v in data.items()})


def thaw(data: object) -> object:
    """Undo :func:`freeze`: tuples become lists and mappings become dicts."""
    if isinstance(data, Mapping):
        return {k: thaw(v) for k, v in data.items()}
    if isinstance(data, tuple):
        return [thaw(v) for v in data]
    return data


def parse(tp: Any, data: object, path: str, issues: Issues) -> Any:  # noqa: ANN401, C901, PLR0911, PLR0912
    """Parse ``data`` as type ``tp``; record problems in ``issues`` and return ``INVALID``."""
    origin = get_origin(tp)
    if tp is Any:
        return freeze(data)
    if tp is type(None) or tp is None:
        if data is None:
            return None
        issues.add(path, f"expected null, got {_type_name(data)}")
        return INVALID
    if isinstance(tp, type) and hasattr(tp, "spec_parse"):
        return tp.spec_parse(data, path, issues)
    if dataclasses.is_dataclass(tp) and isinstance(tp, type):
        return parse_dataclass(tp, data, path, issues)
    if tp is bool:
        if isinstance(data, bool):
            return data
        issues.add(path, f"expected a boolean, got {_type_name(data)}")
        return INVALID
    if tp is int:
        if isinstance(data, int) and not isinstance(data, bool):
            return data
        issues.add(path, f"expected an integer, got {_type_name(data)}")
        return INVALID
    if tp is float:
        if isinstance(data, (int, float)) and not isinstance(data, bool):
            return float(data)
        issues.add(path, f"expected a number, got {_type_name(data)}")
        return INVALID
    if tp is str:
        if isinstance(data, str):
            return data
        issues.add(path, f"expected a string, got {_type_name(data)}")
        return INVALID
    if origin is Literal:
        allowed = get_args(tp)
        if any(data == a and type(data) is type(a) for a in allowed):
            return data
        issues.add(path, f"expected one of {', '.join(map(repr, allowed))}, got {data!r}")
        return INVALID
    if _is_union(tp):
        return _parse_union(tp, data, path, issues)
    if origin is tuple:
        item_type = get_args(tp)[0]
        if not isinstance(data, list):
            issues.add(path, f"expected a list, got {_type_name(data)}")
            return INVALID
        items = [parse(item_type, v, child(path, i), issues) for i, v in enumerate(data)]
        return INVALID if any(i is INVALID for i in items) else tuple(items)
    if origin is Mapping or origin is dict:
        _, value_type = get_args(tp)
        if not isinstance(data, dict):
            issues.add(path, f"expected a mapping, got {_type_name(data)}")
            return INVALID
        out: dict[str, Any] = {}
        for key, value in data.items():
            if not isinstance(key, str):
                issues.add(path, f"keys must be strings, got {key!r}")
                continue
            out[key] = parse(value_type, value, child(path, key), issues)
        if any(v is INVALID for v in out.values()):
            return INVALID
        return types.MappingProxyType(out)
    msg = f"unsupported annotation {tp!r}"
    raise TypeError(msg)


def _parse_union(tp: Any, data: object, path: str, issues: Issues) -> Any:  # noqa: ANN401
    arms = get_args(tp)
    attempts: list[Issues] = []
    for arm in arms:
        scratch = Issues()
        value = parse(arm, data, path, scratch)
        if value is not INVALID and not scratch:
            return value
        attempts.append(scratch)
    # An arm whose shape fits the data explains the problem best ("unknown key" inside a
    # mapping); when no arm fits, say what was expected.
    for arm, scratch in zip(arms, attempts, strict=True):
        if _shape_fits(arm, data) and scratch.items:
            issues.items.extend(scratch.items)
            return INVALID
    names = " or ".join(_describe(a) for a in arms)
    issues.add(path, f"expected {names}, got {_type_name(data)}")
    return INVALID


def _shape_fits(tp: object, data: object) -> bool:
    """Whether ``data`` has the JSON shape ``tp`` parses (its content may still be wrong)."""
    if isinstance(tp, type) and hasattr(tp, "spec_parse"):
        return True
    if dataclasses.is_dataclass(tp) or get_origin(tp) in (Mapping, dict):
        return isinstance(data, dict)
    if get_origin(tp) is tuple:
        return isinstance(data, list)
    return False


def _describe(tp: object) -> str:
    if tp is type(None):
        return "null"
    if get_origin(tp) is Literal:
        return " or ".join(map(repr, get_args(tp)))
    if get_origin(tp) is tuple:
        return "a list"
    if get_origin(tp) in (Mapping, dict) or dataclasses.is_dataclass(tp):
        return "a mapping"
    return {bool: "a boolean", int: "an integer", float: "a number", str: "a string"}.get(
        tp,  # type: ignore[call-overload]
        getattr(tp, "__name__", str(tp)),
    )


def parse_dataclass(cls: type[DC], data: object, path: str, issues: Issues) -> DC | Invalid:
    """Parse a mapping into dataclass ``cls``, rejecting unknown keys."""
    if not isinstance(data, dict):
        issues.add(path, f"expected a mapping, got {_type_name(data)}")
        return INVALID
    fields = fields_of(cls)
    by_key = {spec_key(f): (f, tp) for f, tp in fields}
    for key in data:
        if key not in by_key:
            allowed = ", ".join(sorted(by_key))
            issues.add(child(path, str(key)), f"unknown key; allowed here: {allowed}")
    values: dict[str, Any] = {}
    ok = True
    for key, (field, tp) in by_key.items():
        if key not in data:
            if not _has_default(field):
                issues.add(child(path, key), "required")
                ok = False
            continue
        value = _parse_field(field, tp, data[key], child(path, key), issues)
        if value is INVALID:
            ok = False
        else:
            values[field.name] = value
    if not ok or any(k not in by_key for k in data):
        return INVALID
    return cls(**values)


def _parse_field(
    field: dataclasses.Field[Any],
    tp: object,
    data: object,
    path: str,
    issues: Issues,
) -> Any:  # noqa: ANN401
    value = parse(tp, data, path, issues)
    check = field.metadata.get("check")
    if value is INVALID or value is None or check is None:
        return value
    if problem := check(value):
        issues.add(path, problem)
        return INVALID
    return value


def dump(value: object) -> object:
    """The plain-data form of a parsed value, omitting dataclass fields left at their default."""
    if isinstance(value, Dumpable):
        return value.spec_dump()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        out: dict[str, object] = {}
        for field, _ in fields_of(type(value)):
            item = getattr(value, field.name)
            if _has_default(field) and item == _default(field):
                continue
            out[spec_key(field)] = dump(item)
        return out
    if isinstance(value, Mapping):
        return {k: dump(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [dump(v) for v in value]
    return value


def schema(tp: Any, defs: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN401, PLR0911
    """The JSON Schema (2020-12) for annotation ``tp``; dataclasses go into ``defs``."""
    origin = get_origin(tp)
    if tp is Any:
        return {}
    if tp is type(None) or tp is None:
        return {"type": "null"}
    if isinstance(tp, type) and hasattr(tp, "spec_schema"):
        return tp.spec_schema(defs)
    if dataclasses.is_dataclass(tp) and isinstance(tp, type):
        return dataclass_schema(tp, defs)
    simple = {bool: "boolean", int: "integer", float: "number", str: "string"}
    if tp in simple:
        return {"type": simple[tp]}
    if origin is Literal:
        return {"enum": list(get_args(tp))}
    if _is_union(tp):
        return {"anyOf": [schema(a, defs) for a in get_args(tp)]}
    if origin is tuple:
        return {"type": "array", "items": schema(get_args(tp)[0], defs)}
    if origin in (Mapping, dict):
        return {"type": "object", "additionalProperties": schema(get_args(tp)[1], defs)}
    msg = f"unsupported annotation {tp!r}"
    raise TypeError(msg)


def dataclass_schema(cls: type[DataclassInstance], defs: dict[str, Any]) -> dict[str, Any]:
    """Register ``cls`` in ``defs`` and return a ``$ref`` to it."""
    name = cls.__name__
    if name not in defs:
        defs[name] = {}  # placeholder, so recursive references terminate
        properties: dict[str, Any] = {}
        required: list[str] = []
        for field, tp in fields_of(cls):
            prop = schema(tp, defs)
            if doc := field.metadata.get("doc"):
                prop = {**prop, "description": doc}
            default = _default(field)
            if default is not dataclasses.MISSING:
                prop = {**prop, "default": thaw(dump(default))}
            else:
                required.append(spec_key(field))
            properties[spec_key(field)] = prop
        body: dict[str, Any] = {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
        }
        if cls.__doc__:
            body = {"description": " ".join(cls.__doc__.split()), **body}
        if required:
            body["required"] = required
        defs[name] = body
    return {"$ref": f"#/$defs/{name}"}
