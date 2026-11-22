"""spec validate (with --catalog) and spec explain (WBS 2.5)."""

from __future__ import annotations

import json
import textwrap
from typing import TYPE_CHECKING

from click.testing import CliRunner

from map_conform.cli import tools
from map_conform.spec.check import check_spec, explain, read_catalog
from map_conform.spec.load import load_spec
from map_conform.spec.model import DEFAULTS_KEYS, STREAM_KEYS, parse_spec
from tests.fixtures.paths import FIXTURES

if TYPE_CHECKING:
    from pathlib import Path

ORDERS = FIXTURES / "catalogs" / "orders_export.catalog.json"

STREAM_RULE_KEYS = ", ".join(sorted(STREAM_KEYS | DEFAULTS_KEYS))


def write(tmp_path: Path, text: str) -> Path:
    """Write a spec file."""
    path = tmp_path / "conform.yml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def run(*args: str) -> tuple[int, str, str]:
    """Invoke the tool group; return (exit code, stdout, stderr)."""
    result = CliRunner().invoke(tools, list(args))
    return result.exit_code, result.stdout, result.stderr


def test_valid_spec(tmp_path: Path) -> None:
    """A valid spec passes, with and without a catalog."""
    path = write(tmp_path, "version: 1\nstreams:\n  Orders Export: {key_properties: [order_id]}\n")
    assert run("spec", "validate", str(path))[:2] == (0, f"{path}: valid (1 stream rule(s))\n")
    code, out, _ = run("spec", "validate", str(path), "--catalog", str(ORDERS))
    assert code == 0
    assert out.endswith("checked against 1 catalog stream(s))\n")


def test_parse_errors_are_all_reported_with_paths(tmp_path: Path) -> None:
    """Strict-parse problems are listed together, each with its path."""
    path = write(
        tmp_path,
        """\
        version: 1
        defaults: {on_error: ignore}
        streams:
          s: {columns: {a: {type: decimel}}, bogus: 1}
        """,
    )
    code, _, err = run("spec", "validate", str(path))
    assert code == 1
    assert err.splitlines() == [
        f"{path}: 3 problem(s)",
        "  defaults.on_error: expected one of 'raise', 'null', 'keep', 'reject', got 'ignore'",
        f"  streams.s.bogus: unknown key; allowed here: {STREAM_RULE_KEYS}",
        "  streams.s.columns.a.type: unknown type 'decimel' at position 7 in 'decimel'",
    ]


BAD = """\
version: 1
streams:
  Orders Export:
    key_properties: [order_number]
    columns:
      Order ID: {name: Order_ID, type: int64}
      Amount ($): {drop: true}
      Amount: {type: "decimal(12,2)"}
      SKU: {name: sku}
      Qty.: {name: sku}
      Total: {source: Grand Total}
      order_year: {type: int32, expr: "year(order_date)"}
  Inventory*: {prefix: raw_}
  orders_copy: {source: Orders Exprt}
  stats: {alias: Orders Stats}
"""


def test_catalog_check_reports_every_problem_with_its_path(tmp_path: Path) -> None:
    """Against a catalog, every kind of problem is found in one run."""
    path = write(tmp_path, BAD)
    spec = load_spec(path)
    findings = [str(f) for f in check_spec(spec, read_catalog(ORDERS))]
    assert findings == [
        (
            "streams[\"Orders Export\"].columns.Amount: column 'Amount' is not in the catalog "
            "stream; a new column needs expr"
        ),
        (
            "streams[\"Orders Export\"].columns.Total: source column 'Grand Total' is not in the "
            "catalog stream; a new column needs expr"
        ),
        (
            'streams["Orders Export"].columns["Order ID"]: name \'Order_ID\' is not a legal name '
            "here; it would conform to 'order_id'"
        ),
        "streams[\"Orders Export\"].columns[\"Qty.\"]: output name 'sku' is also used by 'SKU'",
        (
            "streams[\"Orders Export\"].key_properties: 'order_number' is neither a source nor an "
            "output column"
        ),
        'warning: streams["Inventory*"]: matches no stream in the catalog',
        "streams.orders_copy.source: tap stream 'Orders Exprt' is not in the catalog",
        "warning: streams.stats: matches no stream in the catalog",
    ]
    code, _, err = run("spec", "validate", str(path), "--catalog", str(ORDERS))
    assert code == 1
    assert err.splitlines()[-1].endswith(": 6 problem(s)")


def test_key_property_cannot_be_dropped_and_undeclared_error() -> None:
    """Dropping a catalog key fails; undeclared: error names every undeclared column."""
    spec = parse_spec(
        {
            "version": 1,
            "defaults": {"undeclared": "error"},
            "streams": {"Orders Export": {"columns": {"Order ID": {"drop": True}}}},
        }
    )
    findings = [str(f) for f in check_spec(spec, read_catalog(ORDERS))]
    assert (
        findings[0]
        == 'streams["Orders Export"].columns["Order ID"]: a key property cannot be dropped'
    )
    assert len([f for f in findings if "(undeclared: error)" in f]) == 13  # noqa: PLR2004


def test_collisions_between_output_streams() -> None:
    """Two outputs with one name are an error."""
    spec = parse_spec(
        {
            "version": 1,
            "streams": {
                "Orders Export": {"alias": "orders"},
                "orders": {"source": "Orders Export"},
            },
        }
    )
    assert [str(f) for f in check_spec(spec, read_catalog(ORDERS))] == [
        "streams.orders: output stream 'orders' is also produced by 'Orders Export'"
    ]


def test_warnings_fail_only_under_strict(tmp_path: Path) -> None:
    """--strict makes warnings errors."""
    path = write(tmp_path, "version: 1\nstreams:\n  nothing: {}\n")
    assert run("spec", "validate", str(path), "--catalog", str(ORDERS))[0] == 0
    assert run("spec", "validate", str(path), "--catalog", str(ORDERS), "--strict")[0] == 1


def test_variables_are_passed(tmp_path: Path) -> None:
    """--var fills ${NAME}; a malformed --var is a usage error."""
    path = write(tmp_path, "version: 1\ndefaults: {stream: {prefix: '${p}'}}\n")
    assert run("spec", "validate", str(path))[0] == 1
    assert run("spec", "validate", str(path), "--var", "p=raw_")[0] == 0
    assert run("spec", "validate", str(path), "--var", "oops")[0] == 2  # noqa: PLR2004


def test_bad_catalog_is_reported(tmp_path: Path) -> None:
    """A catalog that is not one fails cleanly."""
    path = write(tmp_path, "version: 1\n")
    catalog = tmp_path / "c.json"
    catalog.write_text('{"nope": []}')
    code, _, err = run("spec", "validate", str(path), "--catalog", str(catalog))
    assert code == 1
    assert "a Singer catalog needs a 'streams' list" in err


def test_explain_report() -> None:
    """Explain shows matched rules, output names, column sources, names, types and notes."""
    spec = parse_spec(
        {
            "version": 1,
            "defaults": {"stream": {"prefix": "raw_"}},
            "streams": {
                "Orders*": {"on_error": "null"},
                "Orders Export": {
                    "columns": {
                        "Order ID": {"name": "order_id", "type": "int64"},
                        "Notes": {"drop": True},
                        "year": {"type": "int32", "expr": "1"},
                    }
                },
                "orders_eu": {"source": "Orders Export"},
            },
        }
    )
    report = explain(spec, "Orders Export", read_catalog(ORDERS))
    assert report["matched"] == ["Orders*", "Orders Export"]
    names = [o["name"] for o in report["outputs"]]
    assert names == ["raw_orders_export", "raw_orders_eu"]
    first = report["outputs"][0]
    assert first["settings"] == {"on_error": "null"}
    assert first["key_properties"] == ["Order ID"]
    columns = {c["name"]: c for c in first["columns"]}
    assert "notes" not in columns
    assert columns["order_id"]["type"] == "int64"
    assert columns["amount"] == {
        "source": ["Amount ($)"],
        "name": "amount",
        "type": None,
        "tap_type": ["string", "null"],
        "declared": False,
        "notes": ["dropped '$'"],
    }
    assert columns["year"]["source"] is None
    assert [c["name"] for c in first["columns"]][-1] == "year"


def test_explain_cli(tmp_path: Path) -> None:
    """Text and JSON output; a stream absent from the catalog is flagged."""
    path = write(tmp_path, "version: 1\nstreams:\n  Orders Export: {prefix: raw_}\n")
    code, out, _ = run(
        "spec", "explain", str(path), "--stream", "Orders Export", "--catalog", str(ORDERS)
    )
    assert code == 0
    assert "output stream: raw_orders_export" in out
    assert "    Amount ($) -> amount  tap ['string', 'null']  [undeclared]" in out
    code, out, _ = run("spec", "explain", str(path), "--stream", "Orders Export", "--json")
    assert json.loads(out)["outputs"][0]["name"] == "raw_orders_export"
    code, out, _ = run("spec", "explain", str(path), "--stream", "Other", "--catalog", str(ORDERS))
    assert "(not in the catalog" in out


def test_explain_shows_the_plan(tmp_path: Path) -> None:
    """With a catalog, explain compiles and prints each column's plan."""
    path = write(
        tmp_path,
        """\
        version: 1
        streams:
          Orders Export:
            columns:
              Order ID: {name: order_id, type: int64, nullable: false}
              Amount ($): {type: "decimal(12,2)", transform: [{strip_chars: "$, "}]}
        """,
    )
    code, out, _ = run(
        "spec", "explain", str(path), "--stream", "Orders Export", "--catalog", str(ORDERS)
    )
    assert code == 0
    assert "  plan:" in out
    assert "    order_id: int64 not null, on_error raise" in out
    assert "      steps: strip_chars -> cast: decimal(12,2)" in out
    code, out, _ = run(
        "spec",
        "explain",
        str(path),
        "--stream",
        "Orders Export",
        "--catalog",
        str(ORDERS),
        "--json",
    )
    plan = json.loads(out)["outputs"][0]["plan"]
    assert plan["columns"][0] == {
        "name": "order_id",
        "sources": ["Order ID"],
        "type": "int64",
        "nullable": False,
        "on_error": "raise",
        "steps": ["cast: int64"],
    }


def test_explain_reports_plan_problems(tmp_path: Path) -> None:
    """A plan that does not compile is reported, and explain exits 1."""
    path = write(
        tmp_path,
        """\
        version: 1
        streams:
          Orders Export: {columns: {Order ID: {type: int64, on_error: keep}}}
        """,
    )
    code, out, _ = run(
        "spec", "explain", str(path), "--stream", "Orders Export", "--catalog", str(ORDERS)
    )
    assert code == 1
    assert "keep would put raw text in a int64 column" in out
