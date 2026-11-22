"""BATCH file I/O over fsspec: manifest files in, conformed files out (WBS 8.1-8.3).

- **Input.** Each manifest URI is opened with fsspec (``file://``, ``memory://``, ``s3://``
  with the ``s3`` extra, …) using ``batch_output.storage.params``. JSONL is read line by line,
  gzipped or plain, with fractions as exact decimals, as the Singer SDK decodes them. Parquet
  is read in row groups of ``row_group_size`` rows, so a large file never sits in memory.
- **Last modified.** ``_sdc_batched_at`` is the input file's last-modified time from
  fsspec ``info()``, or the time it was opened for stores that do not report one.
- **Output.** ``<root>/<stream>/<run id>-<n>.parquet`` (or ``.jsonl``/``.jsonl.gz``), where
  root is ``batch_output.storage.root`` or the input file's directory. Parquet is written
  with the plan's declared Arrow schema; JSONL with the RECORD path's wire values.
"""

from __future__ import annotations

import datetime as dt
import gzip
import io
import json
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

import fsspec
import pyarrow as pa
import pyarrow.parquet as pq

from map_conform.batch.arrow import to_table
from map_conform.types.jsontext import dumps

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from map_conform.types.canonical import CType

_COMPRESSION_DEFAULTS = {"parquet": "zstd", "jsonl": "gzip"}
_EXTENSIONS = {"parquet": ".parquet", "jsonl": ".jsonl"}


class BatchFileError(ValueError):
    """A manifest file that cannot be read, or an encoding map-conform does not read."""


def _fs(uri: str, params: Mapping[str, Any]) -> tuple[fsspec.AbstractFileSystem, str]:
    fs, path = fsspec.core.url_to_fs(uri, **dict(params))
    return fs, path


def last_modified(uri: str, params: Mapping[str, Any]) -> dt.datetime:
    """The file's last-modified time, in UTC (now, when the store does not say)."""
    fs, path = _fs(uri, params)
    try:
        modified = fs.modified(path)
    except (NotImplementedError, OSError, KeyError):
        return dt.datetime.now(tz=dt.UTC)
    return (
        modified.replace(tzinfo=dt.UTC) if modified.tzinfo is None else modified.astimezone(dt.UTC)
    )


def read_rows(
    uri: str, encoding: Mapping[str, Any], params: Mapping[str, Any], chunk: int
) -> Iterator[list[dict[str, Any]]]:
    """The file's records, in chunks of at most ``chunk`` rows.

    Raises:
        BatchFileError: for an unknown format or compression, or an unreadable file.
    """
    fmt = encoding.get("format")
    compression = encoding.get("compression") or "none"
    fs, path = _fs(uri, params)
    try:
        if fmt == "jsonl":
            yield from _jsonl(fs, path, compression, chunk)
        elif fmt == "parquet":
            with fs.open(path, "rb") as handle:
                for batch in pq.ParquetFile(handle).iter_batches(batch_size=chunk):
                    yield batch.to_pylist()
        else:
            msg = f"BATCH format {fmt!r} is not supported (jsonl or parquet)"
            raise BatchFileError(msg)
    except (OSError, pa.ArrowException, json.JSONDecodeError) as exc:
        msg = f"cannot read {uri}: {exc}"
        raise BatchFileError(msg) from exc


def _jsonl(
    fs: fsspec.AbstractFileSystem, path: str, compression: str, chunk: int
) -> Iterator[list[dict[str, Any]]]:
    if compression not in {"gzip", "none"}:
        msg = f"JSONL compression {compression!r} is not supported (gzip or none)"
        raise BatchFileError(msg)
    with fs.open(path, "rb") as raw, _text_reader(raw, compression) as handle:
        rows: list[dict[str, Any]] = []
        for line in handle:
            if line.strip():
                rows.append(json.loads(line, parse_float=Decimal))
            if len(rows) >= chunk:
                yield rows
                rows = []
        if rows:
            yield rows


def _text_reader(raw: Any, compression: str) -> Any:  # noqa: ANN401 -- a binary file object
    """A text reader over a binary file, gunzipping when asked."""
    if compression == "gzip":
        return gzip.open(raw, "rt", encoding="utf-8")
    return io.TextIOWrapper(raw, encoding="utf-8")


def compression_for(fmt: str, configured: str | None) -> str:
    """The output compression: the configured one, or the format's default."""
    return configured or _COMPRESSION_DEFAULTS[fmt]


def output_uri(  # noqa: PLR0913 -- the parts of the name
    root: str, stream: str, run_id: str, number: int, *, fmt: str, compression: str
) -> str:
    """``<root>/<stream>/<run id>-<n>.<ext>``."""
    extension = _EXTENSIONS[fmt] + (".gz" if fmt == "jsonl" and compression == "gzip" else "")
    return f"{root.rstrip('/')}/{stream}/{run_id}-{number:04d}{extension}"


class Writer:
    """Writes one output file, chunk by chunk."""

    def __init__(  # noqa: PLR0913 -- the file's whole description
        self,
        uri: str,
        params: Mapping[str, Any],
        *,
        fmt: str,
        compression: str,
        columns: Sequence[tuple[str, CType, bool]],
        row_group_size: int,
    ) -> None:
        """Open ``uri`` for writing, creating its directory."""
        self.uri = uri
        self.columns = columns
        self.fmt = fmt
        self.rows = 0
        self.row_group_size = row_group_size
        fs, path = _fs(uri, params)
        fs.makedirs(path.rsplit("/", 1)[0], exist_ok=True)
        self._handle = fs.open(path, "wb")
        self._parquet: pq.ParquetWriter | None = None
        self._text: Any = None
        if fmt == "parquet":
            codec = None if compression == "none" else compression
            schema = to_table([], columns).schema
            self._parquet = pq.ParquetWriter(self._handle, schema, compression=cast("Any", codec))
        elif compression == "gzip":
            self._text = gzip.open(self._handle, "wt", encoding="utf-8")  # noqa: SIM115 -- close()
        else:
            self._text = io.TextIOWrapper(self._handle, encoding="utf-8")

    def write(self, rows: Sequence[Mapping[str, Any]]) -> None:
        """Append conformed rows (wire values)."""
        if not rows:
            return
        self.rows += len(rows)
        if self._parquet is not None:
            self._parquet.write_table(
                to_table(rows, self.columns), row_group_size=self.row_group_size
            )
        else:
            self._text.write("".join(dumps(dict(row), compact=True) + "\n" for row in rows))

    def close(self) -> None:
        """Finish the file."""
        if self._parquet is not None:
            self._parquet.close()
        else:
            self._text.close()
        if not self._handle.closed:
            self._handle.close()


def delete(uri: str, params: Mapping[str, Any]) -> None:
    """Remove an input file."""
    fs, path = _fs(uri, params)
    fs.rm(path)
