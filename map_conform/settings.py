"""Plugin settings (detailed design §1).

The settings are small on purpose: the real configuration is the conform spec, a file, so
Meltano's per-variable environment size limit (~128 KiB) never applies to it. The frozen
:class:`Settings` dataclass is the single source: the mapper's ``config_jsonschema`` (what
``--about`` lists and the Singer SDK validates) is generated from it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from map_conform.spec._struct import (
    Issues,
    documented,
    empty_mapping,
    parse_dataclass,
    positive,
    schema,
)
from map_conform.spec.errors import SpecError


@dataclass(frozen=True)
class StorageSettings:
    """Where BATCH output files are written."""

    root: str | None = documented(
        "An fsspec URL (file://, s3://, ...). Default: the input file's directory.",
        default=None,
    )
    params: Mapping[str, Any] = documented("fsspec storage options.", default_factory=empty_mapping)


@dataclass(frozen=True)
class BatchOutputSettings:
    """How BATCH input is written out."""

    mode: Literal["batch", "record"] = documented(
        "Write new BATCH files, or emit the rows as RECORD messages.", default="batch"
    )
    format: Literal["parquet", "jsonl"] = documented("Output file encoding.", default="parquet")
    compression: Literal["zstd", "snappy", "gzip", "none"] | None = documented(
        "Output compression. Default: zstd for parquet, gzip for jsonl.", default=None
    )
    storage: StorageSettings = documented("Output location.", default_factory=StorageSettings)
    delete_input: bool = documented(
        "Delete each input file after its output is written.", default=False
    )
    row_group_size: int = documented(
        "Rows per parquet row group, which is also the processing chunk size.",
        default=131072,
        metadata={"check": positive},
    )


@dataclass(frozen=True)
class RejectSettings:
    """The dead-letter sink for rows rejected under on_error: reject."""

    storage: str = documented("Directory for reject files.", default="./.map-conform/rejects")
    format: Literal["jsonl", "parquet"] = documented("Reject file encoding.", default="jsonl")


@dataclass(frozen=True)
class Settings:
    """map-conform plugin settings."""

    spec_path: str | None = documented(
        "Path to the conform spec (YAML or JSON). Relative paths resolve against the current "
        "directory, which is the project root under Meltano.",
        default=None,
    )
    spec: Mapping[str, Any] | None = documented(
        "An inline conform spec for small cases; deep-merged over spec_path.", default=None
    )
    spec_vars: Mapping[str, Any] = documented(
        "Values for ${name} in the spec. Environment variables are ${env:NAME}.",
        default_factory=empty_mapping,
    )
    strict: bool = documented(
        "Treat undeclared columns as errors and make warnings errors.", default=False
    )
    allow_python_udfs: bool = documented(
        "Allow udfs given as module paths. Entry-point UDFs are always allowed.", default=False
    )
    batch_output: BatchOutputSettings = documented(
        "BATCH output.", default_factory=BatchOutputSettings
    )
    reject: RejectSettings = documented("Reject sink.", default_factory=RejectSettings)
    metrics_path: str | None = documented(
        "Write per-stream metrics as JSON here at the end of the run.", default=None
    )


def parse_settings(config: Mapping[str, Any]) -> Settings:
    """Parse the plugin config into :class:`Settings`.

    Raises:
        SpecError: listing every problem, each with its setting path.
    """
    issues = Issues()
    settings = parse_dataclass(Settings, dict(config), "", issues)
    if issues or not isinstance(settings, Settings):
        raise SpecError(issues.items, "the plugin settings")
    return settings


def settings_jsonschema() -> dict[str, Any]:
    """The settings' JSON Schema with every reference inlined, for the Singer SDK."""
    defs: dict[str, Any] = {}
    root = schema(Settings, defs)
    return cast("dict[str, Any]", _inline(root, defs))


def _inline(node: object, defs: Mapping[str, Any]) -> object:
    if isinstance(node, dict):
        out: dict[str, object] = {}
        if "$ref" in node:
            target = _inline(defs[node["$ref"].removeprefix("#/$defs/")], defs)
            out.update(cast("dict[str, object]", target))
        out.update({k: _inline(v, defs) for k, v in node.items() if k != "$ref"})
        return out
    if isinstance(node, list):
        return [_inline(v, defs) for v in node]
    return node
