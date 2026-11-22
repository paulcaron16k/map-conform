"""The shipped spec reference and the README's examples stay true (WBS 10.1)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from map_conform.settings import parse_settings
from map_conform.spec.model import parse_spec
from map_conform.spec.reference import SHIPPED, render

README = Path(__file__).resolve().parents[2] / "README.md"


def test_reference_is_current() -> None:
    """docs/spec-reference.md is what the generator writes now."""
    assert SHIPPED.read_text(encoding="utf-8") == render(), (
        "run `uv run python -m map_conform.spec.reference`"
    )


def test_reference_covers_every_key() -> None:
    """A sample of keys from each section is listed."""
    text = render()
    for key in ("`spec_path`", "`batch_output.mode`", "`naming.preset`", "`filter`",
                "`shape`", "`fields`", "`regex_replace`", "`coalesce(*values)`"):  # fmt: skip
        assert key in text, key


def test_readme_examples_are_valid() -> None:
    """The README's spec parses, and its Meltano mapping config is valid settings."""
    blocks = re.findall(r"```yaml\n(.*?)```", README.read_text(encoding="utf-8"), re.DOTALL)
    meltano, spec = (yaml.safe_load(b) for b in blocks)
    parse_spec(spec)
    mapping = meltano["plugins"]["mappers"][0]["mappings"][0]["config"]
    parse_settings(mapping)
