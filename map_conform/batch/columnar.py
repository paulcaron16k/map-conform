"""The columnar executor: conform a whole Arrow batch at once (detailed design §10.2).

Vectorised columns (:mod:`map_conform.plan.vector`) run as Arrow chains on the whole column.
Everything else runs through the row executor, row by row, skipping the vectorised columns
for the rows they computed: columns with expressions, the filter, ``_sdc_*``, policies,
rejects and metrics all behave exactly as on the RECORD path. Rows a vector op left as todo
are computed by the row executor too, and *spliced* into the column (WBS 8.5).

Rejected rows (``on_error: reject``) and rows the filter drops are taken out of the batch;
the output table has exactly the declared schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pyarrow.compute as _compute

from map_conform.batch.arrow import arrow_schema, arrow_value, output_columns
from map_conform.errors import RowRejected
from map_conform.plan.row import RowExecutor

if TYPE_CHECKING:
    from collections.abc import Callable

# The pyarrow stubs type compute kernels as returning unions of arrays, chunked arrays and
# scalars, so array-in, array-out code cannot be checked through them. The parity suite
# (tests/parity) checks this module against the scalar path instead.
_pa: Any = pa
pc: Any = _compute


def columnar(executor: RowExecutor) -> bool:
    """Whether the stream's plan has vectorised columns worth a columnar run."""
    plan = executor.plan
    return not plan.shaped and plan.flattener is None and any(c.vector for c in plan.columns)


@dataclass
class ColumnarExecutor:
    """Runs one output stream's plan on Arrow batches."""

    executor: RowExecutor

    def run(
        self,
        table: pa.Table,
        *,
        passed: dict[str, Any],
        first_row: int,
        batched_at: str,
        reject: Callable[[RowRejected, dict[str, Any]], None],
    ) -> pa.Table:
        """The conformed batch; rejected and filtered rows are left out."""
        plan = self.executor.plan
        vectors = {
            i: column.vector.run(self._source(table, column.sources))
            for i, column in enumerate(plan.columns)
            if column.vector is not None
        }
        todo: dict[int, list[bool]] = {
            i: [bool(flag) for flag in mask.to_pylist()] for i, (_, mask) in vectors.items()
        }
        records = table.to_pylist()
        kept: list[int] = []
        outputs: list[dict[str, Any] | None] = []
        for n, record in enumerate(records):
            skip = frozenset(i for i, rows in todo.items() if not rows[n])
            try:
                out = self.executor.run(record, passed, first_row + n, batched_at=batched_at,
                                        skip=skip)  # fmt: skip
            except RowRejected as rejected:
                reject(rejected, record)
                out = None
            outputs.append(out)
            if out is not None:
                kept.append(n)
        return self._assemble(vectors, todo, outputs, kept)

    @staticmethod
    def _source(table: pa.Table, sources: tuple[str, ...]) -> pa.Array:
        present = [table.column(s).combine_chunks() for s in sources if s in table.column_names]
        if not present:
            return _pa.nulls(table.num_rows)
        if len(present) == 1 or len({a.type for a in present}) > 1:
            return present[0] if len(present) == 1 else _pa.nulls(table.num_rows)
        return pc.coalesce(*present)

    def _assemble(
        self,
        vectors: dict[int, tuple[pa.Array, pa.Array]],
        todo: dict[int, list[bool]],
        outputs: list[dict[str, Any] | None],
        kept: list[int],
    ) -> pa.Table:
        executor = self.executor
        columns = output_columns(executor.plan, metadata=executor.metadata is not None)
        schema = arrow_schema(columns)
        index = _pa.array(kept, type=pa.int64())
        arrays: list[pa.Array] = []
        for position, ((name, ctype, _), field) in enumerate(zip(columns, schema, strict=True)):
            if position in vectors:
                values, mask = vectors[position]
                rows = todo[position]
                spliced = [
                    arrow_value(out.get(name), ctype) if out is not None else None
                    for out, flag in zip(outputs, rows, strict=True)
                    if flag
                ]
                if spliced:
                    values = pc.replace_with_mask(values, mask, _pa.array(spliced, type=field.type))
                arrays.append(values.take(index))
            else:
                arrays.append(_pa.array(
                    [arrow_value(_get(outputs[n], name), ctype) for n in kept],
                    type=field.type,
                ))  # fmt: skip
        return _pa.Table.from_arrays(arrays, schema=schema)


def _get(out: dict[str, Any] | None, name: str) -> object:
    """A kept row's wire value (kept rows always have an output)."""
    return None if out is None else out.get(name)
