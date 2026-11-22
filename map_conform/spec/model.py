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
from dataclasses import dataclass
from typing import Any, Literal

from map_conform.spec._struct import (
    INVALID,
    Issues,
    child,
    dataclass_schema,
    documented,
    empty_mapping,
    freeze_mapping,
    non_negative,
    parse_dataclass,
    positive,
    thaw,
)
from map_conform.spec.errors import SpecError
from map_conform.spec.steps import Chain, Macro
from map_conform.types.canonical import ctype_problem

OnError = Literal["raise", "null", "keep", "reject"]
Dialect = Literal["postgres", "duckdb", "snowflake", "ansi"]

_NULL_POLICY_HINT = (
    "YAML reads a bare null as 'no value'; to choose the null policy, quote it: on_error: \"null\""
)
_UDF_TARGET = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")


MIN_NAME_LENGTH = 8
"""Room for at least one character, '_' and a 6-hex hash suffix."""


def _name_length(value: int) -> str | None:
    return None if value >= MIN_NAME_LENGTH else f"must be at least {MIN_NAME_LENGTH}"


def _udf_problem(target: str) -> str | None:
    return None if _UDF_TARGET.match(target) else "expected 'package.module:function'"


# --- Defaults ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class NamingDefaults:
    """How column names are conformed."""

    case: Literal["snake", "lower", "upper", "preserve"] = documented(
        "snake splits camelCase and lowercases; lower and upper only change case.",
        default="snake",
    )
    split_camel: bool = documented(
        "customerID -> customer_id; HTTPServer -> http_server.", default=True
    )
    ascii: Literal["transliterate", "strip", "keep"] = documented(
        "transliterate with the bundled table (ADR-0012), strip non-ASCII, or keep it.",
        default="transliterate",
    )
    replace_invalid: str = documented(
        "Replacement for characters outside [a-z0-9_] after casing.", default="_"
    )
    collapse: bool = documented("Collapse runs of '_' and trim it from both ends.", default=True)
    leading_digit: Literal["prefix", "letter", "error"] = documented(
        "prefix '_', letter (SDK style: 0 -> a), or error.", default="prefix"
    )
    max_length: int = documented(
        "Longer names are truncated (see truncate). At least 8, room for a hash suffix.",
        default=63,
        metadata={"check": _name_length},
    )
    truncate: Literal["hash", "error"] = documented(
        "hash keeps the head plus '_' and 6 hex digits of a hash of the full name.",
        default="hash",
    )
    reserved_words: Literal["suffix", "prefix", "error", "ignore"] = documented(
        "What to do with a reserved word: suffix '_', prefix '_', error or ignore.",
        default="suffix",
    )
    reserved_dialects: tuple[Dialect, ...] = documented(
        "Reserved-word lists to union. ansi (SQL:2016) is opt-in: it reserves common column "
        "names such as date, year and value.",
        default=("postgres", "duckdb", "snowflake"),
    )
    on_collision: Literal["error", "suffix"] = documented(
        "Two names conforming to the same output: error, or add _2, _3, ...", default="error"
    )
    nested: bool = documented("Also conform the member names of struct columns.", default=True)


@dataclass(frozen=True)
class StreamNaming:
    """How stream names are conformed."""

    name: Literal["conform", "preserve"] = documented(
        "Conform stream names like column names, or keep them.", default="conform"
    )
    prefix: str = documented("Added after conforming.", default="")
    split: str | None = documented(
        "Emit only the part after the last occurrence of this separator.", default=None
    )


@dataclass(frozen=True)
class ValuesDefaults:
    """Value cleanup applied before casting."""

    trim: bool = documented("Trim surrounding whitespace from strings.", default=True)
    null_tokens: tuple[str, ...] = documented(
        "Strings that mean null.",
        default=("", "NULL", "null", "N/A", "n/a", "#N/A", "NaN", "-"),
    )
    null_tokens_case_sensitive: bool = documented(
        "Match null tokens case-sensitively.", default=False
    )
    empty_string_for_string: Literal["keep", "null"] = documented(
        'What "" becomes in a string column.', default="keep"
    )


@dataclass(frozen=True)
class TimestampDefaults:
    """Defaults for temporal casts."""

    assume_tz: str = documented("Time zone of naive input cast to timestamptz.", default="UTC")
    output_precision: Literal["s", "ms", "us"] = documented(
        "Fractional precision on output.", default="us"
    )
    formats: tuple[str, ...] = documented(
        "Formats tried in order: strftime patterns, iso, excel_serial, epoch_*, rfc2822.",
        default=("iso",),
    )


@dataclass(frozen=True)
class BooleanDefaults:
    """Words that cast to booleans (case-insensitive unless the cast says otherwise)."""

    true_values: tuple[str, ...] = documented(
        "Strings that mean true.", default=("true", "t", "yes", "y", "1", "on")
    )
    false_values: tuple[str, ...] = documented(
        "Strings that mean false.", default=("false", "f", "no", "n", "0", "off")
    )


@dataclass(frozen=True)
class FlattenDefaults:
    """Singer SDK flattening semantics, for nested: flatten."""

    separator: str = documented("Joins parent and child keys.", default="__")
    max_depth: int = documented(
        "Levels of nesting to flatten.", default=1, metadata={"check": non_negative}
    )
    max_key_length: int = documented(
        "Longest flattened key.", default=255, metadata={"check": positive}
    )


@dataclass(frozen=True)
class FakerDefaults:
    """Settings for the fake builtin (needs the faker extra)."""

    seed: int | None = documented("Seed for reproducible fake values.", default=None)
    locale: str | tuple[str, ...] | None = documented("Faker locale or locales.", default=None)


@dataclass(frozen=True)
class Defaults:
    """Settings inherited by every stream. A stream may override any of them."""

    naming: NamingDefaults = documented("Column naming.", default_factory=NamingDefaults)
    stream: StreamNaming = documented("Stream naming.", default_factory=StreamNaming)
    values: ValuesDefaults = documented("Value cleanup.", default_factory=ValuesDefaults)
    timestamp: TimestampDefaults = documented("Temporal casts.", default_factory=TimestampDefaults)
    boolean: BooleanDefaults = documented("Boolean casts.", default_factory=BooleanDefaults)
    on_error: OnError = documented(
        "What a failed cast or transform does: raise, null, keep the raw value, or reject the "
        "row to the dead-letter sink.",
        default="raise",
        metadata={"null_hint": _NULL_POLICY_HINT},
    )
    metadata: Literal["sdc", "none"] = documented(
        "Add the seven Singer SDK _sdc_* columns.", default="sdc"
    )
    undeclared: Literal["conform", "drop", "error"] = documented(
        "Columns the spec does not mention: conform them from the tap SCHEMA, drop them, or fail.",
        default="conform",
    )
    nested: Literal["json", "flatten", "keep"] = documented(
        "Undeclared object and array columns: JSON text, flattened, or typed struct/list.",
        default="json",
    )
    flatten: FlattenDefaults = documented("Flattening settings.", default_factory=FlattenDefaults)
    faker: FakerDefaults = documented("Fake data settings.", default_factory=FakerDefaults)


# --- Columns and streams ------------------------------------------------------------------------


@dataclass(frozen=True)
class ExprRef:
    """A value computed by an expression."""

    expr: str = documented("The expression.")


@dataclass(frozen=True)
class FieldSpec:
    """Transforms on a nested member of a struct or json column, by dotted path."""

    transform: Chain | None = documented("Steps applied to the member.", default=None)
    when: str | None = documented("Apply only where this expression is truthy.", default=None)
    drop: bool = documented("Remove the member.", default=False)


@dataclass(frozen=True)
class ColumnSpec:
    """One output column. Unset keys inherit from the stream's defaults or the tap SCHEMA."""

    name: str | None = documented(
        "Output name. It is checked, never silently conformed.", default=None
    )
    type: str | None = documented(
        "Declared CType, e.g. int64, decimal(18,2), timestamptz. From the tap SCHEMA if absent.",
        default=None,
        metadata={"check": ctype_problem},
    )
    nullable: bool = documented("If false, a null is an error under on_error.", default=True)
    source: str | tuple[str, ...] | None = documented(
        "Source column(s) if not the key; a list coalesces in order.", default=None
    )
    expr: str | None = documented(
        "Derived value. Without source, it creates a new column.", default=None
    )
    default: Any = documented(
        "Used when the value is missing or null after transforms.", default=None
    )
    transform: Chain | None = documented("Steps run before the implicit cast.", default=None)
    parse: Mapping[str, Any] | None = documented(
        "Keyword arguments for the implicit cast, e.g. {formats: [...], tz: ...}.", default=None
    )
    true_values: tuple[str, ...] | None = documented("Overrides boolean.true_values.", default=None)
    false_values: tuple[str, ...] | None = documented(
        "Overrides boolean.false_values.", default=None
    )
    null_tokens: tuple[str, ...] | None = documented("Overrides values.null_tokens.", default=None)
    trim: bool | None = documented("Overrides values.trim.", default=None)
    on_error: OnError | None = documented(
        "Overrides on_error.", default=None, metadata={"null_hint": _NULL_POLICY_HINT}
    )
    max_length: int | None = documented(
        "Longest string allowed.", default=None, metadata={"check": positive}
    )
    on_overflow: Literal["truncate", "error"] = documented(
        "What a string longer than max_length does.", default="error"
    )
    enum: tuple[Any, ...] | None = documented(
        "Allowed values, checked after the cast.", default=None
    )
    drop: bool = documented(
        "Remove the column. Dropping a key property is an error.", default=False
    )
    doc: str | None = documented("Copied to the SCHEMA description.", default=None)
    sql_type: str | None = documented("Overrides the emitted x-sql-datatype hint.", default=None)
    when: str | None = documented(
        "Apply the chain only to rows where this is truthy; sees conformed names.", default=None
    )
    fields: Mapping[str, FieldSpec] | None = documented(
        "Transforms on nested members of struct and json columns, by dotted path.",
        default=None,
    )


@dataclass(frozen=True)
class StreamSpec:
    """A stream's own keys. Defaults keys set on the stream are merged into its Defaults."""

    alias: str | ExprRef | None = documented(
        "Final stream name; bypasses stream naming and prefix.", default=None
    )
    source: str | None = documented(
        "Make this key a new output stream projected from this tap stream (split or copy).",
        default=None,
    )
    prefix: str | None = documented("Overrides stream.prefix.", default=None)
    key_properties: tuple[str, ...] | None = documented(
        "Overrides the tap's key properties; source or conformed names.", default=None
    )
    filter: str | None = documented(
        "Rows where this expression is falsy are dropped; sees conformed names.", default=None
    )
    columns: Mapping[str, ColumnSpec] = documented(
        "Columns by source name, or by new name for derived columns.", default_factory=empty_mapping
    )
    order: Literal["source", "declared"] = documented(
        "Output column order: the tap's, or the order of columns here.", default="source"
    )
    drop: bool = documented("Drop the whole stream.", default=False)


STREAM_KEYS = frozenset(
    {"alias", "source", "prefix", "key_properties", "filter", "columns", "order", "drop"}
)
DEFAULTS_KEYS = frozenset(
    {
        "naming",
        "stream",
        "values",
        "timestamp",
        "boolean",
        "on_error",
        "metadata",
        "undeclared",
        "nested",
        "flatten",
        "faker",
    }
)


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

    version: Literal[1] = documented("The spec version.")
    defaults: Defaults = documented("Inherited by every stream.", default_factory=Defaults)
    macros: Mapping[str, Macro] = documented(
        "Named, parameterised transform chains.", default_factory=empty_mapping
    )
    udfs: Mapping[str, str] = documented(
        "Python functions by name, as 'package.module:function'.",
        default_factory=empty_mapping,
        metadata={"check": lambda m: next(filter(None, map(_udf_problem, m.values())), None)},
    )
    streams: Mapping[str, StreamRules] = documented(
        "Per-stream rules: StreamSpec keys plus any Defaults key. A key is a glob over tap "
        "stream names, or a new stream name when the rules have source.",
        default_factory=empty_mapping,
    )
    else_: Literal["keep", "drop"] = documented(
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
