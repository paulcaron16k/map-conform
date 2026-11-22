"""Run the same rows through the row executor and the columnar executor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pyarrow as pa

from map_conform.batch.arrow import output_columns, to_table
from map_conform.batch.columnar import ColumnarExecutor
from map_conform.errors import ConformError, RowRejected
from map_conform.plan.compile import compile_stream
from map_conform.plan.row import RowExecutor
from map_conform.spec.load import resolve_stream
from map_conform.spec.model import parse_spec
from map_conform.transforms.builtins import builtin_registry


@dataclass
class Outcome:
    """What one executor made of the rows."""

    table: pa.Table | None
    rejected: list[int] = field(default_factory=list)
    error: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)


def _executor(spec: dict[str, Any], properties: dict[str, Any]) -> RowExecutor:
    parsed = parse_spec({"version": 1, **spec})
    resolved = resolve_stream(parsed, "s")
    assert resolved is not None
    plan = compile_stream(parsed, resolved, {"properties": properties}, builtin_registry())
    return RowExecutor(plan, resolved.settings)


def row_path(spec: dict[str, Any], properties: dict[str, Any], table: pa.Table) -> Outcome:
    """The RECORD path: row by row, wire values, then Arrow."""
    executor = _executor(spec, properties)
    rows, rejected = [], []
    try:
        for n, record in enumerate(table.to_pylist(), 1):
            try:
                out = executor.run(record, {}, n, batched_at="2026-01-01T00:00:00+00:00")
            except RowRejected:
                rejected.append(n)
                continue
            if out is not None:
                rows.append(out)
    except ConformError as exc:
        return Outcome(None, rejected, str(exc), executor.metrics.to_dict())
    columns = output_columns(executor.plan, metadata=False)
    return Outcome(to_table(rows, columns), rejected, None, executor.metrics.to_dict())


def columnar_path(spec: dict[str, Any], properties: dict[str, Any], table: pa.Table) -> Outcome:
    """The columnar executor on the whole table."""
    executor = _executor(spec, properties)
    rejected: list[int] = []

    def reject(error: RowRejected, _record: dict[str, Any]) -> None:
        assert error.error.row is not None
        rejected.append(error.error.row)

    try:
        out = ColumnarExecutor(executor).run(
            table, passed={}, first_row=1, batched_at="2026-01-01T00:00:00+00:00", reject=reject
        )
    except ConformError as exc:
        return Outcome(None, rejected, str(exc), executor.metrics.to_dict())
    return Outcome(out, rejected, None, executor.metrics.to_dict())


def assert_parity(spec: dict[str, Any], properties: dict[str, Any], table: pa.Table) -> Outcome:
    """Both executors give the same table, rejects, error and metrics."""
    row = row_path(spec, properties, table)
    col = columnar_path(spec, properties, table)
    assert col.error == row.error
    assert col.rejected == row.rejected
    assert col.metrics == row.metrics
    if row.table is not None:
        assert col.table is not None
        assert col.table.schema == row.table.schema
        assert col.table.to_pylist() == row.table.to_pylist()
    return row
