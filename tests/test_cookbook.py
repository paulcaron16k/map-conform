"""Every cookbook example runs and gives the documented output (WBS 10.1 acceptance)."""

from __future__ import annotations

import contextlib
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from map_conform.mapper import MapConformMapper

COOKBOOK = Path(__file__).resolve().parent.parent / "docs" / "cookbook.md"
_BLOCK = re.compile(r"^```(?:yaml|json) cookbook:(\w+)\n(.*?)^```", re.MULTILINE | re.DOTALL)


@dataclass
class Recipe:
    """One cookbook section."""

    title: str
    blocks: dict[str, str] = field(default_factory=dict)


def recipes() -> list[Recipe]:
    """The cookbook's recipes, in order."""
    out: list[Recipe] = []
    for section in re.split(r"^## ", COOKBOOK.read_text(encoding="utf-8"), flags=re.MULTILINE)[1:]:
        title = section.splitlines()[0]
        blocks = {m.group(1): m.group(2) for m in _BLOCK.finditer(section)}
        if blocks:
            out.append(Recipe(title, blocks))
    return out


def run(recipe: Recipe) -> list[dict[str, Any]]:
    """The records the mapper writes for a recipe."""
    spec = yaml.safe_load(recipe.blocks["spec"])
    records = json.loads(recipe.blocks["input"])
    settings = json.loads(recipe.blocks.get("settings", "{}"))
    keys = list(dict.fromkeys(k for r in records for k in r))
    properties = (
        json.loads(recipe.blocks["schema"])
        if "schema" in recipe.blocks
        else {k: {"type": ["string", "null"]} for k in keys}
    )
    stream = next(iter(spec.get("streams") or {}), None) or next(
        iter(settings.get("stream_maps") or {}), "s"
    )
    messages: list[dict[str, Any]] = [{"type": "SCHEMA", "stream": stream, "key_properties": [],
                 "schema": {"type": "object", "properties": properties}}]  # fmt: skip
    messages += [{"type": "RECORD", "stream": stream, "record": r} for r in records]
    mapper = MapConformMapper(config={"spec": spec, **settings})
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        mapper.listen(io.StringIO("".join(json.dumps(m) + "\n" for m in messages)))
    return [json.loads(line)["record"] for line in out.getvalue().splitlines()
            if json.loads(line)["type"] == "RECORD"]  # fmt: skip


@pytest.mark.parametrize("recipe", recipes(), ids=lambda r: r.title)
def test_recipe(recipe: Recipe) -> None:
    """The mapper writes exactly the documented records."""
    assert run(recipe) == json.loads(recipe.blocks["output"])


def test_every_recipe_has_a_spec_input_and_output() -> None:
    """No recipe is left untested."""
    found = recipes()
    assert len(found) >= 7  # noqa: PLR2004
    for recipe in found:
        assert {"spec", "input", "output"} <= set(recipe.blocks), recipe.title
