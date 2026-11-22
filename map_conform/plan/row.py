"""The row executor: run a StreamPlan on one record (detailed design §10.1).

For each column: take the first non-null source value, rename nested members, run the chain,
apply the default, enforce nullability and enum, and encode the result for the wire. A value
that fails follows the column's ``on_error``; ``reject`` raises
:class:`~map_conform.errors.RowRejected` for the caller to route the whole row.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from map_conform.errors import ConformError, StepFailed, apply_policy
from map_conform.metadata import SDC_PREFIX, Metadata
from map_conform.metrics import StreamMetrics
from map_conform.naming.nested import rename_value
from map_conform.plan.chain import StepError
from map_conform.plan.compile import StreamPlan
from map_conform.spec.model import Defaults
from map_conform.transforms.registry import Context
from map_conform.types.wire import to_wire

if TYPE_CHECKING:
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
            Context(self.plan.tap_stream, column.name, self.settings, column.ctype)
            for column in self.plan.columns
        ]

    def run(self, record: dict[str, Any], message: dict[str, Any], row: int) -> dict[str, Any]:
        """The conformed record, ``_sdc_*`` columns included when metadata is on.

        Raises:
            ConformError: a value failed under ``on_error: raise``.
            RowRejected: a value failed under ``on_error: reject``.
        """
        self.metrics.rows_in += 1
        self._nulled = False
        out: dict[str, Any] = {}
        for column, ctx in zip(self.plan.columns, self._contexts, strict=True):
            out[column.name] = self._column(column, ctx, record, row)
        if self._nulled:
            self.metrics.rows_nulled += 1
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

    def _column(self, column: ColumnPlan, ctx: Context, record: dict[str, Any], row: int) -> object:
        raw = next((record[s] for s in column.sources if record.get(s) is not None), None)
        if raw is not None and column.member_names is not None:
            raw = rename_value(_decode(raw), column.member_names)
        try:
            value = column.chain.run(raw, ctx)
        except StepError as exc:
            error = self._error(row, column.name, raw, exc.cell.rule, exc.cell.reason)
            if column.on_error == "null" and not column.nullable:
                raise error from exc
            return self._handle(column, error, raw)
        if value is None:
            value = column.default
        if value is None:
            if not column.nullable:
                raise self._error(row, column.name, raw, "nullable: false", "the value is null")
            return None
        wired = to_wire(value, column.ctype)
        if column.enum is not None and wired not in column.enum:
            error = self._error(row, column.name, raw, "enum", f"{wired!r} is not allowed")
            return self._handle(column, error, raw)
        return wired

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
