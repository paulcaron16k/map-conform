"""Reserved-word lists per SQL dialect (data files in ``reserved/``).

Each list holds the words that dialect will not accept as an unquoted column name. The
sources, versions and selection rules are in each file's header. The default dialects are
postgres, duckdb and snowflake; ``ansi`` (SQL:2016) is opt-in because it reserves common
column names such as ``date``, ``year`` and ``value``.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

DATA = Path(__file__).resolve().parent / "reserved"


@functools.cache
def dialect_words(dialect: str) -> frozenset[str]:
    """The reserved words of one dialect, lowercase."""
    text = (DATA / f"{dialect}.txt").read_text(encoding="utf-8")
    return frozenset(
        line.strip().lower()
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    )


def reserved_words(dialects: Iterable[str]) -> frozenset[str]:
    """The union of the given dialects' reserved words."""
    return frozenset().union(*(dialect_words(d) for d in dialects))
