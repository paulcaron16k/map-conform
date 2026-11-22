"""Output stream names (detailed design §3.2, ``stream`` defaults).

For a resolved stream the name is, in order:

1. ``alias`` if set: the final name, checked but never silently conformed;
2. otherwise the base name: the ``streams`` key for a ``source`` stream, else the tap
   stream name, cut to the part after the last ``stream.split`` separator if one is set;
3. conformed like a column name (``stream.name: conform``) or kept (``preserve``);
4. with the stream's ``prefix`` (or ``stream.prefix``) added after conforming, and the result
   conformed again so a long name still fits ``max_length``.

Example: ``sheets-Orders 2024`` with ``prefix: raw_`` becomes ``raw_sheets_orders_2024``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from map_conform.naming.conform import Conformed, NameConformer, NamingError
from map_conform.spec.model import ExprRef

if TYPE_CHECKING:
    from map_conform.spec.load import ResolvedStream


def stream_name(resolved: ResolvedStream) -> Conformed:
    """The output name of a resolved stream.

    Raises:
        NamingError: when an alias is not a legal name, or the policy says to fail.
    """
    settings = resolved.settings
    conformer = NameConformer(settings.naming)
    conform = settings.stream.name == "conform"
    alias = resolved.spec.alias
    if isinstance(alias, ExprRef):
        raise NamingError(
            resolved.tap_stream,
            "an expression alias needs the expression language, which is not built yet "
            "(WBS 6.x); use a literal alias",
        )
    if alias is not None:
        if conform and (fixed := conformer.conform(alias).name) != alias:
            raise NamingError(
                resolved.tap_stream,
                f"alias {alias!r} is not a legal name here; it would conform to {fixed!r}",
            )
        return Conformed(resolved.tap_stream, alias)

    base = resolved.key or resolved.tap_stream
    split = settings.stream.split
    if split and split in base:
        base = base.rsplit(split, 1)[1]
    prefix = resolved.spec.prefix if resolved.spec.prefix is not None else settings.stream.prefix
    if not conform:
        return Conformed(resolved.tap_stream, prefix + base)
    named = conformer.conform(base)
    if not prefix:
        return Conformed(resolved.tap_stream, named.name, named.notes)
    prefixed = conformer.conform(prefix + named.name)
    return Conformed(resolved.tap_stream, prefixed.name, named.notes + prefixed.notes)
