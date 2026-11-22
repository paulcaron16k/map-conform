"""spec import --stream-maps: the native spec gives the same output (WBS 12.8)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
import yaml
from click.testing import CliRunner

from map_conform.cli import tools
from tests.compat.harness import ours_run
from tests.compat.sdk_cases import CASES, MYSTREAM, SAMPLE

if TYPE_CHECKING:
    from pathlib import Path

ROUND_TRIP = [
    "only_mapped_fields",
    "changed_key_properties",
    "sourced_stream_2",
    "builtin_variable_stream_name_alias",
    "non_pk_passthrough",
    "record_to_column",
    "dates",
    "filter_records",
    "map_and_flatten",
    "transform_expressions",
    "clone_and_alias",
]


def catalog(path: Path, streams: dict[str, Any]) -> Path:
    """Write a Singer catalog for the case's streams."""
    document = {
        "streams": [
            {"tap_stream_id": name, "stream": name, "schema": schema, "key_properties": keys}
            for name, (schema, keys, _) in streams.items()
        ]
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def import_spec(
    tmp_path: Path, settings: dict[str, Any], streams: dict[str, Any]
) -> dict[str, Any]:
    """Run `map-conform spec import --stream-maps ... --catalog ...` and parse the output."""
    config = tmp_path / "config.json"
    config.write_text(json.dumps(settings), encoding="utf-8")
    args = ["spec", "import", "--stream-maps", str(config),
            "--catalog", str(catalog(tmp_path / "catalog.json", streams))]  # fmt: skip
    result = CliRunner().invoke(tools, args)
    assert result.exit_code == 0, result.output
    return yaml.safe_load(result.stdout)


@pytest.mark.parametrize("case", ROUND_TRIP)
def test_round_trip(case: str, tmp_path: Path) -> None:
    """Import, then run the native spec: the output equals running the stream maps."""
    streams, stream_maps, config = CASES[case]
    settings = {"stream_maps": stream_maps, **config}
    spec = import_spec(tmp_path, settings, streams)
    assert "infer_type" not in json.dumps(spec)  # every type is explicit with a catalog
    expected = ours_run(streams, stream_maps, config)
    spec_vars = config.get("stream_map_config", {})
    actual = ours_run(streams, None, {"spec": spec, "spec_vars": spec_vars})
    assert actual == expected


def test_without_a_catalog_types_stay_inferred(tmp_path: Path) -> None:
    """Without --catalog, a type that depends on the tap keeps infer_type, with a note."""
    config = tmp_path / "config.json"
    stream_maps = {"mystream": {"n": "count", "f": "float(count)", "__else__": None}}
    config.write_text(json.dumps({"stream_maps": stream_maps}), encoding="utf-8")
    result = CliRunner().invoke(tools, ["spec", "import", "--stream-maps", str(config)])
    assert result.exit_code == 0, result.output
    columns = yaml.safe_load(result.stdout)["streams"]["mystream"]["columns"]
    assert columns["f"] == {"expr": "float(record['count'])", "type": "float64"}
    assert columns["n"] == {"expr": "record['count']", "infer_type": "sdk"}
    assert "streams.mystream.columns.n: kept infer_type: sdk (no --catalog)" in result.stderr


def test_output_file_and_problems(tmp_path: Path) -> None:
    """-o writes the file; bad settings are listed with their paths and exit 1."""
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"stream_maps": {"s": None}}), encoding="utf-8")
    out = tmp_path / "conform.yml"
    result = CliRunner().invoke(
        tools, ["spec", "import", "--stream-maps", str(config), "-o", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert yaml.safe_load(out.read_text())["streams"] == {"s": {"drop": True}}
    config.write_text(json.dumps({"stream_maps": {"s": "x"}}), encoding="utf-8")
    result = CliRunner().invoke(tools, ["spec", "import", "--stream-maps", str(config)])
    assert result.exit_code == 1
    assert "stream_maps.s: a stream map is a mapping, null or __NULL__" in result.stderr
    result = CliRunner().invoke(tools, ["spec", "import"])
    assert result.exit_code == 2  # noqa: PLR2004 -- click's usage error
    assert "give --catalog CATALOG.json, --stream-maps CONFIG.json, or both" in result.output


def test_samples_cover_both_fixtures() -> None:
    """The round trip runs on both of the SDK tests' input fixtures."""
    fixtures = {id(CASES[c][0]) for c in ROUND_TRIP}
    assert fixtures == {id(MYSTREAM), id(SAMPLE)}
