"""The dead-letter sink for rows rejected under ``on_error: reject`` (detailed design §12).

Each rejected row is written with its stream, row number, the column and rule that failed,
the error message, the offending value and the whole raw record, so it can be fixed and
replayed. Files go to ``<reject.storage>/<stream>/<run id>.jsonl`` (or ``.parquet``).
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Literal

import pyarrow as pa
import pyarrow.parquet as pq

if TYPE_CHECKING:
    from map_conform.errors import ConformError

_COLUMNS = ("stream", "row_number", "column", "rule", "error", "value", "record", "rejected_at")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=_default)


def _default(value: object) -> object:
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


@dataclass
class RejectSink:
    """Writes rejected rows, one file per stream for the run."""

    storage: Path
    format: Literal["jsonl", "parquet"]
    run_id: str
    _files: dict[str, IO[str]] = field(default_factory=dict)
    _buffers: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    paths: dict[str, Path] = field(default_factory=dict)

    def write(self, stream: str, error: ConformError, record: dict[str, Any]) -> None:
        """Record one rejected row."""
        row = {
            "stream": stream,
            "row_number": error.row,
            "column": error.column,
            "rule": error.rule,
            "error": str(error),
            "value": _json(error.value),
            "record": _json(record),
            "rejected_at": dt.datetime.now(tz=dt.UTC).isoformat(),
        }
        if self.format == "jsonl":
            self._file(stream).write(json.dumps(row, ensure_ascii=False) + "\n")
        else:
            self._buffers.setdefault(stream, []).append(row)
            self.paths.setdefault(stream, self._path(stream))

    def _path(self, stream: str) -> Path:
        directory = self.storage / stream
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{self.run_id}.{self.format}"

    def _file(self, stream: str) -> IO[str]:
        if stream not in self._files:
            path = self.paths[stream] = self._path(stream)
            self._files[stream] = path.open("a", encoding="utf-8")
        return self._files[stream]

    def close(self) -> None:
        """Flush and close every file."""
        for handle in self._files.values():
            handle.close()
        self._files.clear()
        for stream, rows in self._buffers.items():
            table = pa.Table.from_pylist(
                rows,
                schema=pa.schema(
                    [
                        ("row_number", pa.int64()) if c == "row_number" else (c, pa.string())
                        for c in _COLUMNS
                    ]
                ),
            )
            pq.write_table(table, self.paths[stream])
        self._buffers.clear()
