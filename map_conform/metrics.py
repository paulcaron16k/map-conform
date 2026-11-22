"""Per-stream counters (detailed design §13).

Counted per output stream: rows in and out, rejected rows, rows where ``on_error: null``
replaced a value, values kept raw (``keep``), and errors by (column, rule). They are logged
at the end of the run and, with ``metrics_path``, written as JSON.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class StreamMetrics:
    """Counters for one output stream."""

    rows_in: int = 0
    rows_out: int = 0
    rows_rejected: int = 0
    rows_nulled: int = 0
    rows_filtered: int = 0
    """Rows the stream's filter dropped."""
    values_kept: int = 0
    errors: Counter[tuple[str, str]] = field(default_factory=Counter)
    """Failed values by (column, rule), whatever on_error did with them."""

    def rate(self, count: int) -> float:
        """``count`` as a fraction of rows in."""
        return count / self.rows_in if self.rows_in else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Plain data for the metrics file and log lines."""
        return {
            "rows_in": self.rows_in,
            "rows_out": self.rows_out,
            "rows_rejected": self.rows_rejected,
            "rows_nulled": self.rows_nulled,
            "rows_filtered": self.rows_filtered,
            "values_kept": self.values_kept,
            "errors": [
                {"column": column, "rule": rule, "count": count}
                for (column, rule), count in sorted(self.errors.items())
            ],
        }


def write_metrics(path: str | Path, streams: dict[str, StreamMetrics]) -> None:
    """Write every stream's counters to ``path`` as JSON."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    document = {"streams": {name: m.to_dict() for name, m in sorted(streams.items())}}
    target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
