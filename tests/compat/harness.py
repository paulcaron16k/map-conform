"""Run a stream-map case through the Singer SDK's PluginMapper and through map-conform."""

from __future__ import annotations

import copy
import io
import json
import logging
from contextlib import redirect_stdout
from typing import TYPE_CHECKING, Any

from singer_sdk.mapper import PluginMapper, RemoveRecordTransform

from map_conform.mapper import MapConformMapper
from map_conform.types.jsontext import dumps

if TYPE_CHECKING:
    from tests.compat.sdk_cases import Stream

Message = tuple[str, str, Any, Any]
"""(type, stream, schema or record, key properties)."""


def sdk_run(
    streams: dict[str, Stream], stream_maps: dict[str, Any], config: dict[str, Any]
) -> list[Message]:
    """The messages an SDK inline mapper emits for these streams."""
    mapper = PluginMapper(
        plugin_config={"stream_maps": copy.deepcopy(stream_maps), **copy.deepcopy(config)},
        logger=logging.getLogger("sdk-parity"),
    )
    out: list[Message] = []
    for name, (schema, keys, records) in streams.items():
        mapper.register_raw_stream_schema(name, copy.deepcopy(schema), keys)
        maps = [m for m in mapper.stream_maps[name] if not isinstance(m, RemoveRecordTransform)]
        out.extend(
            (
                "SCHEMA",
                m.stream_alias,
                m.transformed_schema,
                list(m.transformed_key_properties or []),
            )
            for m in maps
        )
        for record in records:
            for m in maps:
                result = m.transform(copy.deepcopy(record))
                if result is not None:
                    out.append(("RECORD", m.stream_alias, result, None))
    return out


def ours_run(
    streams: dict[str, Stream], stream_maps: dict[str, Any] | None, config: dict[str, Any]
) -> list[Message]:
    """The messages map-conform emits for the same input and settings (no stream_maps: None)."""
    lines: list[str] = []
    for name, (schema, keys, records) in streams.items():
        lines.append(
            json.dumps({"type": "SCHEMA", "stream": name, "schema": schema, "key_properties": keys})
        )
        lines.extend(dumps({"type": "RECORD", "stream": name, "record": r}) for r in records)
    settings = {**config} if stream_maps is None else {"stream_maps": stream_maps, **config}
    mapper = MapConformMapper(config=settings)
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        mapper.listen(io.StringIO("\n".join(lines) + "\n"))
    out: list[Message] = []
    for line in buffer.getvalue().splitlines():
        message = json.loads(line)
        if message["type"] == "SCHEMA":
            out.append(("SCHEMA", message["stream"], message["schema"], message["key_properties"]))
        elif message["type"] == "RECORD":
            out.append(("RECORD", message["stream"], message["record"], None))
    return out
