"""The bundled transliteration table (ADR-0012)."""

from __future__ import annotations

import json
import unicodedata

import pytest

from map_conform.naming.translit import (
    RANGES,
    TABLE_PATH,
    UNICODE_VERSION,
    render_table,
    table,
    transliterate,
)


def test_table_records_its_pinned_unicode_version() -> None:
    """The committed table was built from the pinned Unicode version."""
    document = json.loads(TABLE_PATH.read_text(encoding="utf-8"))
    assert document["unicode_version"] == UNICODE_VERSION


@pytest.mark.skipif(
    unicodedata.unidata_version != UNICODE_VERSION,
    reason=f"the table is pinned to Unicode {UNICODE_VERSION}; checked on the Python that has it",
)
def test_table_is_current() -> None:
    """Regenerating the table changes nothing."""
    assert TABLE_PATH.read_text(encoding="utf-8") == render_table(), (
        "run `uv run --python 3.14 python -m map_conform.naming.translit`"
    )


def test_table_covers_only_its_ranges_and_maps_to_ascii() -> None:
    """Keys come from the documented blocks; values are ASCII letters (or empty)."""
    for char, ascii_ in table().items():
        code = ord(char)
        assert any(start <= code <= end for start, end, _ in RANGES), char
        assert ascii_.isascii()
        assert ascii_.isalpha() or ascii_ == "", (char, ascii_)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ünïcode Näme", "Unicode Name"),
        ("Straße", "Strasse"),
        ("Łódź", "Lodz"),
        ("Θεός", "Theos"),
        ("ΘΕΟΣ", "THEOS"),
        ("Жук", "Zhuk"),
        ("ЖУК", "ZHUK"),
        ("объект", "obekt"),
        ("Ærø", "Aero"),
    ],
)
def test_transliterate(text: str, expected: str) -> None:
    """Decomposition, the supplement and context-sensitive capitals."""
    assert transliterate(text) == (expected, "")


def test_unmapped_characters_are_reported() -> None:
    """Characters outside the table are dropped and returned."""
    assert transliterate("A日€b") == ("Ab", "日€")
