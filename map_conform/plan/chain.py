"""Compile a column's transform chain (detailed design §3.4, §7, §9).

Compilation resolves each step to a builtin, a macro, an ``expr`` or a ``case``, validates
kwargs with the spec's strict parser, compiles expressions, and tracks the value's type
through the chain as a *stage*: ``None`` is the raw tap value (or an expression's result),
otherwise the CType the value has. The chain must end as the column's declared type: when it
ends raw, or typed differently with no explicit cast, the implicit cast is appended,
configured from the stream defaults, the column's overrides and its ``parse``.

- A step with ``when`` must keep the value's type, since rows where it is false skip it.
  Before the cast this always holds: every row is raw afterwards, and the cast follows.
- A ``case`` whose branches end in different types gets the implicit cast at the end of each
  branch, so every row leaves it as the column's type.
- A column's ``expr`` is its first step; its ``when`` applies the whole chain only where it
  is truthy, and other rows get the implicit cast alone; ``fields`` run after the cast.

Every problem is recorded with its spec path; nothing is checked again at run time.
"""

from __future__ import annotations

import dataclasses
import json
import re
import typing
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from map_conform.errors import StepFailed
from map_conform.expr.compiler import ExprError, Expression, Names, compile_expr
from map_conform.expr.functions import FUNCTIONS
from map_conform.naming.shape import Shape
from map_conform.plan.ops import (
    CaseOp,
    CastArgs,
    CompiledChain,
    CompiledStep,
    ExprOp,
    FieldOp,
    FieldsOp,
    GuardedOp,
    Op,
    ShapeOp,
    StepError,
    path_segments,
)
from map_conform.spec._struct import (
    INVALID,
    Invalid,
    Issues,
    child,
    parse_dataclass,
    thaw,
    thaw_mapping,
)
from map_conform.spec.model import ColumnSpec, Defaults
from map_conform.spec.steps import CallStep, CaseStep, Chain, ExprStep, Macro
from map_conform.transforms.registry import Context, Registry
from map_conform.types.canonical import CType, CTypeError, parse_ctype

if TYPE_CHECKING:
    from map_conform.spec.model import FieldSpec
    from map_conform.spec.steps import Step
    from map_conform.transforms.registry import Transform

_PARAM = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_STRING = CType("string")


@dataclass(frozen=True)
class _Sequence:
    """Compiled ops, the stage they end at, and whether an explicit cast ran."""

    ops: tuple[Op, ...]
    stage: CType | None
    cast_seen: bool


@dataclass(frozen=True)
class _Context:
    """What the steps of one chain share."""

    column: ColumnSpec | None
    target: CType
    own: str | None
    column_expr: str | None = None
    """The spec path of the column's ``expr``, while its first step is still to compile."""


@dataclass
class ChainCompiler:
    """Compiles chains for one stream: its settings, macros, registry and expression scope."""

    registry: Registry
    settings: Defaults
    macros: Mapping[str, Macro]
    issues: Issues
    scope: Names = field(default_factory=Names)
    """Columns and constants expressions may use; ``own`` is set per column."""
    stream: str = ""

    def __post_init__(self) -> None:
        """Make builtins, casts and macros callable from expressions."""
        if "cast" in self.scope.functions:
            return  # already set up (a scratch copy made by dataclasses.replace)
        functions: dict[str, Any] = {
            name: _StepFunction(self, transform)
            for name, transform in self.registry.transforms.items()
            if name not in FUNCTIONS
        }
        functions["cast"] = _CastFunction(self)
        functions.update(self.scope.functions)
        self.scope = dataclasses.replace(self.scope, functions=MappingProxyType(functions))

    # --- columns ------------------------------------------------------------------------

    def compile_column(
        self, spec: ColumnSpec | None, target: CType, path: str, own: str | None = None
    ) -> CompiledChain | None:
        """A column's whole chain: ``expr``, ``transform``, the cast, ``fields`` and ``when``.

        Returns None when there were problems (recorded in ``issues``).
        """
        if spec is None:
            return self.compile(None, None, target, path, own=own)
        steps: list[Step] = []
        if spec.expr is not None:
            steps.append(ExprStep(spec.expr))
        if spec.transform is not None:
            steps.extend(spec.transform.steps)
        before = len(self.issues.items)
        full = self.compile(
            Chain(tuple(steps)) if steps else None,
            spec,
            target,
            path,
            own=own,
            column_expr=child(path, "expr") if spec.expr is not None else None,
        )
        if spec.fields is not None:
            fields = self._fields(spec, target, path, own)
            if full is not None and fields is not None:
                full = CompiledChain((*full.steps, fields), target)
        if spec.shape is not None and full is not None:  # first, on the source value
            shape = ShapeOp(Shape.of(thaw_mapping(spec.shape)), own or path)
            full = CompiledChain((shape, *full.steps), target)
        if full is None or len(self.issues.items) != before:
            return None
        if spec.when is None:
            return full
        when = self._expr(spec.when, child(path, "when"), own, target)
        otherwise = self.compile(None, spec, target, path, own=own)
        if when is None or otherwise is None:
            return None
        return CompiledChain((CaseOp(((when, full),), otherwise, label="when"),), target)

    def compile(  # noqa: PLR0913 -- the column context
        self,
        chain: Chain | None,
        column: ColumnSpec | None,
        target: CType,
        path: str,
        *,
        own: str | None = None,
        column_expr: str | None = None,
    ) -> CompiledChain | None:
        """Compile a chain ending as ``target``; None when it had problems."""
        before = len(self.issues.items)
        context = _Context(column, target, own, column_expr)
        seq = self._sequence(chain, child(path, "transform"), None, context, ())
        if seq is None or len(self.issues.items) != before:
            return None  # a failed step makes any further type error a consequence of it
        ops = list(seq.ops)
        stage = seq.stage
        if stage != target and (stage is None or not seq.cast_seen):
            implicit = self.cast_step(
                arg=None, extra={}, column=column, target=target, stage=stage,
                path=child(path, "transform"),
            )  # fmt: skip
            if implicit is None:
                return None
            ops.append(implicit)
            stage = target
        if stage != target:
            self.issues.add(
                child(path, "transform"),
                f"the chain ends as {_stage(stage)}, but the column is {target}",
            )
            return None
        return CompiledChain(tuple(ops), target)

    # --- sequences ----------------------------------------------------------------------

    def _sequence(
        self,
        chain: Chain | None,
        base: str,
        stage: CType | None,
        context: _Context,
        stack: tuple[str, ...],
    ) -> _Sequence | None:
        """Compile steps in order from ``stage``; None when any step failed."""
        if chain is None:
            return _Sequence((), stage, cast_seen=False)
        ops: list[Op] = []
        cast_seen = False
        ok = True
        many = len(chain.steps) > 1
        for i, step in enumerate(chain.steps):
            step_path = child(base, i) if many else base
            expr_at = child(step_path, "expr")
            if context.column_expr is not None:
                expr_at = step_path = context.column_expr  # the column's own expr
                context = dataclasses.replace(context, column_expr=None)
            compiled = self._step(step, step_path, expr_at, stage, context, stack)
            if compiled is None:
                ok = False
                continue
            ops.extend(compiled.ops)
            stage = compiled.stage
            cast_seen = cast_seen or compiled.cast_seen
        return _Sequence(tuple(ops), stage, cast_seen) if ok else None

    def _step(  # noqa: PLR0913, PLR0917 -- the step and where it sits
        self,
        step: Step,
        path: str,
        expr_at: str,
        stage: CType | None,
        context: _Context,
        stack: tuple[str, ...],
    ) -> _Sequence | None:
        seq: _Sequence | None
        if isinstance(step, ExprStep):
            expression = self._expr(step.expr, expr_at, context.own, context.target)
            seq = (
                None
                if expression is None
                else _Sequence((ExprOp(expression),), None, cast_seen=False)
            )
        elif isinstance(step, CaseStep):
            seq = self._case(step, path, stage, context, stack)
        elif step.name in self.macros:
            seq = self._macro(step, path, stage, context, stack)
        else:
            seq = self._call(step, path, stage, context)
        if seq is None or step.when is None:
            return seq
        when = self._expr(step.when, child(path, "when"), context.own, context.target)
        if when is None:
            return None
        if stage is not None and seq.stage != stage:
            self.issues.add(
                path,
                f"a step with 'when' must keep the value's type ({_stage(stage)} becomes "
                f"{_stage(seq.stage)}); use case, or put 'when' on the column",
            )
            return None
        # Before the cast, rows that skip the step stay raw, so the value is raw after it.
        return _Sequence((GuardedOp(when, seq.ops),), stage, cast_seen=False)

    def _call(  # noqa: PLR0911 -- one early return per problem
        self, step: CallStep, path: str, stage: CType | None, context: _Context
    ) -> _Sequence | None:
        if step.name == "cast":
            compiled = self.cast_step(
                arg=step.arg, extra=step.kwargs, column=context.column, target=context.target,
                stage=stage, path=path,
            )  # fmt: skip
            if compiled is None:
                return None
            return _Sequence((compiled,), compiled.kwargs.target, cast_seen=True)
        transform = self.registry.transforms.get(step.name)
        if transform is None:
            self.issues.add(path, f"unknown step {step.name!r}: not a builtin or a macro")
            return None
        if not transform.accepts_stage(stage):
            self.issues.add(path, f"{step.name} cannot take {_stage(stage)} here")
            return None
        kinds = transform.column_kinds
        if kinds is not None and context.target.kind not in kinds:
            self.issues.add(
                path,
                f"{step.name} works only in {', '.join(sorted(kinds))} columns, not "
                f"{context.target}; declare the column's type",
            )
            return None
        kwargs = self._kwargs(transform, step.arg, step.kwargs, path)
        if isinstance(kwargs, Invalid):
            return None
        out = transform.output_stage(stage, kwargs)
        return _Sequence((CompiledStep(transform, kwargs, step.name),), out, cast_seen=False)

    def _case(
        self,
        step: CaseStep,
        path: str,
        stage: CType | None,
        context: _Context,
        stack: tuple[str, ...],
    ) -> _Sequence | None:
        """Branches compile from the same stage; differing ends are each cast to the column."""
        case_path = child(path, "case")
        branches: list[tuple[Expression | None, _Sequence, str]] = []
        ok = True
        for i, branch in enumerate(step.branches):
            when = self._expr(
                branch.when, child(child(case_path, i), "when"), context.own, context.target
            )
            then_path = child(child(case_path, i), "then")
            seq = self._sequence(branch.then, then_path, stage, context, stack)
            if when is None or seq is None:
                ok = False
                continue
            branches.append((when, seq, then_path))
        else_path = child(child(case_path, len(step.branches)), "else")
        otherwise = self._sequence(step.otherwise, else_path, stage, context, stack)
        if not ok or otherwise is None:
            return None
        branches.append((None, otherwise, else_path))
        stages = {seq.stage for _, seq, _ in branches}
        out = stages.pop() if len(stages) == 1 else context.target
        finished: list[CompiledChain] = []
        for _, seq, branch_path in branches:
            ops = list(seq.ops)
            if seq.stage != out:
                cast = self.cast_step(
                    arg=None, extra={}, column=context.column, target=context.target,
                    stage=seq.stage, path=branch_path,
                )  # fmt: skip
                if cast is None:
                    return None
                ops.append(cast)
            finished.append(CompiledChain(tuple(ops), out or context.target))
        else_chain = finished.pop()
        whens = tuple(
            (when, chain)
            for (when, _, _), chain in zip(branches, finished, strict=False)
            if when is not None
        )
        keep_else = step.otherwise is not None or bool(else_chain.steps)
        cast_seen = all(seq.cast_seen for _, seq, _ in branches)
        return _Sequence((CaseOp(whens, else_chain if keep_else else None),), out, cast_seen)

    def _macro(
        self,
        step: CallStep,
        path: str,
        stage: CType | None,
        context: _Context,
        stack: tuple[str, ...],
    ) -> _Sequence | None:
        expanded = self._expand_macro(step, path, stack)
        if expanded is None:
            return None
        # Steps inside a macro report at its definition, where they would be fixed.
        definition = child(child("macros", step.name), "steps")
        return self._sequence(expanded, definition, stage, context, (*stack, step.name))

    def _expand_macro(self, step: CallStep, path: str, stack: tuple[str, ...]) -> Chain | None:
        if step.name in stack:
            cycle = " -> ".join((*stack, step.name))
            self.issues.add(path, f"macro cycle: {cycle}")
            return None
        macro = self.macros[step.name]
        params = thaw_mapping(macro.params)
        if step.arg is not None and not isinstance(step.arg, Mapping):
            self.issues.add(path, f"macro {step.name!r} takes named parameters, not a value")
            return None
        given = thaw_mapping(step.arg) if isinstance(step.arg, Mapping) else {}
        given.update(thaw_mapping(step.kwargs))
        unknown = sorted(set(given) - set(params))
        if unknown:
            self.issues.add(path, f"macro {step.name!r} has no parameter {', '.join(unknown)}")
            return None
        params.update(given)
        raw = _fill(macro.steps.spec_dump(), params)
        expanded = Chain.spec_parse(raw, child(child("macros", step.name), "steps"), self.issues)
        return expanded if isinstance(expanded, Chain) else None

    # --- expressions --------------------------------------------------------------------

    def _expr(
        self, text: str, path: str, own: str | None, target: CType = _STRING
    ) -> Expression | None:
        """Compile an expression; macros called in it cast bare types to ``target``."""
        macros = {name: _MacroFunction(self, name, target) for name in self.macros}
        scope = dataclasses.replace(
            self.scope, own=own, functions={**self.scope.functions, **macros}
        )
        try:
            return compile_expr(text, scope)
        except ExprError as exc:
            self.issues.add(path, str(exc))
            return None

    # --- nested fields ------------------------------------------------------------------

    def _fields(
        self, spec: ColumnSpec, target: CType, path: str, own: str | None
    ) -> FieldsOp | None:
        fields_path = child(path, "fields")
        members = spec.fields or {}
        if target.kind not in {"struct", "json"}:
            self.issues.add(fields_path, f"fields needs a struct or json column, not {target}")
            return None
        ops = [
            op
            for member_path, member in members.items()
            if (op := self._field(member_path, member, target, child(fields_path, member_path),
                                  own)) is not None
        ]  # fmt: skip
        return FieldsOp(tuple(ops)) if len(ops) == len(members) else None

    def _field(  # noqa: PLR0911 -- one early return per problem
        self, member_path: str, member: FieldSpec, target: CType, path: str, own: str | None
    ) -> FieldOp | None:
        segments = path_segments(member_path)
        if segments is None:
            self.issues.add(path, "a member path is names joined by '.', with [*] for list items")
            return None
        member_type = _member_type(target, segments) if target.kind == "struct" else None
        if target.kind == "struct" and member_type is None:
            self.issues.add(path, f"{member_path!r} is not a member of {target}")
            return None
        if member.drop and target.kind == "struct":
            self.issues.add(path, "drop works on json members; for a struct, declare its type")
            return None
        when = None
        if member.when is not None:
            when = self._expr(member.when, child(path, "when"), own)
            if when is None:
                return None
        chain = None
        if member.transform is not None:
            context = _Context(None, member_type or target, own)
            transform_path = child(path, "transform")
            seq = self._sequence(member.transform, transform_path, member_type, context, ())
            if seq is None:
                return None
            if member_type is not None and seq.stage != member_type:
                self.issues.add(
                    transform_path,
                    f"the member is {member_type}, but its chain ends as {_stage(seq.stage)}",
                )
                return None
            chain = CompiledChain(seq.ops, member_type or target)
        return FieldOp(member_path, segments, chain, when, member.drop)

    # --- kwargs and casts ---------------------------------------------------------------

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

    def cast_step(  # noqa: PLR0913 -- the cast's full context
        self,
        *,
        arg: object,
        extra: Mapping[str, Any],
        column: ColumnSpec | None,
        target: CType,
        stage: CType | None,
        path: str,
    ) -> CompiledStep | None:
        """Resolve a cast to ``target`` (or to ``arg``), with layered options."""
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

    def sequence(self, chain: Chain, path: str, target: CType) -> CompiledChain | None:
        """A chain from the raw value with no implicit cast, as a macro called as a function."""
        seq = self._sequence(chain, path, None, _Context(None, target, None), ())
        return None if seq is None else CompiledChain(seq.ops, seq.stage or target)

    def context(self, target: CType = _STRING) -> Context:
        """A context for steps called from an expression."""
        fake = self.scope.constants.get("fake")
        return Context(self.stream, "<expr>", self.settings, target, fake=fake)


def _member_type(ctype: CType, segments: tuple[str, ...]) -> CType | None:
    current: CType | None = ctype
    for segment in segments:
        if current is None:
            return None
        if segment == "[*]":
            current = current.item if current.kind == "list" else None
        elif current.kind == "struct":
            current = dict(current.members).get(segment)
        else:
            return None
    return current


# --- steps called as functions from expressions ------------------------------------------------


def _problems(issues: Issues) -> str:
    return "; ".join(str(issue) for issue in issues.items)


def _key(*parts: object) -> str:
    return json.dumps(parts, sort_keys=True, default=repr)


class _StepFunction:
    """A builtin step called from an expression: ``pad(value, 5)``, ``hash(value, algo='md5')``."""

    def __init__(self, compiler: ChainCompiler, transform: Transform) -> None:
        self.compiler = compiler
        self.transform = transform
        self.cache: dict[str, Any] = {}

    def __call__(self, value: object, *args: object, **kwargs: object) -> object:
        transform = self.transform
        if args:
            if transform.positional is None or len(args) > 1:
                raise StepFailed(f"{transform.name} takes the value and keyword arguments")
            kwargs[transform.positional] = args[0]
        key = _key(kwargs)
        if key not in self.cache:
            issues = Issues()
            parsed = parse_dataclass(transform.kwargs, dict(kwargs), transform.name, issues)
            if issues:
                raise StepFailed(_problems(issues))
            self.cache[key] = parsed
        if value is None and not transform.null_safe:
            return None
        return transform.scalar(value, self.cache[key], self.compiler.context())


class _CastFunction:
    """``cast(value, "decimal(18,2)", **options)`` from an expression."""

    def __init__(self, compiler: ChainCompiler) -> None:
        self.compiler = compiler
        self.cache: dict[str, CompiledStep] = {}

    def __call__(self, value: object, type_name: str, **options: object) -> object:
        key = _key(type_name, options)
        if key not in self.cache:
            try:
                target = parse_ctype(type_name)
            except CTypeError as exc:
                raise StepFailed(str(exc)) from None
            scratch = dataclasses.replace(self.compiler, issues=Issues())
            step = scratch.cast_step(
                arg=None, extra=options, column=None, target=target, stage=None, path="cast"
            )
            if step is None:
                raise StepFailed(_problems(scratch.issues))
            self.cache[key] = step
        step = self.cache[key]
        if value is None:
            return None
        return step.transform.scalar(value, step.kwargs, self.compiler.context(step.kwargs.target))


class _MacroFunction:
    """A macro called from an expression: ``money(value, currency='€')``."""

    def __init__(self, compiler: ChainCompiler, name: str, target: CType) -> None:
        self.compiler = compiler
        self.name = name
        self.target = target
        """The column's type: a bare ``{cast: decimal}`` in the macro means it."""
        self.cache: dict[str, CompiledChain] = {}

    def __call__(self, value: object, **params: object) -> object:
        key = _key(params)
        if key not in self.cache:
            self.cache[key] = self._compile(params)
        chain = self.cache[key]
        try:
            return chain.run(value, self.compiler.context(chain.target))
        except StepError as exc:
            raise StepFailed(f"{self.name}: {exc.cell.rule}: {exc.cell.reason}") from None

    def _compile(self, params: Mapping[str, object]) -> CompiledChain:
        scratch = dataclasses.replace(self.compiler, issues=Issues())
        step = CallStep(self.name, arg=MappingProxyType(dict(params)) if params else None)
        chain = scratch.sequence(Chain((step,)), self.name, self.target)
        if chain is None:
            raise StepFailed(_problems(scratch.issues))
        if chain.reads:
            raise StepFailed(f"macro {self.name!r} reads columns; use it as a step instead")
        return chain


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
