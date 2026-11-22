"""Compile a column's transform chain (detailed design §3.4, §9).

Compilation resolves each step to a builtin or a macro, validates its kwargs with the spec's
strict parser, and tracks the value's type through the chain: it starts *raw* (the tap's
value) and must end as the column's declared type. A chain without a ``cast`` gets one
appended, configured from the stream defaults, the column's overrides and its ``parse``.
Every problem is recorded with its spec path; nothing is checked again at run time.
"""

from __future__ import annotations

import dataclasses
import json
import re
import typing
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from map_conform.errors import CellError, StepFailed
from map_conform.spec._struct import (
    INVALID,
    Invalid,
    Issues,
    child,
    parse_dataclass,
    thaw,
    thaw_mapping,
)
from map_conform.spec.model import Defaults
from map_conform.spec.steps import CallStep, CaseStep, Chain, ExprStep, Macro
from map_conform.transforms.registry import Registry, Transform
from map_conform.types.canonical import CType, CTypeError, parse_ctype

if TYPE_CHECKING:
    from map_conform.spec.model import ColumnSpec
    from map_conform.transforms.registry import Context

_PARAM = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_NEEDS_EXPR = "needs the expression language, which is not built yet (WBS 6.x)"


@dataclass(frozen=True)
class CastArgs:
    """A cast step's arguments: its target type and its validated options."""

    target: CType
    options: Any


@dataclass(frozen=True)
class CompiledStep:
    """One resolved, validated step."""

    transform: Transform
    kwargs: Any
    rule: str
    """How errors name the step, e.g. ``strip_chars`` or ``cast: decimal(10,2)``."""


class StepError(Exception):
    """A step failed on a value; ``cell`` says which and why."""

    def __init__(self, cell: CellError) -> None:
        """Keep the failure."""
        self.cell = cell
        super().__init__(f"{cell.rule}: {cell.reason}")


@dataclass(frozen=True)
class CompiledChain:
    """A column's steps, ending as its declared type."""

    steps: tuple[CompiledStep, ...]
    target: CType

    def run(self, value: object, ctx: Context) -> object:
        """Apply the steps to one value. Nulls skip steps that are not null-safe.

        Raises:
            StepError: naming the failed step and the reason.
        """
        for step in self.steps:
            if value is None and not step.transform.null_safe:
                continue
            try:
                value = step.transform.scalar(value, step.kwargs, ctx)
            except StepFailed as exc:
                raise StepError(CellError(step.rule, exc.reason)) from exc
        return value


@dataclass
class ChainCompiler:
    """Compiles chains for one stream: its settings, macros and the builtin registry."""

    registry: Registry
    settings: Defaults
    macros: Mapping[str, Macro]
    issues: Issues

    def compile(
        self,
        chain: Chain | None,
        column: ColumnSpec | None,
        target: CType,
        path: str,
    ) -> CompiledChain | None:
        """Compile a column's chain; None when it had problems (recorded in ``issues``)."""
        before = len(self.issues.items)
        steps: list[CompiledStep] = []
        stage: CType | None = None
        cast_seen = False
        for step, step_path in self._expand(chain, child(path, "transform"), ()):
            compiled = self._step(step, column, target, stage, step_path)
            if compiled is None:
                continue
            item, stage = compiled
            cast_seen = cast_seen or isinstance(item.kwargs, CastArgs)
            steps.append(item)
        if len(self.issues.items) != before:
            return None  # a failed step makes any further type error a consequence of it
        if not cast_seen and stage != target:
            implicit = self._cast(
                arg=None,
                extra={},
                column=column,
                target=target,
                stage=stage,
                path=child(path, "transform"),
            )
            if implicit is not None:
                steps.append(implicit)
                stage = target
        if stage != target and len(self.issues.items) == before:
            self.issues.add(
                child(path, "transform"),
                f"the chain ends as {_stage(stage)}, but the column is {target}",
            )
        if len(self.issues.items) != before:
            return None
        return CompiledChain(tuple(steps), target)

    # --- expansion ----------------------------------------------------------------------

    def _expand(
        self, chain: Chain | None, base: str, stack: tuple[str, ...]
    ) -> list[tuple[CallStep, str]]:
        """Flatten a chain into call steps with their paths, expanding macros in place."""
        if chain is None:
            return []
        out: list[tuple[CallStep, str]] = []
        many = len(chain.steps) > 1
        for i, step in enumerate(chain.steps):
            step_path = child(base, i) if many else base
            if isinstance(step, (ExprStep, CaseStep)) or step.when is not None:
                kind = (
                    "an expr step"
                    if isinstance(step, ExprStep)
                    else ("a case step" if isinstance(step, CaseStep) else "'when'")
                )
                self.issues.add(step_path, f"{kind} {_NEEDS_EXPR}")
                continue
            if step.name in self.macros:
                out.extend(self._expand_macro(step, step_path, stack))
            else:
                out.append((step, step_path))
        return out

    def _expand_macro(
        self, step: CallStep, path: str, stack: tuple[str, ...]
    ) -> list[tuple[CallStep, str]]:
        if step.name in stack:
            cycle = " -> ".join((*stack, step.name))
            self.issues.add(path, f"macro cycle: {cycle}")
            return []
        macro = self.macros[step.name]
        params = thaw_mapping(macro.params)
        given = thaw_mapping(step.arg) if isinstance(step.arg, Mapping) else {}
        given.update(thaw_mapping(step.kwargs))
        if step.arg is not None and not isinstance(step.arg, Mapping):
            self.issues.add(path, f"macro {step.name!r} takes named parameters, not a value")
            return []
        unknown = sorted(set(given) - set(params))
        if unknown:
            self.issues.add(path, f"macro {step.name!r} has no parameter {', '.join(unknown)}")
            return []
        params.update(given)
        raw = _fill(macro.steps.spec_dump(), params)
        expanded = Chain.spec_parse(raw, child(child("macros", step.name), "steps"), self.issues)
        if not isinstance(expanded, Chain):
            return []
        # Steps inside a macro report at its definition, where they would be fixed.
        definition = child(child("macros", step.name), "steps")
        return self._expand(expanded, definition, (*stack, step.name))

    # --- steps --------------------------------------------------------------------------

    def _step(
        self,
        step: CallStep,
        column: ColumnSpec | None,
        target: CType,
        stage: CType | None,
        path: str,
    ) -> tuple[CompiledStep, CType | None] | None:
        if step.name == "cast":
            compiled = self._cast(
                arg=step.arg,
                extra=step.kwargs,
                column=column,
                target=target,
                stage=stage,
                path=path,
            )
            return None if compiled is None else (compiled, compiled.kwargs.target)
        transform = self.registry.transforms.get(step.name)
        if transform is None:
            self.issues.add(path, f"unknown step {step.name!r}: not a builtin or a macro")
            return None
        if not transform.accepts_stage(stage):
            self.issues.add(path, f"{step.name} cannot take {_stage(stage)} here")
            return None
        kwargs = self._kwargs(transform, step.arg, step.kwargs, path)
        if isinstance(kwargs, Invalid):
            return None
        return CompiledStep(transform, kwargs, step.name), transform.output_stage(stage, kwargs)

    def _kwargs(
        self, transform: Transform, arg: object, extra: Mapping[str, Any], path: str
    ) -> Any:  # noqa: ANN401 -- the transform's own kwargs dataclass
        data: dict[str, Any] = {}
        if isinstance(arg, Mapping) and not _positional_takes_mapping(transform, arg):
            data.update(thaw_mapping(arg))  # {hash: {algo: md5}}: keyword arguments
        elif arg is not None:
            if transform.positional is None:
                self.issues.add(path, f"{transform.name} takes keyword arguments only")
                return INVALID
            data[transform.positional] = thaw(arg)
        data.update(thaw_mapping(extra))
        return parse_dataclass(transform.kwargs, data, path, self.issues)

    def _cast(  # noqa: PLR0913 -- the cast's full context
        self,
        *,
        arg: object,
        extra: Mapping[str, Any],
        column: ColumnSpec | None,
        target: CType,
        stage: CType | None,
        path: str,
    ) -> CompiledStep | None:
        cast_target = self._cast_target(arg, target, path)
        if cast_target is None:
            return None
        caster = self.registry.casts.get(cast_target.kind)
        if caster is None:
            self.issues.add(path, f"there is no cast to {cast_target.kind} yet")
            return None
        if not caster.accepts_stage(stage):
            self.issues.add(path, f"cast to {cast_target} cannot take {_stage(stage)}")
            return None
        data = caster.defaults(self.settings, column) if caster.defaults else {}
        if column is not None and column.parse:
            data.update(thaw_mapping(column.parse))
        data.update(thaw_mapping(extra))
        options = parse_dataclass(caster.kwargs, data, path, self.issues)
        if isinstance(options, Invalid):
            return None
        return CompiledStep(caster, CastArgs(cast_target, options), f"cast: {cast_target}")

    def _cast_target(self, arg: object, target: CType, path: str) -> CType | None:
        if arg is None:
            return target
        if not isinstance(arg, str):
            self.issues.add(path, "cast takes a type name, e.g. {cast: decimal}")
            return None
        if arg == target.kind:  # {cast: decimal} on a decimal(18,2) column
            return target
        try:
            return parse_ctype(arg)
        except CTypeError as exc:
            self.issues.add(path, str(exc))
            return None


def _positional_takes_mapping(transform: Transform, arg: Mapping[str, Any]) -> bool:
    """Whether a mapping argument is the positional value, as in ``{map_values: {Y: yes}}``.

    That is so only when the positional kwarg is itself a mapping and the argument's keys are
    not all kwarg names (``{map_values: {values: {...}, default: x}}`` is keyword arguments).
    """
    if transform.positional is None:
        return False
    hints = typing.get_type_hints(transform.kwargs)
    if typing.get_origin(hints[transform.positional]) not in (Mapping, dict):
        return False
    return not set(arg) <= {f.name for f in dataclasses.fields(transform.kwargs)}


def _stage(stage: CType | None) -> str:
    return "the raw value" if stage is None else f"a {stage} value"


def _fill(data: object, params: Mapping[str, object]) -> object:
    """Substitute macro parameters into a macro's steps."""
    if isinstance(data, dict):
        return {k: _fill(v, params) for k, v in data.items()}
    if isinstance(data, list):
        return [_fill(v, params) for v in data]
    if isinstance(data, str):
        whole = _PARAM.fullmatch(data)
        if whole and whole.group(1) in params:
            return params[whole.group(1)]
        return _PARAM.sub(
            lambda m: _text(params[m.group(1)]) if m.group(1) in params else m.group(0), data
        )
    return data


def _text(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value)
