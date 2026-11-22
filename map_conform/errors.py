"""Runtime conform errors and the on_error policy (detailed design §12).

A :class:`ConformError` names the stream, column, row, value and rule, so a data engineer can
find the bad cell and decide: fix the cleanup in the spec, or drop the column. The default
policy is ``raise``; ``null`` and ``keep`` trade correctness for continuity, and ``reject``
sends the row to the dead-letter sink.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

OnError = Literal["raise", "null", "keep", "reject"]

_VALUE_PREVIEW = 80


@dataclass(frozen=True)
class CellError:
    """What went wrong with one value, before the row context is known."""

    rule: str
    """The step that failed, e.g. ``cast: decimal(10,2)`` or ``strip_chars``."""
    reason: str


class ConformError(ValueError):
    """A value that could not be conformed, with everything needed to find and fix it."""

    def __init__(  # noqa: PLR0913 -- the context is the point of this error
        self,
        *,
        stream: str,
        column: str,
        row: int | None,
        value: object,
        rule: str,
        reason: str,
    ) -> None:
        """Record the context and build a one-line message."""
        self.stream = stream
        self.column = column
        self.row = row
        self.value = value
        self.rule = rule
        self.reason = reason
        where = f"row {row}" if row is not None else "a row"
        shown = repr(value)
        if len(shown) > _VALUE_PREVIEW:
            shown = shown[: _VALUE_PREVIEW - 3] + "..."
        super().__init__(
            f"stream {stream!r}, column {column!r}, {where}: {rule} failed on {shown}: {reason}. "
            "Fix the column's transform in the spec, set on_error, or drop the column."
        )


class StepFailed(Exception):  # noqa: N818 -- raised by a step to signal a CellError
    """Raised inside a transform; the executor adds the row context."""

    def __init__(self, reason: str) -> None:
        """Say why the value failed."""
        self.reason = reason
        super().__init__(reason)


class RowRejected(Exception):  # noqa: N818 -- a control-flow signal, not a failure
    """The row goes to the dead-letter sink (on_error: reject)."""

    def __init__(self, error: ConformError) -> None:
        """Keep the error that rejected the row."""
        self.error = error
        super().__init__(str(error))


def apply_policy(policy: OnError, error: ConformError, raw: object) -> object:
    """What a failed value becomes under ``policy``.

    Returns:
        None for ``null``; the raw input value for ``keep``.

    Raises:
        ConformError: for ``raise``.
        RowRejected: for ``reject``.
    """
    if policy == "null":
        return None
    if policy == "keep":
        return raw
    if policy == "reject":
        raise RowRejected(error)
    raise error
