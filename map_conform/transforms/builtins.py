"""The registry of every builtin transform and cast."""

from __future__ import annotations

import dataclasses
import functools
from types import MappingProxyType

from map_conform.transforms import casts, nested, numeric, privacy, temporal, text
from map_conform.transforms.registry import Registry

_MODULES = (text, casts, numeric, temporal, nested, privacy)

DOCS = MappingProxyType(
    {
        "assume_tz": "Place a naive timestamp in tz, giving an aware one.",
        "clamp": "Limit a number to [min, max], or fail outside it.",
        "date_from_timestamp": "The date of a timestamp, in tz when given.",
        "hash": "Hex digest of the value's text, with salt; skip_first keeps a clear prefix.",
        "left": "The first n characters.",
        "lower": "Lowercase text.",
        "map_values": "Replace listed values; others become default when it is set.",
        "mask": "Replace characters with char, keeping keep_first and keep_last.",
        "normalize_unicode": "Unicode normalisation (NFKC by default).",
        "normalize_whitespace": "Collapse runs of whitespace to one space and trim.",
        "null_tokens": "Null for any of the tokens (e.g. N/A, -).",
        "pad": "Pad text to width with fill, on the left or right.",
        "redact_date": "Keep only the year, or the year and month; the type is kept.",
        "regex_extract": "A group of the first match, or null.",
        "regex_replace": "Replace every match of pattern with repl.",
        "remove_control_chars": "Remove control characters.",
        "right": "The last n characters.",
        "round": "Round half away from zero to ndigits.",
        "scale": "Multiply by factor, exactly for decimals (e.g. cents to units).",
        "set_null": "Always null; the column becomes nullable.",
        "split": "Split text into a list of strings.",
        "strip_chars": "Remove every listed character, e.g. currency symbols and commas.",
        "substring": "length characters from start.",
        "title": "Title Case text.",
        "to_local": "The wall-clock time in tz, as a naive timestamp.",
        "to_utc": "An aware timestamp in UTC (explicit; timestamptz output is always UTC).",
        "trim": "Remove surrounding whitespace, or chars.",
        "truncate": "Truncate a date or timestamp to unit.",
        "upper": "Uppercase text.",
    }
)
"""One line per builtin, shown by ``map-conform functions``."""


@functools.cache
def builtin_registry() -> Registry:
    """The builtins, registered once."""
    registry = Registry()
    for module in _MODULES:
        module.register(registry)
    for name, transform in registry.transforms.items():
        if not transform.doc and name in DOCS:
            registry.transforms[name] = dataclasses.replace(transform, doc=DOCS[name])
    return registry
