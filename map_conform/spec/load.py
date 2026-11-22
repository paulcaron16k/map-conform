"""Load a conform spec and resolve the rules for each stream (detailed design §3.1).

Loading is: read YAML or JSON -> deep-merge the inline ``spec`` setting over it ->
substitute ``${var}`` / ``${env:NAME}`` -> strict parse. Resolving a tap stream merges, by
presence, ``defaults`` -> every matching glob from least to most specific -> the exact name;
objects merge key by key and lists replace whole.

YAML is read with YAML 1.2 core-schema scalars. PyYAML's YAML 1.1 defaults would turn
``yes``/``no``/``on``/``off`` (and the country code ``NO``) into booleans and ``1:30`` into 90,
which corrupts value lists such as ``true_values``. Duplicate keys are an error.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from map_conform.spec._struct import (
    Issue,
    Issues,
    child,
    dump,
    freeze_mapping,
    parse_dataclass,
    thaw,
)
from map_conform.spec.errors import SpecError
from map_conform.spec.model import (
    DEFAULTS_KEYS,
    STREAM_KEYS,
    Defaults,
    Spec,
    StreamSpec,
    parse_spec,
)

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

if TYPE_CHECKING:
    from yaml.nodes import MappingNode

_VAR = re.compile(r"\$\$\{|\$\{(env:)?([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
_GLOB_CHARS = frozenset("*?[")


# --- Reading ----------------------------------------------------------------------------------


class _Yaml12Loader(yaml.SafeLoader):
    """SafeLoader with YAML 1.2 core-schema scalars and no duplicate keys."""

    yaml_implicit_resolvers: dict[str, list[tuple[str, re.Pattern[str]]]] = {}  # noqa: RUF012 -- PyYAML's class-level registry

    @override
    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Any, Any]:
        """Build a mapping, rejecting duplicate keys."""
        seen: set[object] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                mark = key_node.start_mark
                msg = f"duplicate key {key!r}"
                raise yaml.constructor.ConstructorError(None, None, msg, mark)
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


for _tag, _pattern, _first in [
    ("tag:yaml.org,2002:null", r"^(?:~|null|Null|NULL|)$", ["~", "n", "N", ""]),
    ("tag:yaml.org,2002:bool", r"^(?:true|True|TRUE|false|False|FALSE)$", list("tTfF")),
    (
        "tag:yaml.org,2002:int",
        r"^(?:[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$",
        list("-+0123456789"),
    ),
    (
        "tag:yaml.org,2002:float",
        (
            r"^(?:[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?"
            r"|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$"
        ),
        list("-+.0123456789"),
    ),
]:
    _Yaml12Loader.add_implicit_resolver(_tag, re.compile(_pattern), _first)


def _construct_int(loader: yaml.SafeLoader, node: yaml.ScalarNode) -> int:
    text = loader.construct_scalar(node)
    # Base 0 reads the 0o/0x prefixes; plain digits are decimal even with a leading zero.
    return int(text, 0) if text.startswith(("0o", "0x")) else int(text, 10)


_Yaml12Loader.add_constructor("tag:yaml.org,2002:int", _construct_int)


def read_document(path: str | Path) -> object:
    """Read a YAML (``.yaml``/``.yml``) or JSON (``.json``) spec file.

    Raises:
        SpecError: if the file cannot be read or parsed.
    """
    path = Path(path)
    source = str(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SpecError([Issue("", f"cannot read the spec: {exc.strerror}")], source) from exc
    if path.suffix.lower() == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            where = f"line {exc.lineno}, column {exc.colno}"
            raise SpecError([Issue("", f"invalid JSON at {where}: {exc.msg}")], source) from exc
    if path.suffix.lower() not in {".yaml", ".yml"}:
        raise SpecError([Issue("", "the spec must be .yaml, .yml or .json")], source)
    try:
        return yaml.load(text, Loader=_Yaml12Loader)  # noqa: S506 -- a SafeLoader subclass
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        problem = getattr(exc, "problem", None) or str(exc)
        raise SpecError([Issue("", f"invalid YAML{where}: {problem}")], source) from exc


# --- Merging and substitution -------------------------------------------------------------------


def deep_merge(base: object, override: object) -> object:
    """Merge by presence: mappings merge key by key; anything else (lists too) replaces."""
    if isinstance(base, Mapping) and isinstance(override, Mapping):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = deep_merge(base[key], value) if key in base else value
        return merged
    return override


def substitute(
    data: object,
    variables: Mapping[str, object],
    env: Mapping[str, str],
    issues: Issues,
) -> object:
    """Replace ``${name}``, ``${env:NAME}`` and ``${env:NAME:-default}`` in every string.

    A string that is exactly one ``${name}`` takes the variable's value with its type; inside
    other text the value is formatted. ``$${`` writes a literal ``${``. A macro's own
    parameters are left for expansion. Unknown names are recorded in ``issues``.
    """
    return _Substituter(variables, env, issues).walk(data, "", frozenset())


@dataclass(frozen=True)
class _Substituter:
    variables: Mapping[str, object]
    env: Mapping[str, str]
    issues: Issues

    def walk(self, data: object, path: str, keep: frozenset[str]) -> object:
        if isinstance(data, Mapping):
            out: dict[str, object] = {}
            for key, value in data.items():
                inner = keep
                if path == "macros" and isinstance(value, Mapping):  # the macro's parameters
                    inner = keep | frozenset(value.get("params") or {})
                out[key] = self.walk(value, child(path, key), inner)
            return out
        if isinstance(data, list):
            return [self.walk(v, child(path, i), keep) for i, v in enumerate(data)]
        if isinstance(data, str):
            whole = _VAR.fullmatch(data)
            if whole and whole.group(0) != "$${":
                return self.value(whole, path, keep)
            return _VAR.sub(lambda m: _format(self.value(m, path, keep)), data)
        return data

    def value(self, match: re.Match[str], path: str, keep: frozenset[str]) -> object:
        if match.group(0) == "$${":
            return "${"
        is_env, name, default = match.group(1), match.group(2), match.group(3)
        found: Mapping[str, object] = self.env if is_env else self.variables
        if name in found:
            return found[name]
        if not is_env and name in keep:
            return match.group(0)
        if default is not None:
            return default
        if is_env:
            self.issues.add(path, f"environment variable {name!r} is not set")
        else:
            self.issues.add(path, f"unknown variable ${{{name}}}; set it in spec_vars")
        return match.group(0)


def _format(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value)


def load_spec(
    path: str | Path | None = None,
    inline: Mapping[str, object] | None = None,
    spec_vars: Mapping[str, object] | None = None,
    env: Mapping[str, str] | None = None,
) -> Spec:
    """Load, merge, substitute and strictly parse a spec.

    Args:
        path: The spec file (``spec_path``).
        inline: An inline spec (the ``spec`` setting), deep-merged over the file.
        spec_vars: Values for ``${name}``.
        env: The environment for ``${env:NAME}``; defaults to ``os.environ``.

    Raises:
        SpecError: listing every problem, each with its path.
    """
    if path is None and inline is None:
        raise SpecError([Issue("", "no spec: set spec_path or spec")])
    document: object = read_document(path) if path is not None else {}
    if inline is not None:
        document = deep_merge(document, thaw(inline))
    issues = Issues()
    document = substitute(document, spec_vars or {}, os.environ if env is None else env, issues)
    source = str(path) if path is not None else "the inline spec"
    if issues:
        raise SpecError(issues.items, source)
    return parse_spec(document, source)


# --- Resolving streams --------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedStream:
    """The effective rules for one output stream."""

    tap_stream: str
    """The tap stream the records come from."""
    key: str | None
    """The ``streams`` key of a ``source`` stream (its output name), else None."""
    matched: tuple[str, ...]
    """The ``streams`` keys merged, least specific first."""
    spec: StreamSpec
    settings: Defaults
    raw: Mapping[str, Any]
    """The merged mapping the two were parsed from, for explain output."""


def specificity(pattern: str) -> tuple[int, int, int]:
    """Sort key: globs before exact names, then by literal characters, then by length."""
    literal = sum(1 for c in pattern if c not in _GLOB_CHARS)
    exact = 0 if _GLOB_CHARS & set(pattern) else 1
    return (exact, literal, len(pattern))


def matching_keys(spec: Spec, tap_stream: str) -> list[str]:
    """The non-``source`` keys that match a tap stream, least specific first."""
    keys = [
        key
        for key, rules in spec.streams.items()
        if rules.spec.source is None and fnmatchcase(tap_stream, key)
    ]
    return sorted(keys, key=specificity)  # stable: declaration order breaks ties


def _resolve(
    spec: Spec,
    tap_stream: str,
    key: str | None,
    raws: list[Mapping[str, Any]],
    matched: tuple[str, ...],
) -> ResolvedStream:
    merged: dict[str, Any] = {}
    for raw in raws:
        for name, value in raw.items():
            plain = thaw(value)
            if name == "naming" and isinstance(plain, str):
                plain = {"preset": plain}  # naming: sdk merges like {preset: sdk}
            merged[name] = deep_merge(merged[name], plain) if name in merged else plain
    own = {k: v for k, v in merged.items() if k in STREAM_KEYS}
    overrides = {k: v for k, v in merged.items() if k in DEFAULTS_KEYS}
    issues = Issues()
    where = child("streams", key or tap_stream)
    stream_spec = parse_dataclass(StreamSpec, own, where, issues)
    settings = parse_dataclass(Defaults, deep_merge(dump(spec.defaults), overrides), where, issues)
    if issues or not isinstance(stream_spec, StreamSpec) or not isinstance(settings, Defaults):
        raise SpecError(issues.items)
    return ResolvedStream(tap_stream, key, matched, stream_spec, settings, freeze_mapping(merged))


def resolve_stream(spec: Spec, tap_stream: str) -> ResolvedStream | None:
    """The rules for a tap stream itself, or None when ``else: drop`` drops it unmatched."""
    keys = matching_keys(spec, tap_stream)
    if not keys and spec.else_ == "drop":
        return None
    raws = [spec.streams[k].raw for k in keys]
    return _resolve(spec, tap_stream, None, raws, tuple(keys))


def output_streams(spec: Spec, tap_stream: str) -> list[ResolvedStream]:
    """Every output stream fed by a tap stream: itself (unless dropped) and its copies."""
    out: list[ResolvedStream] = []
    own = resolve_stream(spec, tap_stream)
    if own is not None and not own.spec.drop:
        out.append(own)
    for key, rules in spec.streams.items():
        if rules.spec.source == tap_stream and not rules.spec.drop:
            out.append(_resolve(spec, tap_stream, key, [rules.raw], (key,)))
    return out
