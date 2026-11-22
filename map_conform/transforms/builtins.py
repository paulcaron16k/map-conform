"""The registry of every builtin transform and cast."""

from __future__ import annotations

import functools

from map_conform.transforms import casts, numeric, privacy, text
from map_conform.transforms.registry import Registry

_MODULES = (text, casts, numeric, privacy)


@functools.cache
def builtin_registry() -> Registry:
    """The builtins, registered once."""
    registry = Registry()
    for module in _MODULES:
        module.register(registry)
    return registry
