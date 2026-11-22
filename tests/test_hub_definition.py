"""The Meltano Hub definition is current with meltano.yml and the mapper (WBS 10.4)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

from map_conform.mapper import MapConformMapper

ROOT = Path(__file__).resolve().parent.parent


def _renderer():  # noqa: ANN202 -- a module
    spec = importlib.util.spec_from_file_location(
        "render_hub", ROOT / "bin" / "render-hub-definition.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_definition_is_current() -> None:
    """plugin-definition.yml is what bin/render-hub-definition.py writes now."""
    assert (ROOT / "plugin-definition.yml").read_text(encoding="utf-8") == _renderer().render(), (
        "run `uv run bin/render-hub-definition.py`"
    )


def test_definition_matches_the_mapper() -> None:
    """Capabilities are the mapper's own; settings are meltano.yml's."""
    definition = yaml.safe_load((ROOT / "plugin-definition.yml").read_text(encoding="utf-8"))
    assert definition["capabilities"] == [str(c) for c in MapConformMapper.capabilities]
    project = yaml.safe_load((ROOT / "meltano.yml").read_text(encoding="utf-8"))
    mapper = next(m for m in project["plugins"]["mappers"] if m["name"] == "map-conform")
    assert definition["settings"] == mapper["settings"]
    assert definition["pip_url"] == "map-conform"
