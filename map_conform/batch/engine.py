"""Conform a BATCH message (detailed design §10.3, WBS 8.1-8.3 and 8.8).

Each manifest file is read in chunks and every row is conformed by the stream's executors,
exactly as a RECORD would be: the same plan, ``on_error``, rejects, filter and metrics.
Then, per ``batch_output.mode``:

- ``batch``: one output file per input file and output stream, in the input's order, then one
  BATCH message per output stream listing its files (``version`` and ``time_extracted``
  passed on);
- ``record``: RECORD messages, for targets that do not read BATCH.

``_sdc_batched_at`` is the input file's last-modified time. With ``delete_input`` each input
file is deleted once every output written from it is complete.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from map_conform.batch.arrow import output_columns
from map_conform.batch.files import (
    Writer,
    compression_for,
    delete,
    last_modified,
    output_uri,
    read_rows,
)
from map_conform.errors import RowRejected
from map_conform.settings import BatchOutputSettings

if TYPE_CHECKING:
    from map_conform.plan.row import RowExecutor

Reject = Callable[["RowExecutor", RowRejected, dict[str, Any]], None]
"""The mapper's reject handler: counts the row and writes it to the reject sink."""


@dataclass
class BatchEngine:
    """Conforms the BATCH messages of one run."""

    settings: BatchOutputSettings
    run_id: str
    reject: Reject
    rows: dict[str, int] = field(default_factory=dict)
    """Rows seen per tap stream, shared with the RECORD path."""
    _numbers: dict[str, int] = field(default_factory=dict)

    def process(
        self, message: dict[str, Any], executors: list[RowExecutor]
    ) -> Iterator[dict[str, Any]]:
        """The messages that replace one BATCH message."""
        tap_stream = message["stream"]
        passed: dict[str, Any] = {
            k: message[k] for k in ("version", "time_extracted") if k in message
        }
        manifests: dict[int, list[str]] = {id(e): [] for e in executors}
        params = self.settings.storage.params
        for uri in message.get("manifest", []):
            batched_at = last_modified(uri, params).isoformat()
            writers: dict[int, Writer] = {}
            for chunk in read_rows(uri, message.get("encoding") or {}, params,
                                   self.settings.row_group_size):  # fmt: skip
                yield from self._chunk(
                    chunk,
                    tap_stream=tap_stream,
                    executors=executors,
                    passed=passed,
                    batched_at=batched_at,
                    uri=uri,
                    writers=writers,
                )
            for executor in executors:
                writer = writers.get(id(executor))
                if writer is not None:
                    writer.close()
                    manifests[id(executor)].append(writer.uri)
            if self.settings.delete_input:
                delete(uri, params)
        if self.settings.mode == "batch":
            fmt = self.settings.format
            encoding = {
                "format": fmt,
                "compression": compression_for(fmt, self.settings.compression),
            }
            for executor in executors:
                files = manifests[id(executor)]
                if files:
                    yield {"type": "BATCH", "stream": executor.plan.name, "encoding": encoding,
                           "manifest": files, **passed}  # fmt: skip

    def _chunk(  # noqa: PLR0913 -- the chunk and where it goes
        self,
        chunk: list[dict[str, Any]],
        *,
        tap_stream: str,
        executors: list[RowExecutor],
        passed: dict[str, Any],
        batched_at: str,
        uri: str,
        writers: dict[int, Writer],
    ) -> Iterator[dict[str, Any]]:
        buffers: dict[int, list[dict[str, Any]]] = {id(e): [] for e in executors}
        for record in chunk:
            row = self.rows[tap_stream] = self.rows.get(tap_stream, 0) + 1
            for executor in executors:
                try:
                    out = executor.run(record, passed, row, batched_at=batched_at)
                except RowRejected as rejected:
                    self.reject(executor, rejected, record)
                    continue
                if out is None:
                    continue
                executor.metrics.rows_out += 1
                if self.settings.mode == "record":
                    yield {"type": "RECORD", "stream": executor.plan.name, "record": out, **passed}
                else:
                    buffers[id(executor)].append(out)
        if self.settings.mode == "batch":
            for executor in executors:
                rows = buffers[id(executor)]
                if rows:
                    self._writer(executor, uri, writers).write(rows)

    def _writer(self, executor: RowExecutor, uri: str, writers: dict[int, Writer]) -> Writer:
        writer = writers.get(id(executor))
        if writer is None:
            stream = executor.plan.name
            number = self._numbers[stream] = self._numbers.get(stream, 0) + 1
            fmt = self.settings.format
            compression = compression_for(fmt, self.settings.compression)
            root = self.settings.storage.root or uri.rsplit("/", 1)[0]
            target = output_uri(root, stream, self.run_id, number, fmt=fmt, compression=compression)
            columns = output_columns(executor.plan, metadata=executor.metadata is not None)
            writer = writers[id(executor)] = Writer(
                target, self.settings.storage.params, fmt=fmt, compression=compression,
                columns=columns, row_group_size=self.settings.row_group_size,
            )  # fmt: skip
        return writer
