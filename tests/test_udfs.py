"""UDFs: the decorator, entry points and module paths behind allow_python_udfs (WBS 6.5)."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from singer_sdk.exceptions import ConfigValidationError

from map_conform.errors import ConformError
from map_conform.mapper import MapConformMapper
from map_conform.plan.compile import compile_stream
from map_conform.plan.row import RowExecutor
from map_conform.spec.errors import SpecError
from map_conform.spec.load import resolve_stream
from map_conform.spec.model import parse_spec
from map_conform.transforms.builtins import builtin_registry
from map_conform.udfs import Udf, UdfOptions, load_udfs, registry_with
from tests.fixtures.paths import FIXTURES

SITE = FIXTURES / "udfs" / "site"
PROJECT = FIXTURES / "udfs" / "project"
STRING = {"type": ["null", "string"]}


@pytest.fixture
def installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put the sample UDF package (with its entry points) on sys.path."""
    monkeypatch.syspath_prepend(str(SITE))


@pytest.fixture
def project(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run from the sample project directory, where its UDF module lives."""
    monkeypatch.chdir(PROJECT)


def conform(
    columns: dict[str, Any], *records: dict[str, Any], udfs: dict[str, str] | None = None
) -> list[dict[str, Any] | None]:
    """Compile stream s with the installed (and allowed spec) UDFs and conform records."""
    spec = parse_spec({
        "version": 1,
        "defaults": {"metadata": "none"},
        "udfs": udfs or {},
        "streams": {"s": {"columns": columns}},
    })  # fmt: skip
    registry = registry_with(builtin_registry(), load_udfs(spec.udfs, allow_python_udfs=True))
    resolved = resolve_stream(spec, "s")
    assert resolved is not None
    properties = dict.fromkeys(columns, STRING)
    plan = compile_stream(spec, resolved, {"properties": properties}, registry)
    executor = RowExecutor(plan, resolved.settings)
    return [executor.run(r, {}, i) for i, r in enumerate(records, 1)]


@pytest.mark.usefixtures("installed")
def test_entry_point_udfs_as_steps_and_in_expressions() -> None:
    """Installed UDFs work as steps (kwargs checked) and as functions in expressions."""
    columns = {
        "ordered": {
            "type": "int32",
            "transform": [{"cast": "date"}, {"fiscal_week": {"start_month": 4}}],
        },
        "sku": {"type": "string", "transform": "clean_sku"},
        "note": {"type": "string", "expr": "shout(value, suffix='?')"},
    }
    out = conform(columns, {"ordered": "2026-04-15", "sku": " ab-1 ", "note": "hi"})
    assert out == [{"ordered": 3, "sku": "AB-1", "note": "HI?"}]


@pytest.mark.usefixtures("installed")
def test_udf_kwargs_are_checked_at_compile_time() -> None:
    """An unknown option is a spec error at its path, like a builtin's."""
    with pytest.raises(SpecError) as caught:
        conform(
            {"d": {"type": "int32", "transform": [{"cast": "date"}, {"fiscal_week": {"x": 1}}]}}
        )
    assert "transform[1].x: unknown key; allowed here: start_month" in str(caught.value.issues[0])


@pytest.mark.usefixtures("installed")
def test_returns_types_the_chain() -> None:
    """Returns says what the step produces, so a mismatch is caught when the plan compiles."""
    with pytest.raises(SpecError, match="ends as a int32 value, but the column is date"):
        conform({"d": {"type": "date", "transform": [{"cast": "date"}, "fiscal_week"]}})


@pytest.mark.usefixtures("project")
def test_module_path_udfs_need_the_setting() -> None:
    """Spec udfs import project code, so they are refused unless allowed."""
    with pytest.raises(SpecError) as caught:
        load_udfs({"where_from": "project_udfs:where_from"}, allow_python_udfs=False)
    assert "udfs.where_from: module-path UDFs run project code" in str(caught.value.issues[0])
    udfs = load_udfs({"where_from": "project_udfs:where_from"}, allow_python_udfs=True)
    assert udfs["where_from"].origin == "project_udfs:where_from"


@pytest.mark.usefixtures("project")
def test_module_path_udfs_get_ctx_and_nulls() -> None:
    """A ctx parameter receives the step context; null_safe UDFs see nulls."""
    out = conform(
        {"c": {"type": "string", "transform": "where_from"}},
        {"c": "x"},
        {"c": None},
        udfs={"where_from": "project_udfs:where_from"},
    )
    assert out == [{"c": "s:x"}, {"c": "s:null"}]


@pytest.mark.usefixtures("project")
def test_udf_failures_follow_on_error() -> None:
    """An exception in a UDF is a ConformError naming the step, not a crash."""
    with pytest.raises(ConformError, match=r"explode failed on 'x': RuntimeError: cannot handle"):
        conform(
            {"c": {"type": "string", "transform": "explode"}},
            {"c": "x"},
            udfs={"explode": "project_udfs:explode"},
        )


@pytest.mark.usefixtures("project")
@pytest.mark.parametrize(
    ("udfs", "message"),
    [
        ({"x": "no_such_module:f"}, "udfs.x: cannot import 'no_such_module'"),
        ({"x": "project_udfs:nope"}, "udfs.x: 'project_udfs' has no function 'nope'"),
    ],
)
def test_loading_problems(udfs: dict[str, str], message: str) -> None:
    """Import problems are reported at the spec path."""
    with pytest.raises(SpecError) as caught:
        load_udfs(udfs, allow_python_udfs=True)
    assert message in str(caught.value.issues[0])


@pytest.mark.usefixtures("project")
@pytest.mark.parametrize(
    ("udfs", "message"),
    [
        ({"trim": "project_udfs:explode"}, "udfs.trim: 'trim' is a builtin"),
        ({"md5": "project_udfs:explode"}, "udfs.md5: 'md5' is an expression function"),
        ({"bad": "project_udfs:broken"}, "option 'option' must be keyword-only"),
    ],
)
def test_registration_problems(udfs: dict[str, str], message: str) -> None:
    """Names that shadow builtins or library functions, and bad signatures, are refused."""
    loaded = load_udfs(udfs, allow_python_udfs=True)
    with pytest.raises(SpecError) as caught:
        registry_with(builtin_registry(), loaded)
    assert message in str(caught.value.issues[0])


def test_returns_must_be_a_ctype() -> None:
    """A bad returns is reported when the UDF is registered."""
    bad = Udf("f", lambda value: value, "test", UdfOptions(returns="decimal"))
    with pytest.raises(SpecError, match="returns: decimal needs a precision and scale"):
        registry_with(builtin_registry(), {"f": bad})


@pytest.mark.usefixtures("installed", "project")
def test_mapper_loads_udfs(capsys: pytest.CaptureFixture[str]) -> None:
    """The mapper registers UDFs at start-up, and refuses spec udfs without the setting."""
    spec = {
        "version": 1,
        "defaults": {"metadata": "none"},
        "udfs": {"where_from": "project_udfs:where_from"},
        "streams": {"s": {"columns": {"c": {"type": "string", "transform": "where_from"}}}},
    }
    with pytest.raises(ConfigValidationError):
        MapConformMapper(config={"spec": spec})
    mapper = MapConformMapper(config={"spec": spec, "allow_python_udfs": True})
    messages = [
        {"type": "SCHEMA", "stream": "s", "schema": {"properties": {"c": STRING}},
         "key_properties": []},
        {"type": "RECORD", "stream": "s", "record": {"c": "v"}},
    ]  # fmt: skip
    capsys.readouterr()
    mapper.listen(io.StringIO("".join(json.dumps(m) + "\n" for m in messages)))
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[-1]["record"] == {"c": "s:v"}


@pytest.mark.usefixtures("installed")
def test_functions_lists_installed_udfs() -> None:
    """map-conform functions documents installed UDFs with their docstrings."""
    from map_conform.cli import functions_report  # noqa: PLC0415 -- after the fixture

    steps = {s["name"]: s for s in functions_report()["steps"]}
    assert steps["fiscal_week"]["doc"] == (
        "Week of the fiscal year that starts on the first of start_month."
    )
    assert steps["fiscal_week"]["signature"] == "start_month=7"
    assert steps["fiscal_week"]["udf"] is True
    assert steps["trim"]["udf"] is False


def test_sample_package_layout() -> None:
    """The fixture package declares its entry points like an installed distribution."""
    text = (SITE / "sample_udfs-0.1.dist-info" / "entry_points.txt").read_text()
    assert "[map_conform.functions]" in text
    assert Path(SITE / "sample_udfs" / "__init__.py").is_file()
