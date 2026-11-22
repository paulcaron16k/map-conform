"""User-defined functions (detailed design §8).

A UDF is a Python function registered under a name, usable as a step
(``{fiscal_week: {start_month: 4}}``) or in an expression (``fiscal_week(order_date,
start_month=4)``)::

    from map_conform import udf


    @udf(name="fiscal_week", returns="int32")
    def fiscal_week(value, *, start_month: int = 7, ctx=None) -> int | None: ...

The value is the first parameter; options are keyword-only, and are validated against the
signature when the plan compiles, like a builtin's kwargs. A ``ctx`` parameter receives the
step context. ``returns`` is the CType the function produces, so the chain's type checking
knows it; without it the result is untyped and the column's implicit cast follows.

**Registration.**

- Entry points in the group ``map_conform.functions``, from any installed package: always
  allowed, since installing the package was the decision to trust it.
- ``udfs: {name: "package.module:function"}`` in the spec: only with the plugin setting
  ``allow_python_udfs: true``, because the module is imported from the project.

A UDF is arbitrary Python, like a database UDF: the expression sandbox does not apply to it.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import sys
import types
import typing
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Literal, TypeVar

from map_conform.errors import StepFailed
from map_conform.expr.functions import FUNCTIONS
from map_conform.spec._struct import Issues, child
from map_conform.spec.errors import SpecError
from map_conform.transforms.registry import ANY, Registry, Transform
from map_conform.types.canonical import CType, CTypeError, parse_ctype

ENTRY_POINT_GROUP = "map_conform.functions"
_ATTRIBUTE = "__map_conform_udf__"
_SIMPLE = (str, int, float, bool, type(None))

F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True)
class UdfOptions:
    """What ``@udf`` records on a function."""

    name: str | None = None
    returns: str | None = None
    vectorized: bool = False
    null_safe: bool = False
    doc: str | None = None


def udf(
    name: str | None = None,
    *,
    returns: str | None = None,
    vectorized: bool = False,
    null_safe: bool = False,
    doc: str | None = None,
) -> Callable[[F], F]:
    """Mark a function as a map-conform UDF.

    Args:
        name: The name specs use; the function's name by default.
        returns: The CType it produces, e.g. ``int32`` or ``decimal(10,2)``.
        vectorized: It takes and returns a ``pyarrow.Array`` instead of one value.
        null_safe: It must see nulls; otherwise nulls skip it.
        doc: One line for ``map-conform functions``; the docstring's first line by default.

    Returns:
        A decorator that returns the function unchanged.
    """

    def mark(fn: F) -> F:
        setattr(fn, _ATTRIBUTE, UdfOptions(name, returns, vectorized, null_safe, doc))
        return fn

    return mark


@dataclass(frozen=True)
class Udf:
    """A loaded UDF, ready to register as a step."""

    name: str
    fn: Callable[..., Any]
    origin: str
    """Where it came from: the entry point's package, or the spec's module path."""
    options: UdfOptions

    def transform(self) -> Transform:
        """The step a chain compiles: kwargs from the signature, output from ``returns``.

        Raises:
            ValueError: for a signature or ``returns`` that cannot be a step.
        """
        kwargs_type, takes_ctx = _kwargs_dataclass(self.name, self.fn)
        produces = None
        if self.options.returns is not None:
            try:
                returned = parse_ctype(self.options.returns)
            except CTypeError as exc:
                msg = f"returns: {exc}"
                raise ValueError(msg) from None
            produces = _fixed_stage(returned)
        else:
            produces = _raw_stage
        return Transform(
            self.name,
            _scalar(self.fn, takes_ctx=takes_ctx, vectorized=self.options.vectorized),
            kwargs=kwargs_type,
            accepts=frozenset({ANY}),
            produces=produces,
            doc=self.options.doc or _first_line(self.fn) or f"UDF from {self.origin}",
            null_safe=self.options.null_safe,
        )


def _first_line(fn: Callable[..., Any]) -> str:
    return (inspect.getdoc(fn) or "").partition("\n")[0]


def _fixed_stage(ctype: CType) -> Callable[[CType | None, object], CType | None]:
    return lambda _stage, _kwargs: ctype


def _raw_stage(_stage: CType | None, _kwargs: object) -> CType | None:
    return None


def _annotation(hint: object) -> object:
    """A hint the strict parser checks (str, int, float, bool, None and unions of them)."""
    args = typing.get_args(hint)
    if hint in _SIMPLE or (
        typing.get_origin(hint) in (typing.Union, types.UnionType)
        and all(a in _SIMPLE for a in args)
    ):
        return hint
    if typing.get_origin(hint) is Literal:
        return hint
    return Any


def _kwargs_dataclass(name: str, fn: Callable[..., Any]) -> tuple[type[Any], bool]:
    """A frozen dataclass of the function's keyword-only options, and whether it takes ctx.

    Raises:
        ValueError: when the function does not take the value first and options by keyword.
    """
    signature = inspect.signature(fn)
    params = list(signature.parameters.values())
    if not params or params[0].kind not in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    ):
        msg = "a UDF takes the value as its first parameter"
        raise ValueError(msg)
    try:
        hints = typing.get_type_hints(fn)
    except (NameError, TypeError):
        hints = {}
    fields: list[tuple[str, object, dataclasses.Field[Any]]] = []
    takes_ctx = False
    for param in params[1:]:
        if param.name == "ctx":
            takes_ctx = True
            continue
        if param.kind is not inspect.Parameter.KEYWORD_ONLY:
            msg = f"option {param.name!r} must be keyword-only (put it after *)"
            raise ValueError(msg)
        default = (
            dataclasses.field()
            if param.default is inspect.Parameter.empty
            else dataclasses.field(default=param.default)
        )
        fields.append((param.name, _annotation(hints.get(param.name, Any)), default))
    fields.sort(key=lambda f: f[2].default is not dataclasses.MISSING)  # required first
    cls = dataclasses.make_dataclass(f"{name}_kwargs", fields, frozen=True)
    return cls, takes_ctx


def _scalar(
    fn: Callable[..., Any], *, takes_ctx: bool, vectorized: bool
) -> Callable[[Any, Any, Any], Any]:
    def run(value: object, kwargs: Any, ctx: object) -> object:  # noqa: ANN401 -- the UDF's kwargs dataclass
        options = {f.name: getattr(kwargs, f.name) for f in dataclasses.fields(kwargs)}
        if takes_ctx:
            options["ctx"] = ctx
        try:
            if vectorized:
                return _one(fn, value, options)
            return fn(value, **options)
        except StepFailed:
            raise
        except Exception as exc:  # noqa: BLE001 -- a UDF's failure is a cell error with context
            raise StepFailed(f"{type(exc).__name__}: {exc}") from None

    return run


def _one(fn: Callable[..., Any], value: object, options: dict[str, Any]) -> object:
    """Run a vectorized UDF on one value, as the row executor does."""
    import pyarrow as pa  # noqa: PLC0415 -- only vectorized UDFs need it here

    values: list[Any] = [value]
    result = fn(pa.array(values), **options)
    return result[0].as_py()


# --- loading ----------------------------------------------------------------------------------


def _options(fn: Callable[..., Any]) -> UdfOptions:
    found = getattr(fn, _ATTRIBUTE, None)
    return found if isinstance(found, UdfOptions) else UdfOptions()


def _from_entry_points(issues: Issues) -> dict[str, Udf]:
    out: dict[str, Udf] = {}
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        origin = f"entry point {ep.name!r} ({ep.value})"
        try:
            fn = ep.load()
        except Exception as exc:  # noqa: BLE001 -- report any import failure with its source
            issues.add("", f"cannot load UDF {origin}: {type(exc).__name__}: {exc}")
            continue
        if not callable(fn):
            issues.add("", f"UDF {origin} is not callable")
            continue
        out[ep.name] = Udf(ep.name, fn, origin, _options(fn))
    return out


@contextmanager
def _project_on_path() -> Generator[None]:
    """Import spec UDF modules from the project directory (the current directory)."""
    cwd = str(Path.cwd())
    added = cwd not in sys.path
    if added:
        sys.path.insert(0, cwd)
    try:
        yield
    finally:
        if added and cwd in sys.path:
            sys.path.remove(cwd)


def _from_spec(spec_udfs: Mapping[str, str], issues: Issues) -> dict[str, Udf]:
    out: dict[str, Udf] = {}
    with _project_on_path():
        for name, target in spec_udfs.items():
            path = child("udfs", name)
            module_name, _, attr = target.partition(":")
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:  # noqa: BLE001 -- report any import failure at its path
                issues.add(path, f"cannot import {module_name!r}: {type(exc).__name__}: {exc}")
                continue
            fn = getattr(module, attr, None)
            if not callable(fn):
                issues.add(path, f"{module_name!r} has no function {attr!r}")
                continue
            out[name] = Udf(name, fn, target, _options(fn))
    return out


def load_udfs(spec_udfs: Mapping[str, str], *, allow_python_udfs: bool) -> dict[str, Udf]:
    """Every UDF: installed entry points, then the spec's module paths (which win).

    Raises:
        SpecError: listing every UDF that cannot load, or module paths without
            ``allow_python_udfs``.
    """
    issues = Issues()
    udfs = _from_entry_points(issues)
    if spec_udfs and not allow_python_udfs:
        for name in spec_udfs:
            issues.add(
                child("udfs", name),
                "module-path UDFs run project code; set allow_python_udfs: true to allow them",
            )
    elif spec_udfs:
        udfs.update(_from_spec(spec_udfs, issues))
    if issues:
        raise SpecError(issues.items, "the UDFs")
    return udfs


def registry_with(base: Registry, udfs: Mapping[str, Udf]) -> Registry:
    """A registry of the builtins plus these UDFs.

    Raises:
        SpecError: for a UDF named like a builtin, or one that cannot be a step.
    """
    if not udfs:
        return base
    issues = Issues()
    registry = Registry(dict(base.transforms), dict(base.casts))
    for name, item in udfs.items():
        if name in base.transforms or name == "cast":
            issues.add(child("udfs", name), f"{name!r} is a builtin; choose another name")
            continue
        if name in FUNCTIONS:
            issues.add(child("udfs", name), f"{name!r} is an expression function; choose another")
            continue
        try:
            registry.transforms[name] = item.transform()
        except ValueError as exc:
            issues.add(child("udfs", name), f"{item.origin}: {exc}")
    if issues:
        raise SpecError(issues.items, "the UDFs")
    return registry
