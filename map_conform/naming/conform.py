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
9. A reserved word of any configured dialect (case-insensitive): suffix ``_``, prefix ``_``,
   fail, or ignore.
10. Longer than ``max_length``: keep the head and add ``_`` plus 6 hex digits of the SHA-256
    of the whole name, or fail.

Running the pipeline on its own output changes nothing. :meth:`NameConformer.conform_all`
also resolves names that collide under case folding within one stream or struct.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from map_conform.naming.reserved import reserved_words
from map_conform.naming.translit import transliterate

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from map_conform.spec.model import NamingDefaults

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
# An acronym followed by a capitalised word splits before the word (HTTP_Server), but a
# plural acronym (IDs, URLs) stays whole.
_ACRONYM = re.compile(r"(?<=[A-Z])(?=[A-Z](?!s(?![a-z]))[a-z])")
_RUNS = re.compile(r"_+")
_MAX_PASSES = 5
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
        self.reserved = reserved_words(naming.reserved_dialects)

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
        text = self._settle(source, text, ordinal, notes)
        return Conformed(source, text, tuple(notes))

    def _settle(self, source: str, text: str, ordinal: int, notes: list[str]) -> str:
        """Steps 6-10, repeated until the name is a fixed point.

        One pass is usually enough. A truncation can cut a name back to something a step
        would change again (``_0000`` truncated to ``_`` plus a hash), so the steps repeat
        until nothing changes; that is what makes conforming idempotent.
        """
        for _ in range(_MAX_PASSES):
            before = text
            if self.naming.collapse:
                text = _RUNS.sub("_", text).strip("_")
            text = self._leading_digit(source, text)
            if not text:
                text = self._case(f"col_{ordinal}")
                notes.append(f"nothing usable was left, so it is named {text}")
            text = self._reserved(source, text)
            text = self._truncate(source, text, notes)
            if text == before:
                return text
        raise NamingError(source, f"the naming steps do not settle (last result {text!r})")

    def conform_all(self, sources: Sequence[str]) -> list[Conformed]:
        """Conform the names of one stream (or struct) and make them unique.

        Names that collide under case folding are an error, or with ``on_collision: suffix``
        the later ones get ``_2``, ``_3``, ... in input order, still within ``max_length``.

        Raises:
            NamingError: on a collision under ``on_collision: error``, or from :meth:`conform`.
        """
        results = [self.conform(source, ordinal) for ordinal, source in enumerate(sources, 1)]
        # First occurrences claim their names before any suffix is chosen, so a source that is
        # genuinely called order_id_2 keeps that name.
        owners: dict[str, Conformed] = {}
        for result in results:
            owners.setdefault(result.name.casefold(), result)
        taken = set(owners)
        out: list[Conformed] = []
        for result in results:
            first = owners[result.name.casefold()]
            if first is result:
                out.append(result)
                continue
            if self.naming.on_collision == "error":
                raise NamingError(
                    result.source,
                    f"it conforms to {result.name!r}, as {first.source!r} does "
                    "(on_collision: error)",
                )
            unique = self._suffixed(result.name, taken)
            taken.add(unique.casefold())
            note = f"renamed from {result.name!r}: {first.source!r} has that name"
            out.append(Conformed(result.source, unique, (*result.notes, note)))
        return out

    def _suffixed(self, name: str, taken: set[str]) -> str:
        n = 2
        while True:
            suffix = f"_{n}"
            head = name[: self.naming.max_length - len(suffix)].rstrip("_")
            candidate = head + suffix
            if candidate.casefold() not in taken:
                return candidate
            n += 1

    def _truncate(self, source: str, text: str, notes: list[str]) -> str:
        limit = self.naming.max_length
        if len(text) <= limit:
            return text
        if self.naming.truncate == "error":
            raise NamingError(source, f"{text!r} is longer than {limit} (truncate: error)")
        digest = self._case(hashlib.sha256(text.encode()).hexdigest()[:6])
        head = text[: limit - len(digest) - 1].rstrip("_")
        notes.append(f"truncated from {len(text)} characters")
        return f"{head}_{digest}"

    def _reserved(self, source: str, text: str) -> str:
        policy = self.naming.reserved_words
        if policy == "ignore" or text.lower() not in self.reserved:
            return text
        if policy == "suffix":
            return text + "_"
        if policy == "prefix":
            return "_" + text
        raise NamingError(source, f"{text!r} is a reserved word (reserved_words: error)")

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
        value = unicodedata.digit(text[0], None)
        if policy == "prefix" or (policy == "letter" and value is None):
            # A digit-like character with no digit value (e.g. U+11052 BRAHMI NUMBER ONE,
            # kept by ascii: keep) cannot become a letter, so it is prefixed instead.
            return "_" + text
        if policy == "letter" and value is not None:
            return self._case("abcdefghij"[value]) + text[1:]
        raise NamingError(source, "it starts with a digit (leading_digit: error)")


def _quote(chars: Iterable[str]) -> str:
    return ", ".join(repr(c) for c in dict.fromkeys(chars))
