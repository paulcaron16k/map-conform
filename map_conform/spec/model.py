"""The conform spec as frozen dataclasses (detailed design §3).

These classes are the single source of truth for the spec grammar: the strict parser, the
dump used for round trips and the shipped JSON Schema are all derived from them.

Inheritance by presence (defaults -> matching globs -> exact name) happens on the raw
mappings before parsing, in :mod:`map_conform.spec.load`. A :class:`StreamSpec` therefore
carries only the stream's own keys; the :class:`Defaults` keys it overrides are parsed into
the merged :class:`Defaults` of the resolved stream.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

from map_conform.spec._struct import (
    INVALID,
    Issues,
    child,
    dataclass_schema,
    freeze_mapping,
    parse_dataclass,
    thaw,
)
from map_conform.spec.errors import SpecError
from map_conform.spec.steps import Chain, Macro
from map_conform.types.canonical import ctype_problem

OnError = Literal["raise", "null", "keep", "reject"]
Dialect = Literal["ansi", "postgres", "duckdb"]

_UDF_TARGET = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")


def _doc(text: str, **kwargs: Any) -> Any:  # noqa: ANN401 -- dataclasses.field's own type
    """A dataclass field with schema documentation."""
    metadata = {"doc": text}
    metadata.update(kwargs.pop("metadata", {}))
    return field(metadata=metadata, **kwargs)


def _empty() -> Mapping[str, Any]:
    return MappingProxyType({})


def _udf_problem(target: str) -> str | None:
    return None if _UDF_TARGET.match(target) else "expected 'package.module:function'"


def _positive(value: int) -> str | None:
    return None if value > 0 else "must be at least 1"


def _non_negative(value: int) -> str | None:
    return None if value >= 0 else "must not be negative"


# --- Defaults ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class NamingDefaults:
    """How column names are conformed."""

    case: Literal["snake", "lower", "upper", "preserve"] = _doc(
        "snake splits camelCase and lowercases; lower and upper only change case.",
        default="snake",
    )
    split_camel: bool = _doc("customerID -> customer_id; HTTPServer -> http_server.", default=True)
    ascii: Literal["transliterate", "strip", "keep"] = _doc(
        "transliterate with the bundled table (ADR-0012), strip non-ASCII, or keep it.",
        default="transliterate",
    )
    replace_invalid: str = _doc(
        "Replacement for characters outside [a-z0-9_] after casing.", default="_"
    )
    collapse: bool = _doc("Collapse runs of '_' and trim it from both ends.", default=True)
    leading_digit: Literal["prefix", "letter", "error"] = _doc(
        "prefix '_', letter (SDK style: 0 -> a), or error.", default="prefix"
    )
    max_length: int = _doc(
        "Longer names are truncated (see truncate).",
        default=63,
        metadata={"check": _positive},
    )
    truncate: Literal["hash", "error"] = _doc(
        "hash keeps the head plus '_' and 6 hex digits of a hash of the full name.",
        default="hash",
    )
    reserved_words: Literal["suffix", "prefix", "error", "ignore"] = _doc(
        "What to do with a reserved word: suffix '_', prefix '_', error or ignore.",
        default="suffix",
    )
    reserved_dialects: tuple[Dialect, ...] = _doc(
        "Reserved-word lists to union.", default=("ansi", "postgres", "duckdb")
    )
    on_collision: Literal["error", "suffix"] = _doc(
        "Two names conforming to the same output: error, or add _2, _3, ...", default="error"
    )
    nested: bool = _doc("Also conform the member names of struct columns.", default=True)


@dataclass(frozen=True)
class StreamNaming:
    """How stream names are conformed."""

    name: Literal["conform", "preserve"] = _doc(
        "Conform stream names like column names, or keep them.", default="conform"
    )
    prefix: str = _doc("Added after conforming.", default="")
    split: str | None = _doc(
        "Emit only the part after the last occurrence of this separator.", default=None
    )


@dataclass(frozen=True)
class ValuesDefaults:
    """Value cleanup applied before casting."""

    trim: bool = _doc("Trim surrounding whitespace from strings.", default=True)
    null_tokens: tuple[str, ...] = _doc(
        "Strings that mean null.",
        default=("", "NULL", "null", "N/A", "n/a", "#N/A", "NaN", "-"),
    )
    null_tokens_case_sensitive: bool = _doc("Match null tokens case-sensitively.", default=False)
    empty_string_for_string: Literal["keep", "null"] = _doc(
        'What "" becomes in a string column.', default="keep"
    )


@dataclass(frozen=True)
class TimestampDefaults:
    """Defaults for temporal casts."""

    assume_tz: str = _doc("Time zone of naive input cast to timestamptz.", default="UTC")
    output_precision: Literal["s", "ms", "us"] = _doc(
        "Fractional precision on output.", default="us"
    )
    formats: tuple[str, ...] = _doc(
        "Formats tried in order: strftime patterns, iso, excel_serial, epoch_*, rfc2822.",
        default=("iso",),
    )


@dataclass(frozen=True)
class BooleanDefaults:
    """Words that cast to booleans (case-insensitive unless the cast says otherwise)."""

    true_values: tuple[str, ...] = _doc(
        "Strings that mean true.", default=("true", "t", "yes", "y", "1", "on")
    )
    false_values: tuple[str, ...] = _doc(
        "Strings that mean false.", default=("false", "f", "no", "n", "0", "off")
    )


@dataclass(frozen=True)
class FlattenDefaults:
    """Singer SDK flattening semantics, for nested: flatten."""

    separator: str = _doc("Joins parent and child keys.", default="__")
    max_depth: int = _doc(
        "Levels of nesting to flatten.", default=1, metadata={"check": _non_negative}
    )
    max_key_length: int = _doc("Longest flattened key.", default=255, metadata={"check": _positive})


@dataclass(frozen=True)
class FakerDefaults:
    """Settings for the fake builtin (needs the faker extra)."""

    seed: int | None = _doc("Seed for reproducible fake values.", default=None)
    locale: str | tuple[str, ...] | None = _doc("Faker locale or locales.", default=None)


@dataclass(frozen=True)
class Defaults:
    """Settings inherited by every stream. A stream may override any of them."""

    naming: NamingDefaults = _doc("Column naming.", default_factory=NamingDefaults)
    stream: StreamNaming = _doc("Stream naming.", default_factory=StreamNaming)
    values: ValuesDefaults = _doc("Value cleanup.", default_factory=ValuesDefaults)
    timestamp: TimestampDefaults = _doc("Temporal casts.", default_factory=TimestampDefaults)
    boolean: BooleanDefaults = _doc("Boolean casts.", default_factory=BooleanDefaults)
    on_error: OnError = _doc(
        "What a failed cast or transform does: raise, null, keep the raw value, or reject the "
        "row to the dead-letter sink.",
        default="raise",
    )
    metadata: Literal["sdc", "none"] = _doc(
        "Add the seven Singer SDK _sdc_* columns.", default="sdc"
    )
    undeclared: Literal["conform", "drop", "error"] = _doc(
        "Columns the spec does not mention: conform them from the tap SCHEMA, drop them, or fail.",
        default="conform",
    )
    nested: Literal["json", "flatten", "keep"] = _doc(
        "Undeclared object and array columns: JSON text, flattened, or typed struct/list.",
        default="json",
    )
    flatten: FlattenDefaults = _doc("Flattening settings.", default_factory=FlattenDefaults)
    faker: FakerDefaults = _doc("Fake data settings.", default_factory=FakerDefaults)


# --- Columns and streams ------------------------------------------------------------------------


@dataclass(frozen=True)
class ExprRef:
    """A value computed by an expression."""

    expr: str = _doc("The expression.")


@dataclass(frozen=True)
class FieldSpec:
    """Transforms on a nested member of a struct or json column, by dotted path."""

    transform: Chain | None = _doc("Steps applied to the member.", default=None)
    when: str | None = _doc("Apply only where this expression is truthy.", default=None)
    drop: bool = _doc("Remove the member.", default=False)


@dataclass(frozen=True)
class ColumnSpec:
    """One output column. Unset keys inherit from the stream's defaults or the tap SCHEMA."""

    name: str | None = _doc("Output name. It is checked, never silently conformed.", default=None)
    type: str | None = _doc(
        "Declared CType, e.g. int64, decimal(18,2), timestamptz. From the tap SCHEMA if absent.",
        default=None,
        metadata={"check": ctype_problem},
    )
    nullable: bool = _doc("If false, a null is an error under on_error.", default=True)
    source: str | tuple[str, ...] | None = _doc(
        "Source column(s) if not the key; a list coalesces in order.", default=None
    )
    expr: str | None = _doc("Derived value. Without source, it creates a new column.", default=None)
    default: Any = _doc("Used when the value is missing or null after transforms.", default=None)
    transform: Chain | None = _doc("Steps run before the implicit cast.", default=None)
    parse: Mapping[str, Any] | None = _doc(
        "Keyword arguments for the implicit cast, e.g. {formats: [...], tz: ...}.", default=None
    )
    true_values: tuple[str, ...] | None = _doc("Overrides boolean.true_values.", default=None)
    false_values: tuple[str, ...] | None = _doc("Overrides boolean.false_values.", default=None)
    null_tokens: tuple[str, ...] | None = _doc("Overrides values.null_tokens.", default=None)
    trim: bool | None = _doc("Overrides values.trim.", default=None)
    on_error: OnError | None = _doc("Overrides on_error.", default=None)
    max_length: int | None = _doc(
        "Longest string allowed.", default=None, metadata={"check": _positive}
    )
    on_overflow: Literal["truncate", "error"] = _doc(
        "What a string longer than max_length does.", default="error"
    )
    enum: tuple[Any, ...] | None = _doc("Allowed values, checked after the cast.", default=None)
    drop: bool = _doc("Remove the column. Dropping a key property is an error.", default=False)
    doc: str | None = _doc("Copied to the SCHEMA description.", default=None)
    sql_type: str | None = _doc("Overrides the emitted x-sql-datatype hint.", default=None)
    when: str | None = _doc(
        "Apply the chain only to rows where this is truthy; sees conformed names.", default=None
    )
    fields: Mapping[str, FieldSpec] | None = _doc(
        "Transforms on nested members of struct and json columns, by dotted path.",
        default=None,
    )


@dataclass(frozen=True)
class StreamSpec:
    """A stream's own keys. Defaults keys set on the stream are merged into its Defaults."""

    alias: str | ExprRef | None = _doc(
        "Final stream name; bypasses stream naming and prefix.", default=None
    )
    source: str | None = _doc(
        "Make this key a new output stream projected from this tap stream (split or copy).",
        default=None,
    )
    prefix: str | None = _doc("Overrides stream.prefix.", default=None)
    key_properties: tuple[str, ...] | None = _doc(
        "Overrides the tap's key properties; source or conformed names.", default=None
    )
    filter: str | None = _doc(
        "Rows where this expression is falsy are dropped; sees conformed names.", default=None
    )
    columns: Mapping[str, ColumnSpec] = _doc(
        "Columns by source name, or by new name for derived columns.", default_factory=_empty
    )
    order: Literal["source", "declared"] = _doc(
        "Output column order: the tap's, or the order of columns here.", default="source"
    )
    drop: bool = _doc("Drop the whole stream.", default=False)


STREAM_KEYS = frozenset({"alias", "source", "prefix", "key_properties", "filter", "columns",
                         "order", "drop"})  # fmt: skip
DEFAULTS_KEYS = frozenset({"naming", "stream", "values", "timestamp", "boolean", "on_error",
                           "metadata", "undeclared", "nested", "flatten", "faker"})  # fmt: skip


@dataclass(frozen=True)
class StreamRules:
    """A ``streams`` entry: its parsed StreamSpec, and its raw mapping for inheritance."""

    raw: Mapping[str, Any]
    spec: StreamSpec

    @classmethod
    def spec_parse(cls, data: object, path: str, issues: Issues) -> StreamRules | Any:  # noqa: ANN401
        """Validate StreamSpec keys and any Defaults keys the stream overrides."""
        if not isinstance(data, dict):
            issues.add(path, "expected a mapping of stream rules")
            return INVALID
        own = {k: v for k, v in data.items() if k in STREAM_KEYS}
        overrides = {k: v for k, v in data.items() if k in DEFAULTS_KEYS}
        allowed = ", ".join(sorted(STREAM_KEYS | DEFAULTS_KEYS))
        unknown = [k for k in data if k not in STREAM_KEYS | DEFAULTS_KEYS]
        for key in unknown:
            issues.add(child(path, str(key)), f"unknown key; allowed here: {allowed}")
        spec = parse_dataclass(StreamSpec, own, path, issues)
        checked = parse_dataclass(Defaults, overrides, path, issues)
        if unknown or not isinstance(spec, StreamSpec) or checked is INVALID:
            return INVALID
        return cls(freeze_mapping(data), spec)

    def spec_dump(self) -> object:
        """The mapping as written."""
        return thaw(self.raw)

    @classmethod
    def spec_schema(cls, defs: dict[str, Any]) -> dict[str, Any]:
        """StreamSpec properties plus every Defaults property, without defaults (inherited)."""
        if "StreamRules" not in defs:
            dataclass_schema(StreamSpec, defs)
            dataclass_schema(Defaults, defs)
            inherited = {
                key: {k: v for k, v in prop.items() if k != "default"}
                for key, prop in defs["Defaults"]["properties"].items()
            }
            defs["StreamRules"] = {
                "description": (
                    "Rules for the streams this key matches: StreamSpec keys plus any Defaults "
                    "key, which overrides the inherited value (objects merge, lists replace)."
                ),
                "type": "object",
                "additionalProperties": False,
                "properties": {**defs["StreamSpec"]["properties"], **inherited},
            }
        return {"$ref": "#/$defs/StreamRules"}


@dataclass(frozen=True)
class Spec:
    """A conform spec file, version 1."""

    version: Literal[1] = _doc("The spec version.")
    defaults: Defaults = _doc("Inherited by every stream.", default_factory=Defaults)
    macros: Mapping[str, Macro] = _doc(
        "Named, parameterised transform chains.", default_factory=_empty
    )
    udfs: Mapping[str, str] = _doc(
        "Python functions by name, as 'package.module:function'.",
        default_factory=_empty,
        metadata={"check": lambda m: next(filter(None, map(_udf_problem, m.values())), None)},
    )
    streams: Mapping[str, StreamRules] = _doc(
        "Per-stream rules: StreamSpec keys plus any Defaults key. A key is a glob over tap "
        "stream names, or a new stream name when the rules have source.",
        default_factory=_empty,
    )
    else_: Literal["keep", "drop"] = _doc(
        "Tap streams that match no key: keep (conform with the defaults) or drop.",
        default="keep",
        metadata={"key": "else"},
    )


def parse_spec(data: object, source: str | None = None) -> Spec:
    """Strictly parse spec data (already substituted and merged with any inline spec).

    Raises:
        SpecError: listing every problem found, each with its path.
    """
    issues = Issues()
    spec = parse_dataclass(Spec, data, "", issues)
    if issues or not isinstance(spec, Spec):
        raise SpecError(issues.items, source)
    return spec
