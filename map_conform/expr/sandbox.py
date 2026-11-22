"""The safety envelope of the expression language (detailed design §7).

Expressions are untrusted text from a spec, so what they can reach is closed:

- **Attributes** are read only on values of the types in :data:`ALLOWED_TYPES` (and on those
  classes themselves), never when the name starts with ``_``, never ``format``,
  ``format_map`` or ``mro`` (which can reach attributes or classes indirectly), and never a
  method that mutates a list, dict or set, so one column cannot change what the next sees.
- **Modules** are reached through :class:`ModuleProxy`, which exposes an explicit list of
  names and nothing that changes global state (no ``decimal.setcontext``).
- **Sizes** are bounded where one short expression could exhaust memory: repetition,
  powers, shifts, padding, format widths, ``range`` and comprehension lengths.

Generators, frames, code objects, functions' globals and classes outside the list are never
reachable, because no attribute access on them is allowed.
"""

from __future__ import annotations

import datetime as dt
import decimal
import json
import math
import re
import sys
import uuid
from types import MappingProxyType, ModuleType
from typing import TYPE_CHECKING, Any

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping

MAX_LENGTH = 1_000_000
"""Longest string, bytes or sequence an expression may build by repetition or padding."""
MAX_ITEMS = 100_000
"""Most items one comprehension, or one ``range``, may produce."""
MAX_EXPONENT = 10_000
"""Largest integer exponent or shift."""

ALLOWED_TYPES: tuple[type, ...] = (
    str,
    bytes,
    int,
    float,
    complex,
    bool,
    type(None),
    decimal.Decimal,
    dt.date,
    dt.datetime,
    dt.time,
    dt.timedelta,
    dt.tzinfo,
    uuid.UUID,
    list,
    tuple,
    dict,
    set,
    frozenset,
    MappingProxyType,
    re.Pattern,
    re.Match,
)
"""Types whose public attributes and methods an expression may use."""

_DENIED = frozenset({"format", "format_map", "mro"})
_MUTATORS = frozenset(
    {
        "append",
        "extend",
        "insert",
        "pop",
        "remove",
        "clear",
        "sort",
        "reverse",
        "update",
        "setdefault",
        "popitem",
        "add",
        "discard",
        "difference_update",
        "intersection_update",
        "symmetric_difference_update",
    }
)
_MUTABLE = (list, dict, set)
_PADDING = frozenset({"ljust", "rjust", "center", "zfill", "expandtabs"})


class SandboxError(Exception):
    """An expression tried to leave the safety envelope."""


class ModuleProxy:
    """A read-only view of a module that exposes only the listed names."""

    __slots__ = ("_exposed", "_name")

    def __init__(self, module: ModuleType, names: Iterable[str]) -> None:
        """Expose ``names`` of ``module``."""
        self._name = module.__name__
        self._exposed: Mapping[str, object] = MappingProxyType(
            {name: getattr(module, name) for name in names}
        )

    def attribute(self, name: str) -> object:
        """The exposed attribute.

        Raises:
            SandboxError: for a name the proxy does not expose.
        """
        try:
            return self._exposed[name]
        except KeyError:
            msg = f"{self._name}.{name} is not available in expressions"
            raise SandboxError(msg) from None

    def names(self) -> tuple[str, ...]:
        """The exposed names, sorted."""
        return tuple(sorted(self._exposed))

    @override
    def __repr__(self) -> str:
        """``<module datetime (read-only)>``."""
        return f"<module {self._name} (read-only)>"


MODULES: Mapping[str, ModuleProxy] = MappingProxyType(
    {
        "datetime": ModuleProxy(
            dt,
            (
                "date",
                "datetime",
                "time",
                "timedelta",
                "timezone",
                "tzinfo",
                "UTC",
                "MINYEAR",
                "MAXYEAR",
            ),
        ),
        "decimal": ModuleProxy(
            decimal,
            (
                "Decimal",
                "InvalidOperation",
                *(name for name in dir(decimal) if name.startswith("ROUND_")),
            ),
        ),
        "math": ModuleProxy(
            math,
            tuple(
                name
                for name in dir(math)
                if not name.startswith("_") and name not in {"factorial", "comb", "perm"}
            ),
        ),
        "re": ModuleProxy(
            re,
            (
                "compile",
                "escape",
                "findall",
                "fullmatch",
                "match",
                "search",
                "split",
                "sub",
                "subn",
                "A",
                "ASCII",
                "I",
                "IGNORECASE",
                "M",
                "MULTILINE",
                "S",
                "DOTALL",
                "X",
                "VERBOSE",
            ),
        ),
        "json": ModuleProxy(json, ("dumps", "loads")),
    }
)
"""The modules expressions may use, by name. ``math.factorial`` and friends are left out
because a small argument makes a huge number."""

_EXTRA_RECEIVERS: list[type] = []


def allow_receiver(cls: type) -> None:
    """Allow attribute access on instances of ``cls`` (e.g. a Faker generator)."""
    if cls not in _EXTRA_RECEIVERS:
        _EXTRA_RECEIVERS.append(cls)


def _allowed_receiver(obj: object) -> bool:
    if isinstance(obj, type):
        return issubclass(obj, ALLOWED_TYPES)
    return isinstance(obj, (*ALLOWED_TYPES, *_EXTRA_RECEIVERS))


def get_attribute(obj: object, name: str) -> object:
    """``obj.name``, when the sandbox allows it.

    Raises:
        SandboxError: for a private, denied or mutating attribute, or a receiver outside the
            allowed types.
    """
    if isinstance(obj, ModuleProxy):
        return obj.attribute(name)
    if name.startswith("_") or name in _DENIED:
        msg = f"attribute {name!r} is not available in expressions"
        raise SandboxError(msg)
    if not _allowed_receiver(obj):
        msg = f"attributes of {type(obj).__name__} values are not available in expressions"
        raise SandboxError(msg)
    if name in _MUTATORS and isinstance(obj, _MUTABLE):
        msg = f"{type(obj).__name__}.{name} would change a shared value; build a new one instead"
        raise SandboxError(msg)
    value = getattr(obj, name)
    if name in _PADDING and isinstance(obj, (str, bytes)):
        return _guard_padding(value)
    return value


def _guard_padding(method: Callable[..., Any]) -> Callable[..., Any]:
    def padded(width: Any = 8, *args: object) -> object:  # noqa: ANN401 -- as given
        if isinstance(width, int) and width > MAX_LENGTH:
            msg = f"a width over {MAX_LENGTH} is not allowed"
            raise SandboxError(msg)
        return method(width, *args)

    return padded


def check_format_spec(spec: str) -> str:
    """Refuse format widths and precisions over :data:`MAX_LENGTH`.

    Raises:
        SandboxError: for a format spec that would build a huge string.
    """
    if any(int(n) > MAX_LENGTH for n in re.findall(r"\d+", spec)):
        msg = f"a format width over {MAX_LENGTH} is not allowed"
        raise SandboxError(msg)
    return spec


def _sized(value: object) -> int | None:
    return len(value) if isinstance(value, (str, bytes, list, tuple)) else None


def multiply(left: Any, right: Any) -> Any:  # noqa: ANN401 -- any operands
    """``left * right``, refusing repetition beyond :data:`MAX_LENGTH`.

    Raises:
        SandboxError: when the result would be too long.
    """
    for seq, count in ((left, right), (right, left)):
        size = _sized(seq)
        if size is not None and isinstance(count, int) and size * count > MAX_LENGTH:
            msg = f"a result longer than {MAX_LENGTH} is not allowed"
            raise SandboxError(msg)
    return left * right


def power(left: Any, right: Any) -> Any:  # noqa: ANN401 -- any operands
    """``left ** right``, refusing integer exponents beyond :data:`MAX_EXPONENT`.

    Raises:
        SandboxError: for a huge integer exponent.
    """
    if isinstance(right, int) and abs(right) > MAX_EXPONENT and not isinstance(left, float):
        msg = f"an exponent over {MAX_EXPONENT} is not allowed"
        raise SandboxError(msg)
    return left**right


def left_shift(left: Any, right: Any) -> Any:  # noqa: ANN401 -- any operands
    """``left << right``, refusing shifts beyond :data:`MAX_EXPONENT`.

    Raises:
        SandboxError: for a huge shift.
    """
    if isinstance(right, int) and right > MAX_EXPONENT:
        msg = f"a shift over {MAX_EXPONENT} is not allowed"
        raise SandboxError(msg)
    return left << right


def bounded(items: Iterable[Any]) -> Iterator[Any]:
    """Iterate, refusing more than :data:`MAX_ITEMS` items.

    Raises:
        SandboxError: past the limit.
    """
    for count, item in enumerate(items):
        if count >= MAX_ITEMS:
            msg = f"more than {MAX_ITEMS} items in one comprehension is not allowed"
            raise SandboxError(msg)
        yield item


def safe_range(*args: int) -> range:
    """``range``, refusing more than :data:`MAX_ITEMS` items.

    Raises:
        SandboxError: for a longer range.
    """
    result = range(*args)
    if len(result) > MAX_ITEMS:
        msg = f"a range of more than {MAX_ITEMS} items is not allowed"
        raise SandboxError(msg)
    return result
