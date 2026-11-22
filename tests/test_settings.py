"""Plugin settings: parsing, the generated config schema, spec loading at start-up."""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml
from singer_sdk.exceptions import ConfigValidationError

from map_conform.mapper import MapConformMapper
from map_conform.settings import Settings, parse_settings, settings_jsonschema
from map_conform.spec._struct import fields_of
from map_conform.spec.errors import SpecError
from map_conform.spec.model import DEFAULTS_KEYS, STREAM_KEYS

ROOT = Path(__file__).resolve().parents[1]

STREAM_RULE_KEYS = ", ".join(sorted(STREAM_KEYS | DEFAULTS_KEYS))


def test_defaults_match_the_design() -> None:
    """Empty config gives the documented defaults (detailed design §1)."""
    settings = parse_settings({})
    assert settings.spec_path is None
    assert settings.strict is False
    assert settings.batch_output.mode == "batch"
    assert settings.batch_output.format == "parquet"
    assert settings.batch_output.compression is None  # per format
    assert settings.batch_output.row_group_size == 131072  # noqa: PLR2004
    assert settings.reject.storage == "./.map-conform/rejects"


def test_nested_settings_parse() -> None:
    """Nested objects parse into their dataclasses."""
    settings = parse_settings({
        "spec_path": "conform.yml",
        "spec_vars": {"prefix": "raw_"},
        "batch_output": {
            "format": "jsonl",
            "storage": {"root": "s3://b/out", "params": {"anon": True}},
        },
        "reject": {"format": "parquet"},
    })  # fmt: skip
    assert settings.spec_vars == {"prefix": "raw_"}
    assert settings.batch_output.storage.root == "s3://b/out"
    assert settings.batch_output.storage.params == {"anon": True}
    assert settings.reject.format == "parquet"


def test_invalid_settings_list_every_problem() -> None:
    """Bad settings are reported with their paths."""
    with pytest.raises(SpecError) as caught:
        parse_settings({"strict": "yes", "batch_output": {"row_group_size": 0, "mode": "x"}})
    assert [str(i) for i in caught.value.issues] == [
        "strict: expected a boolean, got a string",
        "batch_output.mode: expected one of 'batch', 'record', got 'x'",
        "batch_output.row_group_size: must be at least 1",
    ]


def test_config_schema_is_inline_and_valid() -> None:
    """The SDK gets a self-contained schema whose properties all carry a type."""
    config_schema = settings_jsonschema()
    assert "$ref" not in json.dumps(config_schema)
    jsonschema.Draft202012Validator.check_schema(config_schema)
    assert all("type" in prop for prop in config_schema["properties"].values())
    assert MapConformMapper.config_jsonschema == config_schema


def test_mapper_loads_the_spec_file(tmp_path: Path) -> None:
    """spec_path, the inline spec and spec_vars combine at start-up."""
    spec = tmp_path / "conform.yml"
    spec.write_text("version: 1\ndefaults: {stream: {prefix: '${p}'}, on_error: null}\n")
    mapper = MapConformMapper(config={
        "spec_path": str(spec),
        "spec": {"defaults": {"on_error": "reject"}},
        "spec_vars": {"p": "raw_"},
    })  # fmt: skip
    assert mapper.spec.defaults.stream.prefix == "raw_"
    assert mapper.spec.defaults.on_error == "reject"


def test_mapper_without_a_spec_uses_the_defaults() -> None:
    """No spec_path and no spec: conform with the default rules."""
    assert MapConformMapper(config={}).spec.defaults.on_error == "raise"


def test_mapper_rejects_a_bad_spec_with_every_problem(tmp_path: Path) -> None:
    """A bad spec fails at start-up as a config validation error listing each problem."""
    spec = tmp_path / "conform.yml"
    spec.write_text("version: 1\nstreams:\n  s: {columns: {a: {type: decimel}}, bogus: 1}\n")
    with pytest.raises(ConfigValidationError) as caught:
        MapConformMapper(config={"spec_path": str(spec)})
    assert caught.value.errors == [
        f"streams.s.bogus: unknown key; allowed here: {STREAM_RULE_KEYS}",
        "streams.s.columns.a.type: unknown type 'decimel' at position 7 in 'decimel'",
    ]
    assert str(caught.value) == f"Invalid {spec}"


def test_unknown_setting_is_rejected_by_the_sdk() -> None:
    """The SDK validates config against the generated schema."""
    with pytest.raises(ConfigValidationError):
        MapConformMapper(config={"spec_pth": "typo.yml"})


def test_cli_exits_non_zero_and_names_the_problem(tmp_path: Path) -> None:
    """Run as Meltano runs it, a bad spec stops the mapper with the problem in the log."""
    spec = tmp_path / "conform.yml"
    spec.write_text("version: 2\n")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"spec_path": str(spec)}))
    result = subprocess.run(  # noqa: S603 -- fixed argv: the installed console script
        [str(Path(sys.executable).with_name("map-conform")), "--config", str(config)],
        input="",
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 1
    assert "version: expected one of 1, got 2" in result.stderr


def _leaf_settings(cls: type[Any], prefix: str = "") -> set[str]:
    names: set[str] = set()
    for field, tp in fields_of(cls):
        if isinstance(tp, type) and dataclasses.is_dataclass(tp):
            names |= _leaf_settings(tp, f"{prefix}{field.name}.")
        else:
            names.add(prefix + field.name)
    return names


def test_meltano_yml_declares_exactly_the_settings() -> None:
    """meltano.yml's settings are the Settings leaves, so neither can drift."""
    project = yaml.safe_load((ROOT / "meltano.yml").read_text())
    (mapper,) = project["plugins"]["mappers"]
    assert {s["name"] for s in mapper["settings"]} == _leaf_settings(Settings)


def test_example_project_spec_loads() -> None:
    """The conform.yml that meltano.yml points at is a valid spec."""
    project = yaml.safe_load((ROOT / "meltano.yml").read_text())
    (mapper,) = project["plugins"]["mappers"]
    spec_path = ROOT / mapper["mappings"][0]["config"]["spec_path"]
    assert MapConformMapper(config={"spec_path": str(spec_path)}).spec.streams
