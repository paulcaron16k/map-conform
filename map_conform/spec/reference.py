"""The spec reference (``docs/spec-reference.md``), generated from the model (WBS 10.1).

Every key, type, default and description comes from the same frozen dataclasses the strict
parser and the JSON Schema use, and the builtin and function tables from the registries, so
the reference cannot drift from the code. A test fails when the shipped copy is stale.
Regenerate it with::

    uv run python -m map_conform.spec.reference
"""

from __future__ import annotations

import dataclasses
import json
import typing
from collections.abc import Mapping
from pathlib import Path
from types import NoneType, UnionType
from typing import Any, Literal, get_args, get_origin

from map_conform.expr.functions import FUNCTIONS
from map_conform.settings import Settings
from map_conform.spec._struct import dump, fields_of, spec_key
from map_conform.spec.model import ColumnSpec, Defaults, ExprRef, FieldSpec, Spec, StreamSpec
from map_conform.spec.steps import Chain, Macro
from map_conform.transforms.builtins import builtin_registry
from map_conform.types.canonical import Kind

SHIPPED = Path(__file__).resolve().parents[2] / "docs" / "spec-reference.md"
_GROUPS = ("predicates", "coercion", "temporal", "text", "numeric", "misc", "python", "modules")


def _type(tp: Any) -> str:  # noqa: ANN401, PLR0911 -- one branch per annotation form
    """An annotation in words."""
    origin = get_origin(tp)
    if tp is Any:
        return "any"
    if tp is NoneType:
        return "null"
    if origin is Literal:
        return " \\| ".join(f"`{a}`" for a in get_args(tp))
    if origin in (UnionType, typing.Union):
        return " or ".join(_type(a) for a in get_args(tp))
    if origin is tuple:
        return f"list of {_type(get_args(tp)[0])}"
    if origin in (Mapping, dict):
        return f"mapping of {_type(get_args(tp)[1])}"
    names = {bool: "boolean", int: "integer", float: "number", str: "string",
             Chain: "chain", Macro: "macro", ExprRef: "`{expr: ...}`"}  # fmt: skip
    if tp in names:
        return names[tp]
    if dataclasses.is_dataclass(tp):
        return "object"
    return str(tp)


def _default(field: dataclasses.Field[Any]) -> str:
    if field.default is not dataclasses.MISSING:
        value: object = field.default
    elif field.default_factory is not dataclasses.MISSING:
        value = field.default_factory()
    else:
        return "required"
    if value is None:
        return "unset"
    if dataclasses.is_dataclass(value):
        return "the section below"
    return f"`{json.dumps(dump(value, full=True), ensure_ascii=False)}`"


def _rows(cls: type[Any], prefix: str = "", *, expand: bool = True) -> list[str]:
    """Table rows for a dataclass's fields; nested objects become dotted keys when expanded."""
    rows: list[str] = []
    for field, tp in fields_of(cls):
        key = f"{prefix}{spec_key(field)}"
        doc = " ".join(str(field.metadata.get("doc", "")).split()).replace("|", "\\|")
        if expand and dataclasses.is_dataclass(tp) and isinstance(tp, type):
            rows.extend(_rows(tp, f"{key}."))
            continue
        rows.append(f"| `{key}` | {_type(tp)} | {_default(field)} | {doc} |")
    return rows


def _table(cls: type[Any], *, expand: bool = True) -> list[str]:
    rows = _rows(cls, expand=expand)
    return ["| Key | Type | Default | Meaning |", "| -- | -- | -- | -- |", *rows]


def _steps() -> list[str]:
    lines = ["| Step | Options | Meaning |", "| -- | -- | -- |"]
    registry = builtin_registry()
    for name, transform in sorted(registry.names().items()):
        options = ", ".join(f"`{f.name}`" for f in dataclasses.fields(transform.kwargs)) or "none"
        lines.append(f"| `{name}` | {options} | {transform.doc} |")
    kinds = ", ".join(f"`{k}`" for k in sorted(registry.casts))
    lines.append(f"| `cast` | per target type | Casts to any of {kinds}. |")
    return lines


def _functions() -> list[str]:
    lines = ["| Function | Group | Meaning |", "| -- | -- | -- |"]
    ordered = sorted(FUNCTIONS.values(), key=lambda f: (_GROUPS.index(f.group), f.name))
    lines.extend(f"| `{f.signature}` | {f.group} | {f.doc} |" for f in ordered)
    return lines


def render() -> str:
    """The reference's text."""
    kinds = ", ".join(f"`{k}`" for k in get_args(Kind))
    parts = [
        "# map-conform spec reference",
        "",
        "Generated from the code by `uv run python -m map_conform.spec.reference`; do not edit.",
        "The [detailed design](detailed-design.md) explains the behaviour behind each key, and",
        "the [cookbook](cookbook.md) shows them at work.",
        "",
        "## Plugin settings",
        "",
        "Set in `meltano.yml` (or `--config`). Nested keys are written with dots in Meltano.",
        "",
        *_table(Settings),
        "",
        "## Spec file: top level",
        "",
        *_table(Spec, expand=False),
        "",
        "## `defaults`",
        "",
        "Inherited by every stream; a stream rule may set any of these keys to override them.",
        "",
        *_table(Defaults),
        "",
        "## `streams.<glob>`",
        "",
        "Plus any `defaults` key. A key is a glob over tap stream names, or a new output stream's",
        "name when the rule has `source`.",
        "",
        *_table(StreamSpec),
        "",
        "## `columns.<name>`",
        "",
        *_table(ColumnSpec),
        "",
        "## `fields.<path>`",
        "",
        "For `struct` and `json` columns; paths are member names joined by `.`, with `[*]` for",
        "list items.",
        "",
        *_table(FieldSpec),
        "",
        "## Types",
        "",
        f"Kinds: {kinds}. Parameterised: `decimal(p,s)`, `string(n)`, `list<T>`,",
        "`struct<name: T, ...>`. SQL aliases are read too (`bigint`, `varchar(n)`, `long`, ...).",
        "",
        "## Builtin steps",
        "",
        *_steps(),
        "",
        "## Expression functions",
        "",
        "Builtin steps, `cast(value, type, ...)`, macros and UDFs are callable in expressions",
        "too. Names in scope: `value`/`self`, columns by conformed name, `record`/`_`,",
        "`source(name)`, `config`, `stream`, `source_stream`, `row_number`, `NULL`, `fake`.",
        "",
        *_functions(),
        "",
    ]
    return "\n".join(parts)


def main() -> int:
    """Write the shipped reference."""
    SHIPPED.write_text(render(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
