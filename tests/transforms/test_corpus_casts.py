"""The string, boolean and uuid corpus tables pass with the real casts (WBS 5.2, 5.5)."""

from __future__ import annotations

import pytest

from tests.transforms.corpus import Case, cases, run_case

TABLES = ["text.csv", "boolean.csv", "uuid.csv"]


@pytest.mark.parametrize("case", [c for t in TABLES for c in cases(t)], ids=lambda c: c.case)
def test_corpus(case: Case) -> None:
    """Each case gives its expected wire value, null or error."""
    assert run_case(case) == case.expected, case.note
