"""``map-conform doctor``: check a Meltano project's use of map-conform (WBS 9.3).

For each map-conform mapper in ``meltano.yml`` and each of its mappings (the mapping's
config over the plugin's), the doctor checks:

1. the settings are valid;
2. ``spec_path`` exists (relative to the project) and the spec, with any ``stream_maps``,
   loads without problems;
3. UDF opt-in: spec ``udfs`` given as module paths need ``allow_python_udfs: true``; the
   setting without such UDFs is noted;
4. ``_sdc_*`` columns: when the mapping adds them (``add_record_metadata``, in the settings
   or anywhere in the spec), every loader that runs after it in a job must set
   ``add_record_metadata: true``, or an SDK target strips them. With no job using the
   mapping, every loader is checked.

Config set only through environment variables is not visible here; a finding says so.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from map_conform.settings import parse_settings
from map_conform.spec._struct import Issues
from map_conform.spec.errors import SpecError
from map_conform.spec.load import deep_merge, load_spec
from map_conform.spec.stream_maps import SDK_SETTINGS, translate

Severity = Literal["error", "warning", "note"]


@dataclass(frozen=True)
class Finding:
    """One problem or remark."""

    severity: Severity
    where: str
    message: str

    @override
    def __str__(self) -> str:
        """``error: plugins.mappers.map-conform: ...``."""
        return f"{self.severity}: {self.where}: {self.message}"


def _is_map_conform(plugin: dict[str, Any]) -> bool:
    return (
        plugin.get("name") == "map-conform"
        or plugin.get("namespace") == "map_conform"
        or plugin.get("executable") == "map-conform"
        or "map-conform" in str(plugin.get("pip_url", ""))
        or plugin.get("inherit_from") == "map-conform"
    )


def _plugins(project: dict[str, Any], kind: str) -> dict[str, dict[str, Any]]:
    return {p["name"]: p for p in (project.get("plugins") or {}).get(kind) or [] if "name" in p}


def _loader_config(loaders: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
    """A loader's config, over its ``inherit_from`` parent's."""
    plugin = loaders.get(name) or {}
    parent = plugin.get("inherit_from")
    base = _loader_config(loaders, parent) if parent and parent != name else {}
    merged = deep_merge(base, plugin.get("config") or {})
    return merged if isinstance(merged, dict) else {}


def _following_loaders(
    project: dict[str, Any], mapping: str, loaders: dict[str, dict[str, Any]]
) -> list[str]:
    """Loaders that run after the mapping in any job's task."""
    found: list[str] = []
    for job in project.get("jobs") or []:
        for task in job.get("tasks") or []:
            steps = task.split() if isinstance(task, str) else [s for t in task for s in t.split()]
            if mapping not in steps:
                continue
            later = steps[steps.index(mapping) + 1 :]
            found.extend(s for s in later if s in loaders and s not in found)
    return found


def _adds_metadata(config: dict[str, Any], spec_doc: Any) -> bool:  # noqa: ANN401 -- a Spec
    if config.get("add_record_metadata"):
        return True
    if spec_doc is None:
        return False
    if spec_doc.defaults.add_record_metadata:
        return True
    return any(rules.raw.get("add_record_metadata") for rules in spec_doc.streams.values())


def check_project(path: str | Path) -> list[Finding]:
    """Every finding for the project at ``path`` (a meltano.yml)."""
    file = Path(path)
    try:
        project = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        return [Finding("error", str(file), f"cannot read the project: {exc}")]
    mappers = {n: p for n, p in _plugins(project, "mappers").items() if _is_map_conform(p)}
    if not mappers:
        return [Finding("warning", str(file), "no map-conform mapper in plugins.mappers")]
    loaders = _plugins(project, "loaders")
    findings: list[Finding] = []
    for name, plugin in mappers.items():
        mappings = plugin.get("mappings") or [{"name": name, "config": {}}]
        for mapping in mappings:
            where = f"plugins.mappers.{name}.mappings.{mapping.get('name', name)}"
            merged = deep_merge(plugin.get("config") or {}, mapping.get("config") or {})
            config = merged if isinstance(merged, dict) else {}
            name_of = str(mapping.get("name", name))
            findings.extend(
                _check_mapping(file.parent, project, loaders, where=where, mapping=name_of,
                               config=config)
            )  # fmt: skip
    return findings


def _check_mapping(  # noqa: PLR0913 -- the mapping and its project
    root: Path,
    project: dict[str, Any],
    loaders: dict[str, dict[str, Any]],
    *,
    where: str,
    mapping: str,
    config: dict[str, Any],
) -> list[Finding]:
    findings: list[Finding] = []
    try:
        settings = parse_settings(config)
    except SpecError as exc:
        return [Finding("error", where, f"invalid setting: {i}") for i in exc.issues]
    spec = None
    spec_path = settings.spec_path
    if spec_path is not None and not (root / spec_path).is_file():
        findings.append(
            Finding("error", f"{where}.config.spec_path", f"{spec_path!r} does not exist")
        )
        spec_path = None
    issues = Issues()
    base = translate({k: getattr(settings, k) for k in SDK_SETTINGS}, issues)
    findings.extend(Finding("error", where, str(i)) for i in issues.items)
    if spec_path is not None or settings.spec is not None or base is not None:
        try:
            spec = load_spec(root / spec_path if spec_path else None, settings.spec,
                             settings.spec_vars, base=base)  # fmt: skip
        except SpecError as exc:
            findings.extend(Finding("error", f"{where} (spec)", str(i)) for i in exc.issues)
    if spec is not None and spec.udfs and not settings.allow_python_udfs:
        findings.append(Finding("error", f"{where}.config", "the spec has module-path udfs; "
                                "set allow_python_udfs: true to allow them"))  # fmt: skip
    if settings.allow_python_udfs and (spec is None or not spec.udfs):
        findings.append(Finding("note", f"{where}.config.allow_python_udfs",
                                "set, but the spec has no module-path udfs"))  # fmt: skip
    if _adds_metadata(config, spec):
        targets = _following_loaders(project, mapping, loaders) or list(loaders)
        message = (
            f"{mapping} adds _sdc_* columns, but this target does not set "
            "add_record_metadata: true, so an SDK target strips them (unless it is set in "
            "the environment)"
        )
        findings.extend(
            Finding("error", f"plugins.loaders.{loader}.config", message)
            for loader in targets
            if not _loader_config(loaders, loader).get("add_record_metadata")
        )
    return findings
