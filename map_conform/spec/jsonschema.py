"""The conform spec's JSON Schema, generated from the model (detailed design §3.1).

The shipped copy is ``map_conform/map-conform-spec.schema.json``; a test fails when it is
stale. Regenerate it with::

    uv run python -m map_conform.spec.jsonschema

Editors can use the schema for completion and validation. It cannot express everything the
loader checks (CType grammar, the first-key step rule, cross-references), so
``map-conform spec validate`` remains the authority.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from map_conform.spec._struct import schema
from map_conform.spec.model import Spec

SCHEMA_ID = (
    "https://raw.githubusercontent.com/paulcaron16k/map-conform/main/"
    "map_conform/map-conform-spec.schema.json"
)
SHIPPED = Path(__file__).resolve().parent.parent / "map-conform-spec.schema.json"


def spec_json_schema() -> dict[str, Any]:
    """The JSON Schema (draft 2020-12) of a version 1 conform spec."""
    defs: dict[str, Any] = {}
    root = schema(Spec, defs)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        "title": "map-conform spec (version 1)",
        **root,
        "$defs": dict(sorted(defs.items())),
    }


def render() -> str:
    """The schema as the shipped file's text."""
    return json.dumps(spec_json_schema(), indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    """Write the shipped schema file."""
    SHIPPED.write_text(render(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
