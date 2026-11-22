"""Vectorised column chains for the columnar executor (detailed design §10.2, WBS 8.4-8.5).

A column is vectorised when every step of its chain has an Arrow implementation
(:mod:`map_conform.transforms.vector`), it has no ``enum``, no nested renames and no shape,
and no expression or filter reads it (expressions see Python values). Its chain then runs on
the whole column; the rows any step leaves as *todo* go through the scalar chain, row by row,
so each row's result is exactly the RECORD path's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pyarrow.compute as _compute

from map_conform.plan.lower import chain_vector
from map_conform.transforms.vector import Vector
from map_conform.types.canonical import CType
from map_conform.types.to_arrow import to_arrow

if TYPE_CHECKING:
    from map_conform.plan.compile import ColumnPlan

# The pyarrow stubs type compute kernels as returning unions of arrays, chunked arrays and
# scalars, so array-in, array-out code cannot be checked through them. The parity suite
# (tests/parity) checks this module against the scalar path instead.
_pa: Any = pa
pc: Any = _compute


@dataclass(frozen=True)
class VectorChain:
    """A column's chain as Arrow ops."""

    steps: tuple[tuple[Vector, Any, CType], ...]
    target: CType
    nullable: bool
    default: Any = None

    def run(self, column: pa.Array) -> tuple[pa.Array, pa.Array]:
        """The column's values and the rows to compute row by row."""
        todo = _pa.repeat(_pa.scalar(False), len(column))  # noqa: FBT003
        values = column
        arrow_type = to_arrow(self.target)
        try:
            for fn, kwargs, ctype in self.steps:
                values, more = fn(values, kwargs, ctype)
                todo = pc.or_(todo, pc.fill_null(more, False))  # noqa: FBT003
            if values.type != arrow_type:
                values = pc.cast(values, arrow_type)
        except (pa.ArrowInvalid, pa.ArrowNotImplementedError, pa.ArrowTypeError):
            # A kernel refused this batch: the whole column runs row by row instead.
            return _pa.nulls(len(column), arrow_type), _pa.repeat(_pa.scalar(True), len(column))  # noqa: FBT003
        if self.default is not None:
            values = pc.fill_null(values, _pa.scalar(self.default, arrow_type))
        if not self.nullable:  # a null is an error: the scalar path raises it
            todo = pc.or_(todo, pc.is_null(values))
        return values, todo


def vector_chain(column: ColumnPlan, read: frozenset[str]) -> VectorChain | None:
    """The column's vector chain, or None when it must run row by row."""
    if column.enum is not None or column.member_names is not None or column.name in read:
        return None
    lowered = chain_vector(column.chain.steps, column.ctype)
    if lowered is None:
        return None
    return VectorChain(((lowered, None, column.ctype),), column.ctype, column.nullable,
                       column.default)  # fmt: skip
