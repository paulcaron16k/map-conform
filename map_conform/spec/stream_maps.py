"""Translate Singer SDK stream-map settings into a native spec (detailed design §15).

map-conform accepts the settings of meltano-map-transformer unchanged: ``stream_maps``,
``stream_map_config``, ``faker_config`` and ``flattening_*``. They are translated once, at
start-up, into a raw spec merged *under* the native one, so the native spec wins column by
column. Every SDK feature has a native equivalent:

==============================================  =============================================
SDK                                             native
==============================================  =============================================
``stream_maps.<stream or glob>``                ``streams.<stream or glob>``
``<stream>: null`` / ``"__NULL__"``             ``drop: true``
``__else__: null`` (top level)                  ``else: drop``
``__alias__``                                   ``alias`` (a literal, or ``{expr: ...}``)
``__source__``                                  ``source`` on a new output-stream key
``__filter__``                                  ``filter``
``__key_properties__``                          ``key_properties`` (null: none)
``__else__: null`` (stream level)               ``undeclared: drop`` (key properties kept)
``<property>: null`` / ``"__NULL__"``           ``{drop: true}``
``<property>: "<expr>"``                        ``{expr: ..., infer_type: sdk}``
``faker_config``                                ``defaults.faker``
``flattening_enabled`` and friends              ``defaults.nested: flatten`` and ``flatten``
==============================================  =============================================

Expressions are rewritten so that bare record names read ``record['...']``
(:func:`~map_conform.expr.sdk.rewrite_sdk_expression`). An alias is an expression when it
parses and uses no name but ``__stream_name__``; otherwise it is the literal name, as in the
SDK (``aliased.stream`` is a name, ``'aliased_' + __stream_name__`` an expression).

With ``stream_maps`` set, these **compatibility defaults** apply unless the spec sets them,
so that a project moving from meltano-map-transformer keeps its output: column names follow
the SDK's ``conform_name`` (what an SDK SQL target creates), stream names are kept as they
are, no ``_sdc_*`` columns are added (targets add them), nested values keep their shape, and
text is not trimmed or nulled by tokens.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from typing import Any

from map_conform.expr.sdk import rewrite_sdk_expression
from map_conform.spec._struct import Issues, child
from map_conform.types.canonical import CType

SDK_SETTINGS = (
    "stream_maps",
    "stream_map_config",
    "faker_config",
    "flattening_enabled",
    "flattening_max_depth",
    "flattening_separator",
    "flattening_max_key_length",
)
"""The plugin settings meltano-map-transformer takes, accepted here unchanged."""

NULL_STRING = "__NULL__"
ELSE = "__else__"
SPECIAL = frozenset({"__alias__", "__source__", "__filter__", "__key_properties__", ELSE})

COMPAT_DEFAULTS: Mapping[str, Any] = {
    "naming": {"preset": "sdk"},
    "stream": {"name": "preserve"},
    "metadata": "none",
    "nested": "keep",
    "values": {"trim": False, "null_tokens": []},
}
"""Defaults that make translated stream maps give the SDK mapper's output."""


def _is_null(value: object) -> bool:
    return value is None or value == NULL_STRING


def _alias(text: object, path: str, issues: Issues) -> object:
    """A literal alias, or ``{expr: ...}`` when the SDK would evaluate it."""
    if not isinstance(text, str):
        issues.add(path, "an alias is a string")
        return None
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except SyntaxError:
        return text
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    if names - {"__stream_name__"}:
        return text  # the SDK falls back to the literal on an unknown name
    return {"expr": text}


def _special(name: str, value: object, where: str, issues: Issues) -> dict[str, Any]:  # noqa: PLR0911 -- one per option
    """The native keys for one of the SDK's ``__option__`` keys of a stream map."""
    if name == "__source__":
        return {"source": value}
    if name == "__alias__":
        return {"alias": _alias(value, where, issues)}
    if name == "__filter__":
        if not isinstance(value, str):
            issues.add(where, "a filter is an expression string")
            return {}
        return {"filter": rewrite_sdk_expression(value)}
    if name == "__key_properties__":
        if value is not None and not isinstance(value, (list, tuple)):
            issues.add(where, "key properties are a list of names, or null for none")
            return {}
        return {"key_properties": list(value or [])}
    if not _is_null(value):  # __else__
        issues.add(where, f"only {ELSE}: null is supported, as in the SDK")
        return {}
    return {"undeclared": "drop"}


def _stream(key: str, rules: Mapping[str, Any], path: str, issues: Issues) -> dict[str, Any]:
    out: dict[str, Any] = {}
    columns: dict[str, Any] = {}
    for name, value in rules.items():
        where = child(path, name)
        if name in SPECIAL:
            out.update(_special(name, value, where, issues))
        elif _is_null(value):
            columns[name] = {"drop": True}
        elif isinstance(value, str):
            columns[name] = {"expr": rewrite_sdk_expression(value), "infer_type": "sdk"}
        else:
            issues.add(where, f"expected an expression string or null for {key}.{name}")
    if columns:
        out["columns"] = columns
    return out


def _streams(stream_maps: Mapping[str, Any], issues: Issues) -> dict[str, Any]:
    """The ``streams`` (and ``else``) of the translated spec."""
    out: dict[str, Any] = {"streams": {}}
    for key, rules in stream_maps.items():
        path = child("stream_maps", key)
        if key == ELSE:
            if _is_null(rules):
                out["else"] = "drop"
            else:
                issues.add(path, f"only {ELSE}: null is supported, as in the SDK")
        elif key.startswith("__"):
            issues.add(path, f"option {key!r} is not expected here")
        elif _is_null(rules):
            out["streams"][key] = {"drop": True}
        elif isinstance(rules, Mapping):
            out["streams"][key] = _stream(key, rules, path, issues)
        else:
            issues.add(path, "a stream map is a mapping, null or __NULL__")
    return out


def _sdk_defaults(settings: Mapping[str, Any]) -> dict[str, Any]:
    """``defaults`` from faker_config and the flattening settings."""
    defaults: dict[str, Any] = {}
    if faker := settings.get("faker_config"):
        defaults["faker"] = {k: faker[k] for k in ("seed", "locale") if k in faker}
    if settings.get("flattening_enabled"):
        defaults["nested"] = "flatten"
        flatten = {
            option: settings[f"flattening_{option}"]
            for option in ("separator", "max_depth", "max_key_length")
            if settings.get(f"flattening_{option}") is not None
        }
        if flatten:
            defaults["flatten"] = flatten
    return defaults


def translate(settings: Mapping[str, Any], issues: Issues) -> dict[str, Any] | None:
    """The raw spec for the SDK settings in ``settings``, or None when there are none.

    Problems are recorded in ``issues`` with their setting paths.
    """
    defaults = _sdk_defaults(settings)
    stream_maps = settings.get("stream_maps")
    if stream_maps is None:
        return {"version": 1, "defaults": defaults} if defaults else None
    compat = {k: dict(v) if isinstance(v, Mapping) else v for k, v in COMPAT_DEFAULTS.items()}
    return {"version": 1, "defaults": {**compat, **defaults}, **_streams(stream_maps, issues)}


# --- SDK type inference (WBS 12.2) --------------------------------------------------------------

_PASSTHROUGH = re.compile(r"""^record\[(['"])(?P<name>.+)\1\]$""")
_PREFIXES: tuple[tuple[tuple[str, ...], CType], ...] = (
    (("float(",), CType("float64")),
    (("int(",), CType("int64")),
    (("str(",), CType("string")),
    (("bool(",), CType("boolean")),
    (("json.dumps(",), CType("string")),
)


def prefix_type(expr: str) -> CType | None:
    """The type the SDK decides from the expression's text alone, or None."""
    text = expr.strip()
    for prefixes, ctype in _PREFIXES:
        if text.startswith(prefixes):
            return ctype
    if text.startswith(("datetime.date.", "datetime.date(")) or text.endswith(".date()"):
        return CType("date")
    if text.startswith(("datetime.datetime.", "datetime.datetime(")):
        return CType("timestamptz")
    if len(text) > 1 and text[0] == text[-1] == "'":
        return CType("string")
    return None


def sdk_type(
    expr: str, key: str, properties: Mapping[str, Any], *, undeclared_dropped: bool
) -> tuple[CType | None, Mapping[str, Any] | None]:
    """The column type the SDK mapper would declare for ``key: <expr>``.

    Returns:
        ``(ctype, None)`` for a type the expression decides, or ``(None, schema)`` for the
        JSON Schema to take the type from (the record's, an existing property's, or a string).
    """
    text = expr.strip()
    if text == "record":  # the whole record, typed by the tap SCHEMA, as the SDK declares it
        return None, {"type": ["object", "null"], "properties": dict(properties)}
    if (decided := prefix_type(text)) is not None:
        return decided, None
    match = _PASSTHROUGH.match(text)
    passthrough = match["name"] if match else None
    existing = None if undeclared_dropped else properties.get(key)
    existing = existing or (properties.get(passthrough) if passthrough else None)
    if existing:
        return None, existing
    return CType("string"), None
