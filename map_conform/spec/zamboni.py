"""The bridge to Zamboni table-config ``columns`` (ADR-0003, WBS 9.2).

Zamboni's table-config (version 2) describes physical layout per table; its ``columns``
block maps a column name to a type string, which Zamboni itself only checks for shape. The
bridge fills it with map-conform's canonical types and reads it back:

- ``spec export SPEC --zamboni TC --catalog C`` compiles each catalog stream's plans and
  writes ``namespaces.<ns>.tables.<output stream>.columns`` as ``{output column: CType}``,
  ``_sdc_*`` columns included when they are added. Everything else in the file is kept as
  it was; a missing table entry is created with just its columns.
- ``spec import --catalog C --zamboni TC`` drafts a spec whose column types come from the
  Zamboni table (matched by output stream and column names), falling back to the catalog.
  ``defaults.columns`` applies to every table, under its own.

Tables are matched by the conformed output stream name. With one namespace in the file it
is used; with several, ``--namespace`` says which.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from map_conform.spec._struct import Issue
from map_conform.spec.errors import SpecError

SUPPORTED_VERSION = 2


def _problem(path: str | Path, message: str) -> SpecError:
    return SpecError([Issue("", message)], str(path))


def read_table_config(path: str | Path) -> dict[str, Any]:
    """Read a Zamboni table-config file (JSON or YAML), version 2.

    Raises:
        SpecError: if the file cannot be read or is not a version 2 table-config.
    """
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as exc:
        raise _problem(path, f"cannot read the table-config: {exc.strerror}") from exc
    try:
        document = json.loads(text) if file.suffix.lower() == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise _problem(path, f"not a table-config: {exc}") from exc
    if not isinstance(document, dict):
        raise _problem(path, "a table-config is a mapping")
    if document.get("version") != SUPPORTED_VERSION:
        raise _problem(path, f"only Zamboni table-config version 2 is supported, got "
                             f"{document.get('version')!r}")  # fmt: skip
    return document


def write_table_config(document: dict[str, Any], path: str | Path) -> None:
    """Write the table-config back in the file's own format."""
    file = Path(path)
    if file.suffix.lower() == ".json":
        text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    else:
        text = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    file.write_text(text, encoding="utf-8")


def namespace_of(document: dict[str, Any], namespace: str | None, path: str | Path) -> str:
    """The namespace to use: the one given, or the file's only one.

    Raises:
        SpecError: when the namespace is ambiguous.
    """
    names = list((document.get("namespaces") or {}).keys())
    if namespace is not None:
        return namespace
    if len(names) == 1:
        return names[0]
    choices = ", ".join(names) or "none"
    raise _problem(path, f"choose a namespace with --namespace (the file has: {choices})")


def table_columns(document: dict[str, Any], namespace: str, table: str) -> dict[str, str]:
    """A table's ``columns``, over ``defaults.columns``."""
    columns = dict((document.get("defaults") or {}).get("columns") or {})
    tables = ((document.get("namespaces") or {}).get(namespace) or {}).get("tables") or {}
    columns.update((tables.get(table) or {}).get("columns") or {})
    return columns


def set_table_columns(
    document: dict[str, Any], namespace: str, table: str, columns: dict[str, str]
) -> None:
    """Replace a table's ``columns``, creating the namespace and table entries if needed."""
    namespaces = document.setdefault("namespaces", {})
    tables = namespaces.setdefault(namespace, {}).setdefault("tables", {})
    tables.setdefault(table, {})["columns"] = columns
