"""The Transform protocol and the builtin registry (detailed design §6).

A transform is a name, a frozen kwargs dataclass (validated at plan compile time by the same
strict parser as the spec), the types it accepts and produces, and a scalar function. An
optional Arrow function marks it vectorisable for the columnar executor.

Types are tracked through a chain as a *stage*: ``None`` means the raw value from the tap,
before the cast; otherwise it is the CType the value has at that point. A step's ``accepts``
lists kinds, plus ``"raw"`` for steps that may run before the cast.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from map_conform.spec.model import ColumnSpec, Defaults
from map_conform.types.canonical import CType

if TYPE_CHECKING:
    from _typeshed import DataclassInstance  # noqa: TC004 -- typing only

RAW = "raw"
ANY = "any"
NUMERIC = frozenset({"int16", "int32", "int64", "float32", "float64", "decimal"})
TEMPORAL = frozenset({"date", "time", "timestamp", "timestamptz"})


@dataclass(frozen=True)
class Context:
    """What a step knows about the value it is working on."""

    stream: str
    column: str
    settings: Defaults
    target: CType
    """The column's declared output type."""
    row: int | None = None


@dataclass(frozen=True)
class NoKwargs:
    """For transforms that take no keyword arguments."""


@dataclass(frozen=True)
class Transform:
    """One builtin step."""

    name: str
    scalar: Callable[[Any, Any, Context], Any]
    """``(value, kwargs, ctx) -> value``; raises :class:`~map_conform.errors.StepFailed`."""
    kwargs: type[DataclassInstance] = NoKwargs
    accepts: frozenset[str] = frozenset({RAW, "string"})
    produces: Callable[[CType | None, Any], CType | None] | None = None
    """``(input stage, kwargs) -> output stage``; None keeps the input stage."""
    positional: str | None = None
    """The kwarg a scalar step argument fills, e.g. ``chars`` for ``{strip_chars: "$, "}``."""
    arrow: Callable[..., Any] | None = None
    doc: str = ""
    null_safe: bool = False
    """True when the step must see nulls; otherwise nulls pass through untouched."""
    defaults: Callable[[Defaults, ColumnSpec | None], dict[str, Any]] | None = None
    """For casts: kwargs taken from the stream defaults and column overrides."""
    forces_nullable: bool = False
    """The step can produce null whatever the input (set_null), so the column is nullable."""

    @property
    def vectorised(self) -> bool:
        """Whether the columnar executor can run this step on whole arrays."""
        return self.arrow is not None

    def accepts_stage(self, stage: CType | None) -> bool:
        """Whether a value at ``stage`` may enter this step."""
        if ANY in self.accepts:
            return True
        if stage is None:
            return RAW in self.accepts
        return stage.kind in self.accepts

    def output_stage(self, stage: CType | None, kwargs: object) -> CType | None:
        """The stage after this step."""
        return stage if self.produces is None else self.produces(stage, kwargs)


@dataclass
class Registry:
    """Builtins by name. Casts are registered per target kind."""

    transforms: dict[str, Transform] = field(default_factory=dict)
    casts: dict[str, Transform] = field(default_factory=dict)

    def register(self, transform: Transform) -> Transform:
        """Add a builtin; names are unique."""
        if transform.name in self.transforms or transform.name == "cast":
            msg = f"a transform named {transform.name!r} is already registered"
            raise ValueError(msg)
        self.transforms[transform.name] = transform
        return transform

    def register_cast(self, kinds: frozenset[str] | set[str], transform: Transform) -> None:
        """Add the caster for these target kinds."""
        for kind in kinds:
            if kind in self.casts:
                msg = f"a cast to {kind!r} is already registered"
                raise ValueError(msg)
            self.casts[kind] = transform

    def names(self) -> Mapping[str, Transform]:
        """Every registered builtin."""
        return self.transforms
