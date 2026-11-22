"""Errors raised for an invalid spec."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from map_conform.spec._struct import Issue


class SpecError(ValueError):
    """A spec with one or more problems; ``issues`` lists every one with its path."""

    def __init__(self, issues: Sequence[Issue], source: str | None = None) -> None:
        """Keep the issues and build a message listing them."""
        self.issues = tuple(issues)
        self.source = source
        where = f" in {source}" if source else ""
        lines = "\n".join(f"  {issue}" for issue in self.issues)
        super().__init__(f"{len(self.issues)} problem(s){where}:\n{lines}")
