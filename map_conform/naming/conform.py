"""Conform names so that every target accepts them (detailed design §5).

The pipeline is pure and deterministic, and each step follows the ``naming`` defaults:

1. Unicode NFKC normalisation.
2. ASCII: transliterate with the bundled table (ADR-0012), strip, or keep.
3. Split camelCase and acronym boundaries (``customerID`` -> ``customer_ID``,
   ``HTTPServer`` -> ``HTTP_Server``); a plural acronym stays whole (``IDs``).
4. Apply the case.
5. Replace characters outside the allowed set (``[a-z0-9_]`` for snake/lower).
6. Collapse runs of ``_`` and trim it from both ends.
7. A leading digit: prefix ``_``, turn it into a letter (SDK style) or fail.
8. An empty result becomes ``col_<n>``, where n is the source ordinal.

Running the pipeline on its own output changes nothing.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from map_conform.naming.translit import transliterate

if TYPE_CHECKING:
    from collections.abc import Iterable

    from map_conform.spec.model import NamingDefaults

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
# An acronym followed by a capitalised word splits before the word (HTTP_Server), but a
# plural acronym (IDs, URLs) stays whole.
_ACRONYM = re.compile(r"(?<=[A-Z])(?=[A-Z](?!s(?![a-z]))[a-z])")
_RUNS = re.compile(r"_+")
_SEPARATORS = frozenset(" \t\n\r-_.()[]{}/\\:,;'\"")
_ALLOWED = {
    "snake": re.compile(r"[^a-z0-9_]"),
    "lower": re.compile(r"[^a-z0-9_]"),
    "upper": re.compile(r"[^A-Z0-9_]"),
    "preserve": re.compile(r"[^A-Za-z0-9_]"),
}
_ALLOWED_UNICODE = re.compile(r"[^\w]")


class NamingError(ValueError):
    """A name that cannot be conformed under the configured policy."""

    def __init__(self, source: str, reason: str) -> None:
        """Name the source and say why."""
        self.source = source
        self.reason = reason
        super().__init__(f"cannot conform {source!r}: {reason}")


@dataclass(frozen=True)
class Conformed:
    """A conformed name and what was lost on the way."""

    source: str
    name: str
    notes: tuple[str, ...] = field(default=())
    """Lossy changes, e.g. ``dropped '%'`` or ``transliterated``; empty when nothing was lost."""

    @property
    def lossy(self) -> bool:
        """True when characters were dropped or transliterated."""
        return bool(self.notes)


class NameConformer:
    """Conforms names with one ``naming`` configuration."""

    def __init__(self, naming: NamingDefaults) -> None:
        """Use these naming defaults."""
        self.naming = naming

    def conform(self, source: str, ordinal: int = 1) -> Conformed:
        """Conform one name; ``ordinal`` (1-based) names an empty result ``col_<n>``.

        Raises:
            NamingError: when the policy says to fail (e.g. ``leading_digit: error``).
        """
        naming = self.naming
        notes: list[str] = []
        text = unicodedata.normalize("NFKC", source)
        text = self._ascii(text, notes)
        if naming.case == "snake" and naming.split_camel:
            text = _ACRONYM.sub("_", _CAMEL.sub("_", text))
        text = self._case(text)
        text = self._replace(text, notes)
        if naming.collapse:
            text = _RUNS.sub("_", text).strip("_")
        text = self._leading_digit(source, text)
        if not text:
            text = f"col_{ordinal}"
            notes.append(f"nothing usable was left, so it is named {text}")
        return Conformed(source, text, tuple(notes))

    def _ascii(self, text: str, notes: list[str]) -> str:
        if self.naming.ascii == "keep" or text.isascii():
            return text
        if self.naming.ascii == "strip":
            kept = "".join(c for c in text if c.isascii())
            notes.append(f"dropped non-ASCII {_quote(c for c in text if not c.isascii())}")
            return kept
        ascii_, dropped = transliterate(text)
        if len(dropped) < sum(1 for c in text if not c.isascii()):
            notes.append("transliterated to ASCII")
        if dropped:
            notes.append(f"dropped {_quote(dropped)} (no transliteration)")
        return ascii_

    def _case(self, text: str) -> str:
        case = self.naming.case
        if case in {"snake", "lower"}:
            return text.lower()
        if case == "upper":
            return text.upper()
        return text

    def _replace(self, text: str, notes: list[str]) -> str:
        pattern = _ALLOWED_UNICODE if self.naming.ascii == "keep" else _ALLOWED[self.naming.case]
        lost = [c for c in pattern.findall(text) if c not in _SEPARATORS]
        if lost:
            notes.append(f"dropped {_quote(lost)}")
        return pattern.sub(self.naming.replace_invalid, text)

    def _leading_digit(self, source: str, text: str) -> str:
        if not text or not text[0].isdigit():
            return text
        policy = self.naming.leading_digit
        if policy == "prefix":
            return "_" + text
        if policy == "letter":
            return "abcdefghij"[int(text[0])] + text[1:]
        raise NamingError(source, "it starts with a digit (leading_digit: error)")


def _quote(chars: Iterable[str]) -> str:
    return ", ".join(repr(c) for c in dict.fromkeys(chars))
