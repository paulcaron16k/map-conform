"""Transform chains, steps and macros (detailed design §3.4).

A chain is one step or a list of steps. In mapping form, the **first key other than**
``when`` names the step; its value is the step's argument and the remaining keys are keyword
arguments::

    trim                                   -> CallStep("trim")
    {strip_chars: "$, "}                   -> CallStep("strip_chars", arg="$, ")
    {cast: decimal, rounding: half_even}   -> CallStep("cast", arg="decimal", kwargs={rounding})
    {hash: {}, when: "country == 'DE'"}    -> CallStep("hash", arg={}, when=...)
    {expr: "value.strip()"}                -> ExprStep("value.strip()")
    {case: [{when: .., then: ..}, {else: ..}]} -> CaseStep(...)

Whether a name is a builtin, a macro or a UDF, and whether its arguments fit, is checked when
the plan is compiled against the registries.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from map_conform.spec._struct import INVALID, Issues, child, dump, freeze, freeze_mapping, thaw

_STEP_NAME = r"^[A-Za-z_][A-Za-z0-9_]*$"
_RESERVED = frozenset({"when", "expr", "case"})


def _empty() -> Mapping[str, Any]:
    return MappingProxyType({})


def _parse_when(data: Mapping[str, object], path: str, issues: Issues) -> str | None:
    when = data.get("when")
    if when is None and "when" in data:
        issues.add(child(path, "when"), "expected an expression string, got null")
    if when is not None and not isinstance(when, str):
        issues.add(child(path, "when"), "expected an expression string")
        return None
    return when


@dataclass(frozen=True)
class CallStep:
    """A builtin, macro or UDF applied with an argument and keyword arguments."""

    name: str
    arg: Any = None
    kwargs: Mapping[str, Any] = field(default_factory=_empty)
    when: str | None = None

    def spec_dump(self) -> object:
        """A bare name when there is nothing else, otherwise ``{name: arg, **kwargs}``."""
        if self.arg is None and not self.kwargs and self.when is None:
            return self.name
        out: dict[str, object] = {self.name: thaw(self.arg)}
        out.update({k: thaw(v) for k, v in self.kwargs.items()})
        if self.when is not None:
            out["when"] = self.when
        return out


@dataclass(frozen=True)
class ExprStep:
    """A step whose result is an expression over ``value`` and the row."""

    expr: str
    when: str | None = None

    def spec_dump(self) -> object:
        """``{expr: ...}``."""
        out: dict[str, object] = {"expr": self.expr}
        if self.when is not None:
            out["when"] = self.when
        return out


@dataclass(frozen=True)
class CaseBranch:
    """``{when: <expr>, then: <chain>}``."""

    when: str
    then: Chain


@dataclass(frozen=True)
class CaseStep:
    """Conditional chains: the first branch whose ``when`` is truthy runs, else ``otherwise``."""

    branches: tuple[CaseBranch, ...]
    otherwise: Chain | None = None
    when: str | None = None

    def spec_dump(self) -> object:
        """``{case: [{when, then}, ..., {else}]}``."""
        items: list[object] = [{"when": b.when, "then": dump(b.then)} for b in self.branches]
        if self.otherwise is not None:
            items.append({"else": dump(self.otherwise)})
        out: dict[str, object] = {"case": items}
        if self.when is not None:
            out["when"] = self.when
        return out


Step = CallStep | ExprStep | CaseStep


def _parse_step(data: object, path: str, issues: Issues) -> Step | None:  # noqa: PLR0911 -- one early return per malformed shape
    if isinstance(data, str):
        if not re.match(_STEP_NAME, data) or data in _RESERVED:
            issues.add(path, f"{data!r} is not a step name")
            return None
        return CallStep(data)
    if not isinstance(data, dict) or not data:
        issues.add(path, "a step is a name or a non-empty mapping")
        return None
    when = _parse_when(data, path, issues)
    keys = [k for k in data if k != "when"]
    if not keys:
        issues.add(path, "a step needs a name besides 'when'")
        return None
    name, rest = keys[0], keys[1:]
    if not isinstance(name, str) or not re.match(_STEP_NAME, name):
        issues.add(path, f"{name!r} is not a step name")
        return None
    if name == "expr":
        return _parse_expr_step(data, rest, when, path, issues)
    if name == "case":
        return _parse_case(data, rest, when, path, issues)
    return CallStep(
        name,
        arg=freeze(data[name]),
        kwargs=MappingProxyType({k: freeze(data[k]) for k in rest}),
        when=when,
    )


def _parse_expr_step(
    data: Mapping[str, object], rest: list[str], when: str | None, path: str, issues: Issues
) -> ExprStep | None:
    expr = data["expr"]
    for key in rest:
        issues.add(child(path, key), "unknown key; an expr step allows only 'when'")
    if not isinstance(expr, str):
        issues.add(child(path, "expr"), "expected an expression string")
        return None
    return None if rest else ExprStep(expr, when)


def _parse_case(
    data: Mapping[str, object], rest: list[str], when: str | None, path: str, issues: Issues
) -> CaseStep | None:
    for key in rest:
        issues.add(child(path, key), "unknown key; a case step allows only 'when'")
    items = data["case"]
    case_path = child(path, "case")
    if not isinstance(items, list) or not items:
        issues.add(case_path, "expected a non-empty list of {when, then} and an optional {else}")
        return None
    branches: list[CaseBranch] = []
    otherwise: Chain | None = None
    ok = not rest
    for i, item in enumerate(items):
        item_path = child(case_path, i)
        if isinstance(item, dict) and set(item) == {"else"}:
            if i != len(items) - 1:
                issues.add(item_path, "'else' must be the last branch")
                ok = False
            parsed = Chain.spec_parse(item["else"], child(item_path, "else"), issues)
            ok = ok and parsed is not INVALID
            otherwise = parsed if isinstance(parsed, Chain) else None
            continue
        if not isinstance(item, dict) or set(item) != {"when", "then"}:
            issues.add(item_path, "a branch is {when: <expr>, then: <chain>} or {else: <chain>}")
            ok = False
            continue
        if not isinstance(item["when"], str):
            issues.add(child(item_path, "when"), "expected an expression string")
            ok = False
            continue
        then = Chain.spec_parse(item["then"], child(item_path, "then"), issues)
        if isinstance(then, Chain):
            branches.append(CaseBranch(item["when"], then))
        else:
            ok = False
    if not branches and ok:
        issues.add(case_path, "a case needs at least one {when, then} branch")
        ok = False
    return CaseStep(tuple(branches), otherwise, when) if ok else None


@dataclass(frozen=True)
class Chain:
    """An ordered list of steps. The implicit cast to the column type is added at compile time."""

    steps: tuple[Step, ...]

    @classmethod
    def spec_parse(cls, data: object, path: str, issues: Issues) -> Chain | Any:  # noqa: ANN401
        """Parse one step or a list of steps."""
        raw = data if isinstance(data, list) else [data]
        if not raw:
            issues.add(path, "a chain needs at least one step")
            return INVALID
        many = isinstance(data, list)
        steps = [
            _parse_step(s, child(path, i) if many else path, issues) for i, s in enumerate(raw)
        ]
        if any(s is None for s in steps):
            return INVALID
        return cls(tuple(s for s in steps if s is not None))

    def spec_dump(self) -> object:
        """A single step stays a single step; otherwise a list."""
        dumped = [dump(s) for s in self.steps]
        return dumped[0] if len(dumped) == 1 else dumped

    @classmethod
    def spec_schema(cls, defs: dict[str, Any]) -> dict[str, Any]:
        """A step or a list of steps."""
        if "Step" not in defs:
            defs["Step"] = {
                "description": (
                    "A step name, or a mapping whose first key (other than 'when') names the "
                    "step: its value is the argument and the other keys are keyword arguments. "
                    "{expr: ...} and {case: [...]} are built in."
                ),
                "anyOf": [
                    {"type": "string", "pattern": _STEP_NAME},
                    {"type": "object", "minProperties": 1},
                ],
            }
        step = {"$ref": "#/$defs/Step"}
        return {"anyOf": [step, {"type": "array", "items": step, "minItems": 1}]}


@dataclass(frozen=True)
class Macro:
    """A named, parameterised chain. ``${param}`` in its steps is filled at expansion."""

    steps: Chain
    params: Mapping[str, Any] = field(default_factory=_empty)
    doc: str | None = None

    @classmethod
    def spec_parse(cls, data: object, path: str, issues: Issues) -> Macro | Any:  # noqa: ANN401
        """Either a chain, or ``{steps, params?, doc?}``."""
        if isinstance(data, dict) and "steps" in data and set(data) <= {"steps", "params", "doc"}:
            steps = Chain.spec_parse(data["steps"], child(path, "steps"), issues)
            params = data.get("params", {})
            doc = data.get("doc")
            ok = isinstance(steps, Chain)
            if not isinstance(params, dict) or not all(isinstance(k, str) for k in params):
                issues.add(child(path, "params"), "expected a mapping of parameter defaults")
                ok = False
            if doc is not None and not isinstance(doc, str):
                issues.add(child(path, "doc"), "expected a string")
                ok = False
            if not ok:
                return INVALID
            return cls(steps, freeze_mapping(params), doc)
        steps = Chain.spec_parse(data, path, issues)
        return cls(steps) if isinstance(steps, Chain) else INVALID

    def spec_dump(self) -> object:
        """The short chain form when there are no params or doc."""
        if not self.params and self.doc is None:
            return dump(self.steps)
        out: dict[str, object] = {"steps": dump(self.steps)}
        if self.params:
            out["params"] = thaw(self.params)
        if self.doc is not None:
            out["doc"] = self.doc
        return out

    @classmethod
    def spec_schema(cls, defs: dict[str, Any]) -> dict[str, Any]:
        """A chain, or an object with steps, params and doc."""
        chain = Chain.spec_schema(defs)
        return {
            "anyOf": [
                chain,
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["steps"],
                    "properties": {
                        "steps": chain,
                        "params": {"type": "object"},
                        "doc": {"type": "string"},
                    },
                },
            ]
        }
