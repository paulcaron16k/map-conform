"""spec import --catalog drafts a valid spec; Zamboni columns round-trip (WBS 9.1, 9.2)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
import yaml
from click.testing import CliRunner

from map_conform.cli import tools
from map_conform.spec.check import check_spec, read_catalog
from map_conform.spec.model import parse_spec
from tests.fixtures.paths import FIXTURES

if TYPE_CHECKING:
    from pathlib import Path

ORDERS = FIXTURES / "catalogs" / "orders_export.catalog.json"
INVENTORY = FIXTURES / "catalogs" / "inventory_xlsx.catalog.json"
SPEC = """\
version: 1
defaults: {add_record_metadata: true}
streams:
  Orders Export:
    columns:
      Order ID: {name: order_id, type: int64}
      Amount ($): {type: "decimal(12,2)"}
      Order Date: {type: date}
"""


def invoke(*args: str) -> Any:  # noqa: ANN401 -- click's Result
    """Run a tool command."""
    return CliRunner().invoke(tools, list(args))


@pytest.mark.parametrize("catalog", [ORDERS, INVENTORY])
def test_draft_validates(catalog: Path) -> None:
    """The drafted spec is valid against the catalog it came from."""
    result = invoke("spec", "import", "--catalog", str(catalog))
    assert result.exit_code == 0, result.output
    draft = yaml.safe_load(result.stdout)
    assert [
        f for f in check_spec(parse_spec(draft), read_catalog(catalog)) if f.severity == "error"
    ] == []
    stream = next(iter(draft["streams"].values()))
    assert all("type" in column for column in stream["columns"].values())


def test_draft_types_and_keys() -> None:
    """Typed catalogs give typed columns; key properties are kept."""
    draft = yaml.safe_load(invoke("spec", "import", "--catalog", str(INVENTORY)).stdout)
    (stream,) = draft["streams"].values()
    types = {k: v["type"] for k, v in stream["columns"].items()}
    assert "float64" in types.values() or "decimal(38,9)" in types.values()
    orders = yaml.safe_load(invoke("spec", "import", "--catalog", str(ORDERS)).stdout)
    assert orders["streams"]["Orders Export"]["key_properties"] == ["Order ID"]


def table_config(path: Path) -> Path:
    """A Zamboni v2 table-config with layout keys that must survive."""
    document = {
        "version": 2,
        "warehouse": "lake",
        "defaults": {"min_input_files": 4},
        "namespaces": {"raw": {"tables": {"orders_export": {
            "description": "Orders.", "partition": [{"column": "order_date", "transform": "day"}],
        }}}},
    }  # fmt: skip
    path.write_text(
        json.dumps(document, indent=2) if path.suffix == ".json" else yaml.safe_dump(document)
    )
    return path


@pytest.mark.parametrize("suffix", [".json", ".yml"])
def test_zamboni_round_trip(tmp_path: Path, suffix: str) -> None:
    """Export writes canonical types into columns; import reads them back into a draft."""
    (tmp_path / "conform.yml").write_text(SPEC)
    config = table_config(tmp_path / f"table-config{suffix}")
    result = invoke("spec", "export", str(tmp_path / "conform.yml"), "--zamboni", str(config),
                    "--catalog", str(ORDERS))  # fmt: skip
    assert result.exit_code == 0, result.output
    text = config.read_text()
    document = json.loads(text) if suffix == ".json" else yaml.safe_load(text)
    table = document["namespaces"]["raw"]["tables"]["orders_export"]
    assert table["partition"] == [{"column": "order_date", "transform": "day"}]  # kept
    assert document["defaults"] == {"min_input_files": 4}
    columns = table["columns"]
    assert columns["order_id"] == "int64"
    assert columns["amount"] == "decimal(12,2)"
    assert columns["order_date"] == "date"
    assert columns["customer_id"] == "string"
    assert columns["_sdc_batched_at"] == "timestamptz"
    result = invoke("spec", "import", "--catalog", str(ORDERS), "--zamboni", str(config))
    assert result.exit_code == 0, result.output
    draft = yaml.safe_load(result.stdout)["streams"]["Orders Export"]["columns"]
    assert draft["Order ID"]["type"] == "int64"
    assert draft["Amount ($)"]["type"] == "decimal(12,2)"
    assert draft["Order Date"]["type"] == "date"
    parsed = parse_spec(yaml.safe_load(result.stdout))
    assert [f for f in check_spec(parsed, read_catalog(ORDERS)) if f.severity == "error"] == []


def test_export_creates_missing_tables_and_writes_elsewhere(tmp_path: Path) -> None:
    """A table the file does not have is created; -o leaves the input untouched."""
    (tmp_path / "conform.yml").write_text("version: 1\n")
    config = tmp_path / "tc.json"
    config.write_text(json.dumps({"version": 2, "namespaces": {"raw": {"tables": {}}}}))
    out = tmp_path / "out.json"
    result = invoke("spec", "export", str(tmp_path / "conform.yml"), "--zamboni", str(config),
                    "--catalog", str(INVENTORY), "-o", str(out))  # fmt: skip
    assert result.exit_code == 0, result.output
    assert json.loads(config.read_text())["namespaces"]["raw"]["tables"] == {}
    assert json.loads(out.read_text())["namespaces"]["raw"]["tables"]


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({"version": 1, "tables": {}}, "only Zamboni table-config version 2"),
        ({"version": 2, "namespaces": {"a": {}, "b": {}}}, "choose a namespace with --namespace"),
    ],
)
def test_table_config_problems(tmp_path: Path, document: dict[str, Any], message: str) -> None:
    """Old versions and ambiguous namespaces are refused with a reason."""
    config = tmp_path / "tc.json"
    config.write_text(json.dumps(document))
    result = invoke("spec", "import", "--catalog", str(ORDERS), "--zamboni", str(config))
    assert result.exit_code == 1
    assert message in result.output


def test_non_canonical_zamboni_type_is_noted(tmp_path: Path) -> None:
    """A Zamboni type map-conform does not know keeps the catalog's type, with a note.

    Aliases are understood: long is read as int64.
    """
    config = tmp_path / "tc.json"
    config.write_text(json.dumps({"version": 2, "namespaces": {"raw": {"tables": {
        "orders_export": {"columns": {"order_id": "long", "customer_id": "frob"}}}}}}))  # fmt: skip
    result = invoke("spec", "import", "--catalog", str(ORDERS), "--zamboni", str(config))
    assert result.exit_code == 0, result.output
    assert "Zamboni type 'frob' is not a canonical type" in result.stderr
    columns = yaml.safe_load(result.stdout)["streams"]["Orders Export"]["columns"]
    assert (columns["Order ID"]["type"], columns["customerID"]["type"]) == ("int64", "string")


def test_usage_errors() -> None:
    """The import command needs a catalog or stream maps."""
    assert "give --catalog" in invoke("spec", "import").output
    assert invoke("spec", "import").exit_code == 2  # noqa: PLR2004
