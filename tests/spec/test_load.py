"""Loading: YAML 1.2 scalars, substitution, inline merge, and inheritance by presence."""

from __future__ import annotations

import json
import textwrap
from typing import TYPE_CHECKING, cast

import pytest
import yaml

from map_conform.spec.errors import SpecError
from map_conform.spec.load import (
    deep_merge,
    load_spec,
    matching_keys,
    output_streams,
    read_document,
    resolve_stream,
    specificity,
)
from map_conform.spec.model import parse_spec
from map_conform.spec.steps import CallStep

if TYPE_CHECKING:
    from pathlib import Path


def write(tmp_path: Path, text: str, name: str = "conform.yml") -> Path:
    """Write a spec file and return its path."""
    path = tmp_path / name
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def issues_of(exc: pytest.ExceptionInfo[SpecError]) -> list[str]:
    """The SpecError's issues as strings."""
    return [str(i) for i in exc.value.issues]


# --- Reading ------------------------------------------------------------------------------------


def test_yaml_uses_core_schema_scalars(tmp_path: Path) -> None:
    """yes/no/on/off, country codes, sexagesimal and dates stay strings; true/false are bools."""
    path = write(
        tmp_path, "v: [yes, no, on, OFF, NO, y, '1:30', 1:30, 2026-03-14, true, False, ~]\n"
    )
    assert read_document(path) == {
        "v": ["yes", "no", "on", "OFF", "NO", "y", "1:30", "1:30", "2026-03-14", True, False, None]
    }


def test_yaml_numbers(tmp_path: Path) -> None:
    """Core-schema integers and floats; a leading zero is decimal, as in YAML 1.2."""
    path = write(tmp_path, "v: [42, -7, 0777, 0o17, 0x1F, 1e3, .5, -1.25, .inf, 12_000]\n")
    values = cast("dict[str, list[object]]", read_document(path))["v"]
    assert values[:8] == [42, -7, 777, 15, 31, 1000.0, 0.5, -1.25]
    assert values[8] == float("inf")
    assert values[9] == "12_000"


def test_yaml_duplicate_keys_are_errors(tmp_path: Path) -> None:
    """PyYAML silently keeps the last duplicate; the loader refuses."""
    path = write(tmp_path, "version: 1\nstreams:\n  a: {}\n  a: {drop: true}\n")
    with pytest.raises(SpecError) as caught:
        read_document(path)
    assert issues_of(caught) == ["<root>: invalid YAML at line 4, column 3: duplicate key 'a'"]


def test_invalid_yaml_and_json_report_position(tmp_path: Path) -> None:
    """Syntax errors name the line and column."""
    with pytest.raises(SpecError, match="invalid YAML at line 3, column 1"):
        read_document(write(tmp_path, "a: 1\nb: [\n"))
    with pytest.raises(SpecError, match="invalid JSON at line 1, column 13"):
        read_document(write(tmp_path, '{"version": }', "conform.json"))


def test_json_and_unknown_suffix(tmp_path: Path) -> None:
    """JSON specs load; other suffixes are refused; a missing file is reported."""
    assert read_document(write(tmp_path, '{"version": 1}', "c.json")) == {"version": 1}
    with pytest.raises(SpecError, match=r"must be \.yaml, \.yml or \.json"):
        read_document(write(tmp_path, "version: 1", "c.txt"))
    with pytest.raises(SpecError, match="cannot read the spec"):
        read_document(tmp_path / "missing.yml")


# --- Substitution and inline merge ----------------------------------------------------------


def test_substitution_forms(tmp_path: Path) -> None:
    """${var} keeps its type when whole, formats inside text; env vars, defaults and escapes."""
    path = write(
        tmp_path,
        """\
        version: 1
        defaults:
          naming: {max_length: "${width}"}
          stream: {prefix: "raw_${source}_"}
          timestamp: {assume_tz: "${env:PIPELINE_TZ}"}
        streams:
          orders:
            alias: "${env:ORDERS_ALIAS:-shop_orders}"
            filter: "note != '$${literal}'"
        """,
    )
    spec = load_spec(path, spec_vars={"width": 40, "source": "sheets"},
                     env={"PIPELINE_TZ": "Europe/Paris"})  # fmt: skip
    assert spec.defaults.naming.max_length == 40  # noqa: PLR2004
    assert spec.defaults.stream.prefix == "raw_sheets_"
    assert spec.defaults.timestamp.assume_tz == "Europe/Paris"
    orders = spec.streams["orders"].spec
    assert orders.alias == "shop_orders"
    assert orders.filter == "note != '${literal}'"


def test_unknown_variables_are_reported_with_paths(tmp_path: Path) -> None:
    """Every unknown variable is reported where it is used."""
    path = write(
        tmp_path,
        """\
        version: 1
        defaults: {stream: {prefix: "${nope}"}}
        streams: {s: {alias: "x_${env:NOT_SET}"}}
        """,
    )
    with pytest.raises(SpecError) as caught:
        load_spec(path, env={})
    assert issues_of(caught) == [
        "defaults.stream.prefix: unknown variable ${nope}; set it in spec_vars",
        "streams.s.alias: environment variable 'NOT_SET' is not set",
    ]


def test_macro_parameters_are_left_for_expansion(tmp_path: Path) -> None:
    """${currency} inside a macro with that parameter is not a spec variable."""
    path = write(
        tmp_path,
        """\
        version: 1
        macros:
          money:
            params: {currency: "$"}
            steps: [{strip_chars: "${currency}${sep}"}]
        """,
    )
    spec = load_spec(path, spec_vars={"sep": ", "})
    (step,) = spec.macros["money"].steps.steps
    assert step == CallStep("strip_chars", "${currency}, ")


def test_inline_spec_merges_over_the_file(tmp_path: Path) -> None:
    """The spec setting deep-merges over spec_path: objects merge, lists replace."""
    path = write(
        tmp_path,
        """\
        version: 1
        defaults:
          values: {trim: false, null_tokens: ["", "NULL"]}
          naming: {max_length: 30}
        """,
    )
    inline = {"defaults": {"values": {"null_tokens": ["-"]}, "on_error": "null"}}
    spec = load_spec(path, inline=inline)
    assert spec.defaults.values.trim is False
    assert spec.defaults.values.null_tokens == ("-",)
    assert spec.defaults.naming.max_length == 30  # noqa: PLR2004
    assert spec.defaults.on_error == "null"


def test_inline_only_and_no_spec() -> None:
    """An inline spec alone works; neither is an error."""
    assert load_spec(inline={"version": 1}).version == 1
    with pytest.raises(SpecError, match="no spec: set spec_path or spec"):
        load_spec()


def test_parse_errors_name_the_source(tmp_path: Path) -> None:
    """Problems found after loading carry the file name."""
    with pytest.raises(SpecError, match=r"in .*conform\.yml"):
        load_spec(write(tmp_path, "version: 1\nbogus: 1\n"))


def test_deep_merge() -> None:
    """Objects merge recursively; lists and scalars replace; inputs are not mutated."""
    base = {"a": {"x": 1, "y": [1, 2]}, "b": 1}
    out = deep_merge(base, {"a": {"y": [3], "z": None}, "c": 2})
    assert out == {"a": {"x": 1, "y": [3], "z": None}, "b": 1, "c": 2}
    assert base == {"a": {"x": 1, "y": [1, 2]}, "b": 1}


# --- Inheritance by presence ----------------------------------------------------------------

LAYERED = {
    "version": 1,
    "defaults": {
        "naming": {"max_length": 50},
        "values": {"null_tokens": ["", "NULL"]},
        "on_error": "raise",
    },
    "streams": {
        "*": {"values": {"trim": False}},
        "sheets-*": {
            "prefix": "raw_sheets_",
            "naming": {"case": "lower"},
            "values": {"null_tokens": ["-"]},
            "columns": {"Amount": {"type": "decimal(12,2)", "trim": True}},
        },
        "sheets-Orders*": {"on_error": "null", "columns": {"Amount": {"nullable": False}}},
        "sheets-Orders 2024": {
            "alias": "orders_2024",
            "columns": {"Amount": {"type": "decimal(18,2)"}, "Note": {"drop": True}},
        },
        "orders_copy": {"source": "sheets-Orders 2024", "prefix": "copy_"},
        "ignored": {"drop": True},
    },
}


def test_globs_apply_least_to_most_specific() -> None:
    """Matching keys sort by specificity; the exact name comes last."""
    spec = parse_spec(LAYERED)
    assert matching_keys(spec, "sheets-Orders 2024") == [
        "*",
        "sheets-*",
        "sheets-Orders*",
        "sheets-Orders 2024",
    ]
    assert matching_keys(spec, "sheets-Customers") == ["*", "sheets-*"]
    assert matching_keys(spec, "SHEETS-Orders") == ["*"]  # case-sensitive


def test_objects_merge_and_lists_replace() -> None:
    """Each layer overrides only the keys it sets."""
    resolved = resolve_stream(parse_spec(LAYERED), "sheets-Orders 2024")
    assert resolved is not None
    settings = resolved.settings
    assert settings.naming.max_length == 50  # noqa: PLR2004 -- from defaults
    assert settings.naming.case == "lower"  # from sheets-*
    assert settings.values.trim is False  # from *
    assert settings.values.null_tokens == ("-",)  # list replaced by sheets-*
    assert settings.on_error == "null"  # from sheets-Orders*
    assert resolved.spec.prefix == "raw_sheets_"
    assert resolved.spec.alias == "orders_2024"
    amount = resolved.spec.columns["Amount"]
    assert amount.type == "decimal(18,2)"  # exact name wins
    assert amount.trim is True  # kept from sheets-*
    assert amount.nullable is False  # kept from sheets-Orders*
    assert resolved.spec.columns["Note"].drop is True
    assert resolved.matched == ("*", "sheets-*", "sheets-Orders*", "sheets-Orders 2024")


def test_unmatched_streams_follow_else() -> None:
    """else: keep conforms with the defaults; else: drop drops."""
    keep = resolve_stream(parse_spec({"version": 1}), "anything")
    assert keep is not None
    assert keep.matched == ()
    assert keep.settings == parse_spec({"version": 1}).defaults
    assert resolve_stream(parse_spec({"version": 1, "else": "drop"}), "anything") is None


def test_output_streams_include_source_copies_and_skip_drops() -> None:
    """A tap stream feeds itself and every stream whose source names it."""
    spec = parse_spec(LAYERED)
    outputs = output_streams(spec, "sheets-Orders 2024")
    assert [(o.key, o.spec.prefix) for o in outputs] == [
        (None, "raw_sheets_"),
        ("orders_copy", "copy_"),
    ]
    copy = outputs[1]
    assert copy.matched == ("orders_copy",)
    assert copy.settings.naming.max_length == 50  # noqa: PLR2004 -- defaults only, no globs
    assert output_streams(spec, "ignored") == []
    assert matching_keys(spec, "orders_copy") == ["*"]  # source keys are not globs


def test_specificity_order() -> None:
    """Exact beats any glob; more literal characters beat fewer."""
    ordered = sorted(["exact", "e*", "*", "ex*t", "[e]xact"], key=specificity)
    assert ordered == ["*", "e*", "ex*t", "[e]xact", "exact"]


def test_large_spec_file_loads(tmp_path: Path) -> None:
    """A spec far above Meltano's ~128 KiB environment-variable limit loads from a file."""
    streams = {
        f"stream_{i}": {"columns": {f"Column {j}": {"type": "string(200)"} for j in range(40)}}
        for i in range(120)
    }
    path = tmp_path / "big.json"
    path.write_text(json.dumps({"version": 1, "streams": streams}))
    assert path.stat().st_size > 128 * 1024
    assert len(load_spec(path).streams) == 120  # noqa: PLR2004


def test_global_safe_loader_is_untouched() -> None:
    """The YAML 1.2 rules are local to the spec loader, not patched into PyYAML."""
    assert yaml.safe_load("[yes, 1:30]") == [True, 90]
