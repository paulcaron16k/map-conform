"""Run the cast corpus tables through the real builtins."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from typing import Any

from map_conform.plan.chain import ChainCompiler, CompiledChain, StepError
from map_conform.spec._struct import Issues
from map_conform.spec.model import Defaults, parse_spec
from map_conform.transforms.builtins import builtin_registry
from map_conform.transforms.registry import Context
from map_conform.types.canonical import parse_ctype
from map_conform.types.wire import to_wire
from tests.fixtures.paths import FIXTURES

ERROR = "!error"
NULL = "!null"


@dataclass(frozen=True)
class Case:
    """One corpus row."""

    case: str
    type: str
    input: str
    kwargs: dict[str, Any]
    expected: str
    note: str


def cases(table: str) -> list[Case]:
    """The rows of a corpus table."""
    with (FIXTURES / "corpus" / table).open(encoding="utf-8", newline="") as f:
        return [
            Case(
                r["case"],
                r["type"],
                r["input"],
                json.loads(r["kwargs"] or "{}"),
                r["expected"],
                r["note"],
            )
            for r in csv.DictReader(f)
        ]


def compile_case(case: Case, defaults: Defaults | None = None) -> CompiledChain:
    """Compile ``{cast: <type>, **kwargs}`` for the case's column type."""
    target = parse_ctype(case.type)
    spec = parse_spec({
        "version": 1,
        "streams": {"s": {"columns": {"c": {
            "type": case.type, "transform": {"cast": target.kind, **case.kwargs},
        }}}},
    })  # fmt: skip
    column = spec.streams["s"].spec.columns["c"]
    issues = Issues()
    compiler = ChainCompiler(builtin_registry(), defaults or spec.defaults, spec.macros, issues)
    compiled = compiler.compile(column.transform, column, target, "c")
    if compiled is None:
        msg = f"{case.case} does not compile: {[str(i) for i in issues.items]}"
        raise AssertionError(msg)
    return compiled


def run_case(case: Case) -> str:
    """The case's outcome as the corpus writes it: a wire value, !null or !error."""
    compiled = compile_case(case)
    ctx = Context("s", "c", Defaults(), compiled.target, row=1)
    try:
        value = compiled.run(case.input, ctx)
    except StepError:
        return ERROR
    if value is None:
        return NULL
    wired = to_wire(value, compiled.target)
    return wired if isinstance(wired, str) else json.dumps(wired)
