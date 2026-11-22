"""Chain compilation: registry lookup, kwargs validation, type flow, implicit cast (WBS 5.1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from map_conform.errors import StepFailed
from map_conform.plan.chain import ChainCompiler
from map_conform.plan.ops import CastArgs, CompiledChain, StepError
from map_conform.spec._struct import Issues
from map_conform.spec.model import ColumnSpec, Defaults, parse_spec
from map_conform.spec.steps import Chain
from map_conform.transforms.registry import RAW, Context, Registry, Transform
from map_conform.types.canonical import CType, parse_ctype


@dataclass(frozen=True)
class StripKwargs:
    """Test kwargs: characters to strip."""

    chars: str = " "


@dataclass(frozen=True)
class RoundKwargs:
    """Test kwargs: digits to keep."""

    ndigits: int = 0


@dataclass(frozen=True)
class IntCastKwargs:
    """Test kwargs for the integer cast."""

    trim: bool = True
    base: int = 10


def _int_cast(value: object, args: CastArgs, _ctx: Context) -> object:
    text = str(value).strip() if args.options.trim else str(value)
    try:
        return int(text, args.options.base)
    except ValueError as exc:
        raise StepFailed(f"not an integer: {exc}") from exc


def registry() -> Registry:
    """A registry of test doubles; the real builtins arrive in later PRs."""
    reg = Registry()
    reg.register(Transform("strip_chars", lambda v, k, _c: str(v).strip(k.chars),
                           kwargs=StripKwargs, positional="chars"))  # fmt: skip
    reg.register(Transform("round", lambda v, k, _c: round(v, k.ndigits), kwargs=RoundKwargs,
                           accepts=frozenset({"float64"}), positional="ndigits"))  # fmt: skip
    reg.register(Transform("upper", lambda v, _k, _c: str(v).upper()))
    reg.register(Transform("fail", lambda _v, _k, _c: (_ for _ in ()).throw(StepFailed("boom")),
                           accepts=frozenset({RAW, "string", "int64"})))  # fmt: skip
    reg.register_cast(
        {"int64", "int32"},
        Transform("cast", _int_cast, kwargs=IntCastKwargs, accepts=frozenset({RAW, "string"}),
                  defaults=lambda s, c: {"trim": c.trim if c and c.trim is not None
                                         else s.values.trim}),
    )  # fmt: skip
    to_string = Transform("cast", lambda v, _a, _c: str(v), kwargs=IntCastKwargs,
                          accepts=frozenset({RAW, "int64", "string"}))  # fmt: skip
    reg.register_cast({"string"}, to_string)
    return reg


def compile_chain(
    transform: Any,  # noqa: ANN401 -- raw chain data as written in a spec
    target: str = "int64",
    *,
    macros: dict[str, Any] | None = None,
    column: dict[str, Any] | None = None,
    defaults: dict[str, Any] | None = None,
) -> tuple[CompiledChain | None, list[str]]:
    """Parse a spec with one column and compile its chain."""
    col = dict(column or {})
    if transform is not None:
        col["transform"] = transform
    spec = parse_spec({
        "version": 1,
        "defaults": defaults or {},
        "macros": macros or {},
        "streams": {"s": {"columns": {"c": col}}},
    })  # fmt: skip
    column_spec = spec.streams["s"].spec.columns["c"]
    issues = Issues()
    compiler = ChainCompiler(registry(), spec.defaults, spec.macros, issues)
    compiled = compiler.compile(column_spec.transform, column_spec, parse_ctype(target),
                                "streams.s.columns.c")  # fmt: skip
    return compiled, [str(i) for i in issues.items]


def ctx(target: str = "int64") -> Context:
    """A run-time context."""
    return Context("s", "c", Defaults(), parse_ctype(target), row=3)


def test_implicit_cast_is_appended() -> None:
    """A chain without a cast gets one, so {type: int64} alone parses integers."""
    compiled, problems = compile_chain(None)
    assert problems == []
    assert compiled is not None
    assert [s.rule for s in compiled.steps] == ["cast: int64"]
    assert compiled.run(" 42 ", ctx()) == 42  # noqa: PLR2004


def test_steps_run_in_order_with_positional_args() -> None:
    """Pre-cast steps see the raw value; the cast follows."""
    compiled, problems = compile_chain([{"strip_chars": "$"}, "upper"], target="string")
    assert problems == []
    assert compiled is not None
    assert [s.rule for s in compiled.steps] == ["strip_chars", "upper", "cast: string"]
    assert compiled.run("$ab$", ctx("string")) == "AB"


def test_bad_kwargs_fail_at_compile_with_their_path() -> None:
    """Unknown keys, wrong types and positional args to keyword-only steps."""
    bad = [
        {"strip_chars": {"char": "$"}},
        {"upper": 1},
        {"strip_chars": {"chars": 5}},
        {"cast": "int64", "radix": 16},
    ]
    _, problems = compile_chain(bad)
    assert problems == [
        "streams.s.columns.c.transform[0].char: unknown key; allowed here: chars",
        "streams.s.columns.c.transform[1]: upper takes keyword arguments only",
        "streams.s.columns.c.transform[2].chars: expected a string, got an integer",
        "streams.s.columns.c.transform[3].radix: unknown key; allowed here: base, trim",
    ]


def test_unknown_step() -> None:
    """A name that is neither a builtin nor a macro."""
    _, problems = compile_chain("strp")
    assert problems == [
        "streams.s.columns.c.transform: unknown step 'strp': not a builtin or a macro"
    ]


def test_pre_and_post_cast_types_are_checked() -> None:
    """A numeric step before the cast, or a string step after it, is refused."""
    _, problems = compile_chain([{"round": 2}], target="float64")
    assert problems == ["streams.s.columns.c.transform: round cannot take the raw value here"]
    _, problems = compile_chain([{"cast": "int64"}, "upper"])
    assert problems == ["streams.s.columns.c.transform[1]: upper cannot take a int64 value here"]


def test_cast_targets() -> None:
    """A bare kind means the column's type; other types must match the column in the end."""
    compiled, problems = compile_chain({"cast": "int64", "base": 16})
    assert problems == []
    assert compiled is not None
    assert compiled.run("ff", ctx()) == 255  # noqa: PLR2004
    _, problems = compile_chain({"cast": "string"})
    assert problems == [("streams.s.columns.c.transform: the chain ends as a string value, but "
                        "the column is int64")]  # fmt: skip
    _, problems = compile_chain({"cast": "decimel"})
    assert problems == [("streams.s.columns.c.transform: unknown type 'decimel' at position 7 "
                        "in 'decimel'")]  # fmt: skip
    _, problems = compile_chain(None, target="uuid")
    assert problems == ["streams.s.columns.c.transform: there is no cast to uuid yet"]


def test_cast_options_layer_defaults_column_parse_and_step() -> None:
    """Stream defaults < column overrides < column parse < step kwargs."""

    def options(**kw: Any) -> Any:  # noqa: ANN401
        compiled, problems = compile_chain(**kw)
        assert problems == []
        assert compiled is not None
        return compiled.steps[-1].kwargs.options

    assert options(transform=None).trim is True
    assert options(transform=None, defaults={"values": {"trim": False}}).trim is False
    assert options(transform=None, defaults={"values": {"trim": False}},
                   column={"trim": True}).trim is True  # fmt: skip
    assert options(transform=None, column={"parse": {"base": 8}}).base == 8  # noqa: PLR2004
    step_wins = options(transform={"cast": "int64", "base": 2}, column={"parse": {"base": 8}})
    assert step_wins.base == 2  # noqa: PLR2004
    _, problems = compile_chain(None, column={"parse": {"radix": 8}})
    assert problems == [
        "streams.s.columns.c.transform.radix: unknown key; allowed here: base, trim"
    ]


MONEY = {"params": {"sym": "$"}, "steps": [{"strip_chars": "${sym}"}, "upper"]}


def test_macros_expand_with_parameters() -> None:
    """Macro steps run in place, with defaults and overrides for parameters."""
    compiled, problems = compile_chain("money", target="string", macros={"money": MONEY})
    assert problems == []
    assert compiled is not None
    assert compiled.run("$ab$", ctx("string")) == "AB"
    compiled, _ = compile_chain({"money": {"sym": "€"}}, target="string", macros={"money": MONEY})
    assert compiled is not None
    assert compiled.run("€x€", ctx("string")) == "X"


def test_macro_problems() -> None:
    """Unknown parameters, values for parameters, cycles, and errors inside macro steps."""
    _, problems = compile_chain({"money": {"symbol": "€"}}, macros={"money": MONEY})
    assert problems == ["streams.s.columns.c.transform: macro 'money' has no parameter symbol"]
    _, problems = compile_chain({"money": "€"}, macros={"money": MONEY})
    assert problems == [("streams.s.columns.c.transform: macro 'money' takes named parameters, "
                        "not a value")]  # fmt: skip
    _, problems = compile_chain("a", macros={"a": ["b"], "b": ["a"]})
    assert problems == ["macros.b.steps: macro cycle: a -> b -> a"]
    _, problems = compile_chain("m", macros={"m": [{"strip_chars": {"x": 1}}, "upper"]},
                                target="string")  # fmt: skip
    assert problems == ["macros.m.steps[0].x: unknown key; allowed here: chars"]


def test_failures_name_the_step_and_nulls_pass() -> None:
    """A failing step raises StepError with its rule; nulls skip steps that are not null-safe."""
    compiled, _ = compile_chain("fail")
    assert compiled is not None
    with pytest.raises(StepError) as caught:
        compiled.run("x", ctx())
    assert (caught.value.cell.rule, caught.value.cell.reason) == ("fail", "boom")
    plain, _ = compile_chain(None)
    assert plain is not None
    with pytest.raises(StepError, match=r"cast: int64: not an integer"):
        plain.run("x", ctx())
    assert plain.run(None, ctx()) is None


def test_column_spec_type_is_honoured() -> None:
    """A ColumnSpec with no transform still compiles to its declared type."""
    issues = Issues()
    compiled = ChainCompiler(registry(), Defaults(), {}, issues).compile(
        None, ColumnSpec(type="int32"), CType("int32"), "p"
    )
    assert issues.items == []
    assert compiled is not None
    assert compiled.target == CType("int32")
    assert Chain.spec_parse("upper", "", Issues()) is not None
