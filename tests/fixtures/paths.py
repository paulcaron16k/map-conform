"""Locate fixtures and resolve the BATCH manifest placeholder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.fixtures.generate import MANIFEST_DIR_PLACEHOLDER

FIXTURES = Path(__file__).resolve().parent


def messages(name: str) -> list[dict[str, Any]]:
    """The Singer messages in ``streams/<name>``, with manifests pointing at this checkout."""
    text = (FIXTURES / "streams" / name).read_text(encoding="utf-8")
    text = text.replace(MANIFEST_DIR_PLACEHOLDER, FIXTURES.as_posix())
    return [json.loads(line) for line in text.splitlines()]
