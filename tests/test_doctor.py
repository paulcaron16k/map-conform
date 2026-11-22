"""map-conform doctor checks a Meltano project (WBS 9.3)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import yaml
from click.testing import CliRunner

from map_conform.cli import tools
from map_conform.doctor import check_project

if TYPE_CHECKING:
    from pathlib import Path


def project(tmp_path: Path, mapper_config: dict[str, Any], **extra: Any) -> Path:
    """A meltano.yml with tap-csv | map-conform (mapping `conform`) | target-ducklake."""
    document = {
        "plugins": {
            "extractors": [{"name": "tap-csv"}],
            "mappers": [{"name": "map-conform", "namespace": "map_conform",
                         "config": mapper_config, "mappings": [{"name": "conform", "config": {}}]}],
            "loaders": extra.pop("loaders", [{"name": "target-ducklake", "config": {}},
                                             {"name": "target-jsonl", "config": {}}]),
        },
        "jobs": [{"name": "load", "tasks": ["tap-csv conform target-ducklake"]}],
        **extra,
    }  # fmt: skip
    path = tmp_path / "meltano.yml"
    path.write_text(yaml.safe_dump(document))
    return path


def messages(path: Path) -> list[str]:
    """The findings as text."""
    return [str(f) for f in check_project(path)]


def test_flags_a_missing_add_record_metadata(tmp_path: Path) -> None:
    """The mapping adds _sdc_*; the target after it in the job does not keep them."""
    found = messages(project(tmp_path, {"add_record_metadata": True}))
    assert found == [
        (
            "error: plugins.loaders.target-ducklake.config: conform adds _sdc_* columns, but this "
            "target does not set add_record_metadata: true, so an SDK target strips them (unless "
            "it is set in the environment)"
        )
    ]


def test_metadata_set_on_the_target_or_off_is_fine(tmp_path: Path) -> None:
    """No finding when the target keeps the columns, or when none are added."""
    loaders = [{"name": "target-ducklake", "config": {"add_record_metadata": True}}]
    assert messages(project(tmp_path, {"add_record_metadata": True}, loaders=loaders)) == []
    assert messages(project(tmp_path, {})) == []


def test_metadata_from_the_spec_and_inherited_loaders(tmp_path: Path) -> None:
    """add_record_metadata in the spec counts; a loader inherits its parent's config."""
    (tmp_path / "conform.yml").write_text("version: 1\ndefaults: {add_record_metadata: true}\n")
    loaders = [{"name": "target-base", "config": {"add_record_metadata": True}},
               {"name": "target-ducklake", "inherit_from": "target-base"}]  # fmt: skip
    assert messages(project(tmp_path, {"spec_path": "conform.yml"}, loaders=loaders)) == []
    assert len(messages(project(tmp_path, {"spec_path": "conform.yml"}))) == 1


def test_without_jobs_every_loader_is_checked(tmp_path: Path) -> None:
    """With no job using the mapping, each loader must keep the columns."""
    path = project(tmp_path, {"add_record_metadata": True}, jobs=[])
    assert [f.where for f in check_project(path)] == [
        "plugins.loaders.target-ducklake.config",
        "plugins.loaders.target-jsonl.config",
    ]


def test_spec_path_and_spec_problems(tmp_path: Path) -> None:
    """A missing spec file, or a spec with problems, is reported."""
    assert "'nope.yml' does not exist" in messages(project(tmp_path, {"spec_path": "nope.yml"}))[0]
    (tmp_path / "conform.yml").write_text("version: 1\ndefaults: {on_error: maybe}\n")
    found = messages(project(tmp_path, {"spec_path": "conform.yml"}))
    assert "defaults.on_error: expected one of" in found[0]


def test_udf_opt_in(tmp_path: Path) -> None:
    """Module-path udfs need allow_python_udfs; the setting alone is noted."""
    (tmp_path / "conform.yml").write_text("version: 1\nudfs: {f: pkg.mod:fn}\n")
    found = messages(project(tmp_path, {"spec_path": "conform.yml"}))
    assert found == [("error: plugins.mappers.map-conform.mappings.conform.config: the spec has "
                     "module-path udfs; set allow_python_udfs: true to allow them")]  # fmt: skip
    found = messages(project(tmp_path, {"allow_python_udfs": True}))
    assert found == [("note: plugins.mappers.map-conform.mappings.conform.config.allow_python_udfs"
                     ": set, but the spec has no module-path udfs")]  # fmt: skip


def test_invalid_settings_and_no_mapper(tmp_path: Path) -> None:
    """Bad settings are errors; a project without map-conform is a warning."""
    assert "invalid setting" in messages(project(tmp_path, {"strict": "yes"}))[0]
    path = tmp_path / "meltano.yml"
    path.write_text(yaml.safe_dump({"plugins": {"loaders": [{"name": "target-jsonl"}]}}))
    assert messages(path) == [f"warning: {path}: no map-conform mapper in plugins.mappers"]


def test_cli_exit_codes(tmp_path: Path) -> None:
    """Errors exit 1; --strict also fails on warnings; a clean project exits 0."""
    bad = project(tmp_path, {"add_record_metadata": True})
    result = CliRunner().invoke(tools, ["doctor", "--meltano-yml", str(bad)])
    assert result.exit_code == 1
    assert "1 problem(s)" in result.output
    good = project(tmp_path, {})
    assert CliRunner().invoke(tools, ["doctor", "--meltano-yml", str(good)]).exit_code == 0
    warn = tmp_path / "meltano.yml"
    warn.write_text(yaml.safe_dump({"plugins": {}}))
    assert CliRunner().invoke(tools, ["doctor", "--meltano-yml", str(warn)]).exit_code == 0
    assert (
        CliRunner().invoke(tools, ["doctor", "--meltano-yml", str(warn), "--strict"]).exit_code == 1
    )
