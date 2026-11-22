"""The shipped JSON Schema is current, valid, and agrees with the parser."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

import jsonschema
import pytest
from click.testing import CliRunner

from map_conform.cli import tools
from map_conform.spec.jsonschema import SHIPPED, render, spec_json_schema
from tests.spec.test_load import LAYERED
from tests.spec.test_model import FULL


def validator() -> jsonschema.Draft202012Validator:
    """A validator for the generated schema."""
    return jsonschema.Draft202012Validator(spec_json_schema())


def test_shipped_schema_is_current() -> None:
    """The committed schema equals a fresh render."""
    assert SHIPPED.read_text(encoding="utf-8") == render(), (
        "run `uv run python -m map_conform.spec.jsonschema`"
    )


def test_schema_is_valid_2020_12() -> None:
    """The generated document is itself a valid draft 2020-12 schema."""
    jsonschema.Draft202012Validator.check_schema(spec_json_schema())


def test_schema_ships_inside_the_package() -> None:
    """Installed users can load the schema as package data."""
    shipped = files("map_conform") / "map-conform-spec.schema.json"
    assert json.loads(shipped.read_text(encoding="utf-8"))["title"].startswith("map-conform spec")


@pytest.mark.parametrize("spec", [FULL, LAYERED, {"version": 1}], ids=["full", "layered", "min"])
def test_schema_accepts_specs_the_parser_accepts(spec: dict[str, Any]) -> None:
    """Every valid example spec validates against the schema."""
    validator().validate(spec)


@pytest.mark.parametrize(
    ("spec", "where"),
    [
        ({"version": 2}, ["version"]),
        ({"version": 1, "bogus": 1}, []),
        ({"version": 1, "defaults": {"naming": {"case": "camel"}}}, ["defaults", "naming", "case"]),
        ({"version": 1, "streams": {"s": {"what": 1}}}, ["streams", "s"]),
        ({"version": 1, "streams": {"s": {"columns": {"c": {"nullable": "no"}}}}},
         ["streams", "s", "columns", "c", "nullable"]),
        ({"version": 1, "streams": {"s": {"naming": {"max_length": "x"}}}},
         ["streams", "s", "naming", "max_length"]),
    ],
)  # fmt: skip
def test_schema_rejects_what_the_parser_rejects(spec: dict[str, Any], where: list[str]) -> None:
    """Unknown keys, bad enums and wrong types fail schema validation at the same place."""
    errors = list(validator().iter_errors(spec))
    assert errors
    # An anyOf (naming: {...} | "sdk") reports the deeper error in its context.
    found = [e for error in errors for e in (error, *error.context)]
    assert any(list(e.absolute_path) == where for e in found), [e.absolute_path for e in found]


def test_stream_rules_do_not_claim_defaults() -> None:
    """Defaults keys inside a stream are inherited, so the schema gives them no default."""
    rules = spec_json_schema()["$defs"]["StreamRules"]["properties"]
    assert "default" not in rules["on_error"]
    assert spec_json_schema()["$defs"]["Defaults"]["properties"]["on_error"]["default"] == "raise"


def test_cli_prints_the_schema() -> None:
    """`map-conform spec schema` prints the shipped document."""
    result = CliRunner().invoke(tools, ["spec", "schema"])
    assert result.exit_code == 0, result.output
    assert result.output == SHIPPED.read_text(encoding="utf-8")
