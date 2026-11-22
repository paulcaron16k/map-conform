"""Text builtins, usually run before the cast (detailed design §6.1).

They take the raw value or a string. A raw value that is not a string (a number from a JSON
tap) is turned into text first. The stage is unchanged, except ``split``, which produces a
``list<string>``.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from map_conform.errors import StepFailed
from map_conform.transforms.registry import NoKwargs, Registry, Transform
from map_conform.types.canonical import CType

if TYPE_CHECKING:
    from map_conform.transforms.registry import Context

_UNSET: Any = object()
_FLAGS = {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL, "x": re.VERBOSE}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_WHITESPACE = re.compile(r"\s+")


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (Mapping, list)):
        raise StepFailed(f"a text step got {type(value).__name__}")
    return str(value)


def _flags(text: str) -> int:
    flags = 0
    for letter in text:
        if letter not in _FLAGS:
            raise StepFailed(f"unknown regex flag {letter!r}; use i, m, s or x")
        flags |= _FLAGS[letter]
    return flags


@dataclass(frozen=True)
class TrimKwargs:
    """Characters to trim; whitespace by default."""

    chars: str | None = None


@dataclass(frozen=True)
class NullTokensKwargs:
    """Strings that become null."""

    tokens: tuple[str, ...] = ()
    case_sensitive: bool = False


@dataclass(frozen=True)
class CharsKwargs:
    """Characters to strip from both ends."""

    chars: str = ""


@dataclass(frozen=True)
class RegexReplaceKwargs:
    """A regular-expression substitution."""

    pattern: str = ""
    repl: str = ""
    flags: str = ""


@dataclass(frozen=True)
class RegexExtractKwargs:
    """Keep one group of the first match; no match gives null."""

    pattern: str = ""
    group: int | str = 1
    flags: str = ""


@dataclass(frozen=True)
class NormalizeKwargs:
    """A Unicode normalisation form."""

    form: Literal["NFC", "NFD", "NFKC", "NFKD"] = "NFKC"


@dataclass(frozen=True)
class PadKwargs:
    """Pad to a width."""

    width: int = 0
    fill: str = " "
    side: Literal["left", "right"] = "left"


@dataclass(frozen=True)
class LengthKwargs:
    """A number of characters."""

    n: int = 0


@dataclass(frozen=True)
class SubstringKwargs:
    """Characters from ``start`` (0-based), ``length`` of them or to the end."""

    start: int = 0
    length: int | None = None


@dataclass(frozen=True)
class MapValuesKwargs:
    """Replace whole values; unmapped values are kept unless ``default`` is given."""

    values: Mapping[str, Any] = field(default_factory=dict)
    default: Any = _UNSET
    case_sensitive: bool = True


@dataclass(frozen=True)
class SplitKwargs:
    """Split on a separator into a list of strings."""

    sep: str = ","
    trim: bool = True


def _trim(value: object, k: TrimKwargs, _ctx: Context) -> object:
    return _text(value).strip(k.chars)


def _null_tokens(value: object, k: NullTokensKwargs, _ctx: Context) -> object:
    text = _text(value)
    if k.case_sensitive:
        return None if text in k.tokens else value
    return None if any(text.casefold() == t.casefold() for t in k.tokens) else value


def _strip_chars(value: object, k: CharsKwargs, _ctx: Context) -> object:
    return _text(value).strip(k.chars)


def _regex_replace(value: object, k: RegexReplaceKwargs, _ctx: Context) -> object:
    return re.sub(k.pattern, k.repl, _text(value), flags=_flags(k.flags))


def _regex_extract(value: object, k: RegexExtractKwargs, _ctx: Context) -> object:
    match = re.search(k.pattern, _text(value), flags=_flags(k.flags))
    if match is None:
        return None
    try:
        return match.group(k.group)
    except (IndexError, KeyError) as exc:
        raise StepFailed(f"the pattern has no group {k.group!r}") from exc


def _pad(value: object, k: PadKwargs, _ctx: Context) -> object:
    if len(k.fill) != 1:
        raise StepFailed("fill must be one character")
    text = _text(value)
    return text.rjust(k.width, k.fill) if k.side == "left" else text.ljust(k.width, k.fill)


def _map_values(value: object, k: MapValuesKwargs, _ctx: Context) -> object:
    text = _text(value)
    if k.case_sensitive:
        if text in k.values:
            return k.values[text]
    else:
        for source, target in k.values.items():
            if source.casefold() == text.casefold():
                return target
    return value if k.default is _UNSET else k.default


def _split(value: object, k: SplitKwargs, _ctx: Context) -> object:
    parts = _text(value).split(k.sep)
    return [p.strip() for p in parts] if k.trim else parts


def register(registry: Registry) -> None:
    """Add the text builtins."""
    simple: list[tuple[str, Any]] = [
        ("lower", lambda v, _k, _c: _text(v).lower()),
        ("upper", lambda v, _k, _c: _text(v).upper()),
        ("title", lambda v, _k, _c: _text(v).title()),
        ("normalize_whitespace", lambda v, _k, _c: _WHITESPACE.sub(" ", _text(v)).strip()),
        ("remove_control_chars", lambda v, _k, _c: _CONTROL.sub("", _text(v))),
    ]
    for name, fn in simple:
        registry.register(Transform(name, fn, kwargs=NoKwargs))
    registry.register(Transform("trim", _trim, kwargs=TrimKwargs, positional="chars"))
    registry.register(
        Transform("null_tokens", _null_tokens, kwargs=NullTokensKwargs, positional="tokens")
    )
    registry.register(
        Transform("strip_chars", _strip_chars, kwargs=CharsKwargs, positional="chars")
    )
    registry.register(Transform("regex_replace", _regex_replace, kwargs=RegexReplaceKwargs))
    registry.register(
        Transform("regex_extract", _regex_extract, kwargs=RegexExtractKwargs, positional="pattern")
    )
    registry.register(
        Transform(
            "normalize_unicode",
            lambda v, k, _c: unicodedata.normalize(k.form, _text(v)),
            kwargs=NormalizeKwargs,
            positional="form",
        )
    )
    registry.register(Transform("pad", _pad, kwargs=PadKwargs, positional="width"))
    registry.register(
        Transform("left", lambda v, k, _c: _text(v)[: k.n], kwargs=LengthKwargs, positional="n")
    )
    registry.register(
        Transform(
            "right",
            lambda v, k, _c: _text(v)[-k.n :] if k.n else "",
            kwargs=LengthKwargs,
            positional="n",
        )
    )
    registry.register(
        Transform(
            "substring",
            lambda v, k, _c: _text(v)[k.start : None if k.length is None else k.start + k.length],
            kwargs=SubstringKwargs,
        )
    )
    registry.register(
        Transform("map_values", _map_values, kwargs=MapValuesKwargs, positional="values")
    )
    registry.register(
        Transform(
            "split",
            _split,
            kwargs=SplitKwargs,
            positional="sep",
            produces=lambda _stage, _k: CType("list", item=CType("string")),
        )
    )
