"""Project UDFs, loaded by module path behind allow_python_udfs."""
# ruff: noqa: INP001 -- a project directory's module, not a package

from __future__ import annotations

from typing import Any

from map_conform import udf


@udf(null_safe=True)
def where_from(value: object, *, ctx: Any = None) -> str:  # noqa: ANN401
    """The stream name, and whether the value was null."""
    return f"{ctx.stream}:{'null' if value is None else value}"


def explode(value: object) -> object:
    """Always fails."""
    msg = f"cannot handle {value!r}"
    raise RuntimeError(msg)


def broken(value: object, option: int) -> object:
    """Its option is positional, so it cannot be a step."""
    return value, option
