"""The row executor: run a StreamPlan on one record (detailed design §10.1).

Columns are computed in the plan's order, dependencies first. For each column: take the
first non-null source value, rename nested members, run the chain, apply the default, enforce
nullability and enum, and encode the result for the wire. Expressions see the typed values of
the columns computed before them. A value that fails follows the column's ``on_error``;
``reject`` raises :class:`~map_conform.errors.RowRejected` for the caller to route the whole
row. Last, the stream's ``filter`` decides whether the row is emitted at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from map_conform.errors import ConformError, RowRejected, StepFailed, apply_policy
from map_conform.expr.compiler import Row
from map_conform.metadata import SDC_PREFIX, Metadata
from map_conform.metrics import StreamMetrics
from map_conform.naming.nested import rename_value
from map_conform.plan.compile import StreamPlan
from map_conform.plan.ops import StepError
from map_conform.spec.model import Defaults
from map_conform.transforms.registry import Context
from map_conform.types.wire import to_wire

if TYPE_CHECKING:
    from collections.abc import Mapping

    from map_conform.expr.compiler import Expression
    from map_conform.plan.compile import ColumnPlan


@dataclass
class RowExecutor:
    """Conforms the records of one output stream."""

    plan: StreamPlan
    settings: Defaults
    metadata: Metadata | None = None
    metrics: StreamMetrics = field(default_factory=StreamMetrics)

    def __post_init__(self) -> None:
        """Build each column's context once."""
        self._nulled = False
        self._contexts = [
            Context(
                self.plan.tap_stream, column.name, self.settings, column.ctype, fake=self.plan.fake
            )
            for column in self.plan.columns
        ]

    def run(
        self, record: dict[str, Any], message: dict[str, Any], row: int
    ) -> dict[str, Any] | None:
        """The conformed record, ``_sdc_*`` columns included when metadata is on.

        Returns:
            The record, or None when the stream's filter drops it.

        Raises:
            ConformError: a value failed under ``on_error: raise``.
            RowRejected: a value failed under ``on_error: reject``.
        """
        self.metrics.rows_in += 1
        self._nulled = False
        state = Row.of(record, row)
        plan = self.plan
        sources = plan.flattener.record(record, plan.flat_properties) if plan.flattener else record
        wired: dict[str, Any] = {}
        columns = plan.columns
        for i in plan.order or range(len(columns)):
            column = columns[i]
            typed, wired[column.name] = self._column(column, self._contexts[i], state, sources, row)
            state.values[column.name] = typed
        if self._nulled:
            self.metrics.rows_nulled += 1
        if self.plan.filter is not None and not self._keep(self.plan.filter, state, row):
            self.metrics.rows_filtered += 1
            return None
        out = {column.name: wired[column.name] for column in columns}
        if self.metadata is not None:
            deleted_at = record.get(f"{SDC_PREFIX}deleted_at")
            try:
                self.metadata.add(out, message, deleted_at)
            except StepFailed as exc:
                error = self._error(
                    row, "_sdc_deleted_at", deleted_at, "_sdc_deleted_at", exc.reason
                )
                out["_sdc_deleted_at"] = apply_policy(self.settings.on_error, error, deleted_at)
        return out

    def _keep(self, row_filter: Expression, state: Row, row: int) -> bool:
        """Whether the filter keeps the row.

        A failing filter follows the stream's on_error: ``null`` drops the row (the filter is
        null, so falsy) and ``keep`` keeps it.
        """
        try:
            return bool(row_filter.evaluate(state))
        except StepFailed as exc:
            error = self._error(row, "filter", None, f"filter: {row_filter.text}", exc.reason)
            policy = self.settings.on_error
            if policy == "raise":
                raise error from None
            if policy == "reject":
                raise RowRejected(error) from None
            return policy == "keep"

    def _column(
        self, column: ColumnPlan, ctx: Context, state: Row, sources: Mapping[str, Any], row: int
    ) -> tuple[object, object]:
        """The column's typed value (what later expressions see) and its wire value."""
        raw = next((sources[s] for s in column.sources if sources.get(s) is not None), None)
        if raw is not None and column.member_names is not None:
            raw = rename_value(_decode(raw), column.member_names)
        try:
            value = column.chain.run(raw, ctx, state)
        except StepError as exc:
            error = self._error(row, column.name, raw, exc.cell.rule, exc.cell.reason)
            if column.on_error == "null" and not column.nullable:
                raise error from exc
            kept = self._handle(column, error, raw)
            return kept, kept
        if value is None:
            value = column.default
        if value is None:
            if not column.nullable:
                raise self._error(row, column.name, raw, "nullable: false", "the value is null")
            return None, None
        wired = to_wire(value, column.ctype)
        if column.enum is not None and wired not in column.enum:
            error = self._error(row, column.name, raw, "enum", f"{wired!r} is not allowed")
            kept = self._handle(column, error, raw)
            return kept, kept
        return value, wired

    def _handle(self, column: ColumnPlan, error: ConformError, raw: object) -> object:
        """Count a failed value and apply the column's on_error."""
        self.metrics.errors[(column.name, error.rule)] += 1
        if column.on_error == "null":
            self._nulled = True
        elif column.on_error == "keep":
            self.metrics.values_kept += 1
        return apply_policy(column.on_error, error, raw)

    def _error(self, row: int, column: str, value: object, rule: str, reason: str) -> ConformError:
        return ConformError(
            stream=self.plan.tap_stream,
            column=column,
            row=row,
            value=value,
            rule=rule,
            reason=reason,
        )


def _decode(value: object) -> object:
    """JSON text for a nested column, decoded so its keys can be renamed."""
    if isinstance(value, str):
        try:
            return json.loads(value, parse_float=Decimal)
        except json.JSONDecodeError:
            return value
    return value
