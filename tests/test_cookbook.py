"""Every cookbook example runs and gives the documented output (WBS 10.1 acceptance)."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from map_conform.mapper import MapConformMapper

COOKBOOK = Path(__file__).resolve().parent.parent / "docs" / "cookbook.md"
_BLOCK = re.compile(r"^```(?:yaml|json|text) cookbook:(\w+)\n(.*?)^```", re.MULTILINE | re.DOTALL)


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


def _wire(value: object) -> object:
    """A value read back from parquet, as the RECORD path writes it."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dt.datetime):
        return value.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, (dt.date, uuid.UUID)):
        return str(value)
    return value


@dataclass
class Result:
    """What the mapper did with a recipe."""

    records: list[dict[str, Any]]
    rejects: list[dict[str, Any]]


def run(recipe: Recipe, folder: Path) -> Result:
    """Run a recipe's messages through the mapper, with rejects and BATCH files in folder."""
    spec = yaml.safe_load(recipe.blocks["spec"])
    batch = "parquet" in recipe.blocks
    records = json.loads(recipe.blocks["parquet" if batch else "input"])
    settings = json.loads(recipe.blocks.get("settings", "{}"))
    settings.setdefault("reject", {"storage": str(folder / "rejects")})
    if batch:
        output = settings.setdefault("batch_output", {})
        output.setdefault("storage", {"root": f"file://{folder}/out"})
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
    if batch:
        source = folder / "in.parquet"
        pq.write_table(pa.Table.from_pylist(records), source)
        messages.append({"type": "BATCH", "stream": stream, "encoding": {"format": "parquet"},
                         "manifest": [f"file://{source}"]})  # fmt: skip
    else:
        messages += [{"type": "RECORD", "stream": stream, "record": r} for r in records]
    mapper = MapConformMapper(config={"spec": spec, **settings})
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        mapper.listen(io.StringIO("".join(json.dumps(m) + "\n" for m in messages)))
    written = [json.loads(line) for line in out.getvalue().splitlines()]
    rows = [m["record"] for m in written if m["type"] == "RECORD"]
    for message in written:
        if message["type"] == "BATCH":
            for uri in message["manifest"]:
                table = pq.read_table(uri.removeprefix("file://"))
                rows += [{k: _wire(v) for k, v in r.items()} for r in table.to_pylist()]
    rejects = [json.loads(line) for file in sorted((folder / "rejects").rglob("*.jsonl"))
               for line in file.read_text(encoding="utf-8").splitlines()]  # fmt: skip
    return Result(rows, rejects)


@pytest.mark.parametrize("recipe", recipes(), ids=lambda r: r.title)
def test_recipe(recipe: Recipe, tmp_path: Path) -> None:
    """The mapper writes exactly the documented records, rejects or error."""
    if "error" in recipe.blocks:
        with pytest.raises(Exception) as caught:  # noqa: PT011 -- the text is the check
            run(recipe, tmp_path)
        assert recipe.blocks["error"].strip() in str(caught.value)
        return
    result = run(recipe, tmp_path)
    assert result.records == json.loads(recipe.blocks["output"])
    if "rejects" in recipe.blocks:
        expected = json.loads(recipe.blocks["rejects"])
        shown = [{k: r[k] for k in e} for r, e in zip(result.rejects, expected, strict=True)]
        assert shown == expected


def test_every_recipe_has_a_spec_input_and_output() -> None:
    """No recipe is left untested."""
    found = recipes()
    assert len(found) >= 7  # noqa: PLR2004
    for recipe in found:
        blocks = set(recipe.blocks)
        assert "spec" in blocks, recipe.title
        assert blocks & {"input", "parquet"}, recipe.title
        assert blocks & {"output", "error"}, recipe.title
