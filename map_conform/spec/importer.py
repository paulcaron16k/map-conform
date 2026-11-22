"""``map-conform spec import --stream-maps``: SDK settings to a native spec (WBS 12.8).

The SDK settings are translated as the mapper translates them at start-up
(:mod:`map_conform.spec.stream_maps`), and the result is written as a spec file, compatibility
defaults included, so a project can drop ``stream_maps`` and keep its output.

Types the SDK would infer are written out explicitly. A type decided by the expression's
prefix (``int(...)``) needs nothing more; one taken from a tap property needs the catalog
(``--catalog``). Without it, or when a glob matches streams that disagree, the column keeps
``infer_type: sdk`` and a note says so.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import TYPE_CHECKING, Any

from map_conform.spec._struct import Issues
from map_conform.spec.errors import SpecError
from map_conform.spec.stream_maps import SDK_SETTINGS, prefix_type, sdk_type, translate
from map_conform.types.from_jsonschema import from_jsonschema

if TYPE_CHECKING:
    from collections.abc import Mapping

    from map_conform.spec.check import CatalogStream


def import_stream_maps(
    config: Mapping[str, Any], catalog: list[CatalogStream] | None
) -> tuple[dict[str, Any], list[str]]:
    """The native spec for the SDK settings in ``config``, and notes for the user.

    Raises:
        SpecError: when the settings cannot be translated.
    """
    issues = Issues()
    spec = translate({k: config.get(k) for k in SDK_SETTINGS}, issues)
    if issues:
        raise SpecError(issues.items, "the stream_maps settings")
    if spec is None:
        raise SpecError([], "the settings: there are no stream_maps or flattening settings")
    notes: list[str] = []
    nested = spec.get("defaults", {}).get("nested", "keep")
    for key, rules in spec.get("streams", {}).items():
        for name, column in rules.get("columns", {}).items():
            if column.get("infer_type") != "sdk":
                continue
            resolved = _explicit_type(
                key, rules, name, column["expr"], catalog=catalog, nested=nested
            )
            if resolved is None:
                where = "no --catalog" if catalog is None else "the streams it matches disagree"
                notes.append(
                    f"streams.{key}.columns.{name}: kept infer_type: sdk ({where}); "
                    "declare its type"
                )
                continue
            del column["infer_type"]
            column["type"] = resolved
    if config.get("stream_map_config"):
        notes.append("stream_map_config is config in expressions: move it to the spec_vars setting")
    return spec, notes


def _explicit_type(  # noqa: PLR0913 -- the column and where it applies
    key: str,
    rules: Mapping[str, Any],
    name: str,
    expr: str,
    *,
    catalog: list[CatalogStream] | None,
    nested: str,
) -> str | None:
    """The column's type as text, when every matching catalog stream gives the same one."""
    if catalog is None:  # only what the expression decides by itself
        decided = prefix_type(expr) if expr.strip() != "record" else None
        return None if decided is None else str(decided)
    dropped = rules.get("undeclared") == "drop"
    source = rules.get("source", key)
    found: set[str] = set()
    for stream in (s for s in catalog if fnmatchcase(s.name, source)):
        ctype, schema = sdk_type(expr, name, stream.properties, undeclared_dropped=dropped)
        if ctype is None and schema is not None:
            ctype = from_jsonschema(schema, "json" if nested == "json" else "keep").ctype
        found.add(str(ctype))
    return found.pop() if len(found) == 1 else None
