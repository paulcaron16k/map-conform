"""Stream-level source: copy or split a tap stream into several outputs (WBS 12.3)."""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING, Any

from map_conform.mapper import MapConformMapper

if TYPE_CHECKING:
    import pytest

SCHEMA = {
    "type": "SCHEMA",
    "stream": "orders",
    "schema": {
        "properties": {
            "id": {"type": "integer"},
            "region": {"type": "string"},
            "card": {"type": "string"},
        }
    },
    "key_properties": ["id"],
}


def record(n: int, region: str) -> dict[str, Any]:
    """An orders RECORD."""
    return {"type": "RECORD", "stream": "orders",
            "record": {"id": n, "region": region, "card": f"4111-{n}"}}  # fmt: skip


def state(n: int) -> dict[str, Any]:
    """A STATE after row n."""
    return {"type": "STATE", "value": {"bookmarks": {"orders": {"id": n}}}}


def run(spec: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> list[tuple[str, Any]]:
    """(stream or STATE, record or bookmark) for each message written."""
    mapper = MapConformMapper(config={"spec": {"version": 1, **spec}})
    messages = [SCHEMA, record(1, "eu"), state(1), record(2, "us"), state(2)]
    capsys.readouterr()
    mapper.listen(io.StringIO("".join(json.dumps(m) + "\n" for m in messages)))
    out = []
    for line in capsys.readouterr().out.splitlines():
        message = json.loads(line)
        if message["type"] == "RECORD":
            out.append((message["stream"], message["record"]))
        elif message["type"] == "STATE":
            out.append(("STATE", message["value"]["bookmarks"]["orders"]["id"]))
    return out


def test_copy_keeps_the_original_and_state_order(capsys: pytest.CaptureFixture[str]) -> None:
    """A masked copy beside the original; each STATE follows the rows before it."""
    spec = {
        "defaults": {"metadata": "none"},
        "streams": {
            "orders_masked": {
                "source": "orders",
                "columns": {"card": {"transform": {"mask": {"keep_last": 2}}}},
            }
        },
    }
    assert run(spec, capsys) == [
        ("orders", {"id": 1, "region": "eu", "card": "4111-1"}),
        ("orders_masked", {"id": 1, "region": "eu", "card": "****-1"}),
        ("STATE", 1),
        ("orders", {"id": 2, "region": "us", "card": "4111-2"}),
        ("orders_masked", {"id": 2, "region": "us", "card": "****-2"}),
        ("STATE", 2),
    ]


def test_split_by_filter(capsys: pytest.CaptureFixture[str]) -> None:
    """One tap stream split by region (read from the source: it is not an output column)."""
    spec = {
        "defaults": {"metadata": "none", "undeclared": "drop"},
        "streams": {
            "orders": {"drop": True},
            "orders_eu": {"source": "orders", "filter": "record['region'] == 'eu'"},
            "orders_us": {"source": "o*", "filter": "record['region'] == 'us'"},
        },
    }
    assert run(spec, capsys) == [
        ("orders_eu", {"id": 1}),
        ("STATE", 1),
        ("orders_us", {"id": 2}),
        ("STATE", 2),
    ]
