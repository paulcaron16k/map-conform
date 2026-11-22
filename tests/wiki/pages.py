"""Parse the wiki and the repository's other markdown for the claim tests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WIKI = ROOT / "wiki"
LIFECYCLE = frozenset({"draft", "active", "deprecated", "blocked"})

_FENCE = re.compile(r"^(```|~~~).*?^\1", re.MULTILINE | re.DOTALL)
_CODE_SPAN = re.compile(r"(`+)(?!`).+?(?<!`)\1", re.DOTALL)
_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_CITATION = re.compile(r"\(path:([^)]+)\)")
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_MODULE_PATH = re.compile(r"\bmap_conform/[A-Za-z0-9_./-]*")


@dataclass(frozen=True)
class Page:
    """One markdown file: its frontmatter (if any) and its body."""

    path: Path
    meta: dict[str, Any]
    body: str

    @property
    def rel(self) -> str:
        """The path relative to the repository root."""
        return self.path.relative_to(ROOT).as_posix()

    @property
    def lifecycle(self) -> str | None:
        """The page's lifecycle tag, when it has exactly one."""
        tags = set(self.meta.get("tags") or ())
        found = tags & LIFECYCLE
        return next(iter(found)) if len(found) == 1 else None

    @property
    def prose(self) -> str:
        """The body without fenced blocks or code spans: what links and citations live in."""
        return _CODE_SPAN.sub("", _FENCE.sub("", self.body))

    @property
    def prose_with_code_spans(self) -> str:
        """The body without fenced blocks, keeping inline code where module names appear."""
        return _FENCE.sub("", self.body)


def _read(path: Path) -> Page:
    text = path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        block, _, body = text[4:].partition("\n---\n")
        return Page(path, yaml.safe_load(block) or {}, body)
    return Page(path, {}, text)


@cache
def wiki_pages() -> tuple[Page, ...]:
    """Every wiki page that carries frontmatter (all but the log)."""
    return tuple(_read(p) for p in sorted(WIKI.rglob("*.md")) if p.name != "log.md")


@cache
def markdown_files() -> tuple[Page, ...]:
    """Every markdown file whose links readers follow: the wiki, docs and the root files."""
    paths = [*sorted(WIKI.rglob("*.md")), *sorted((ROOT / "docs").rglob("*.md"))]
    paths += sorted(ROOT.glob("*.md"))
    paths += sorted((ROOT / "tests").rglob("*.md"))
    return tuple(_read(p) for p in paths)


def links(page: Page) -> list[str]:
    """Relative link targets in the page's prose (no URLs, no mail links)."""
    return [
        target
        for target in _LINK.findall(page.prose)
        if not re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE)
    ]


def citations(page: Page) -> list[str]:
    """``(path:...)`` citations, split when one cites several comma-separated files."""
    return [
        part.strip()
        for cited in _CITATION.findall(page.prose)
        for part in cited.split(",")
        if part.strip()
    ]


def module_paths(page: Page) -> list[str]:
    """``map_conform/...`` paths named anywhere outside fenced blocks."""
    return [m.rstrip(".-") for m in _MODULE_PATH.findall(page.prose_with_code_spans)]


def slug(heading: str) -> str:
    """The anchor GitHub generates for a heading."""
    text = _CODE_SPAN.sub(lambda m: m.group(0).strip("`"), heading)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(page: Page) -> set[str]:
    """Every anchor a link may name in this page, with GitHub's ``-1`` de-duplication."""
    seen: dict[str, int] = {}
    out: set[str] = set()
    for heading in _HEADING.findall(_FENCE.sub("", page.body)):
        base = slug(heading)
        count = seen.get(base, 0)
        out.add(base if count == 0 else f"{base}-{count}")
        seen[base] = count + 1
    return out


def in_repo(path: str) -> bool:
    """Whether a cited path names something in this repository rather than elsewhere."""
    first = path.split("/", 1)[0]
    return (ROOT / first).exists()


def page_for(path: Path) -> Page:
    """The parsed page at ``path``."""
    return _read(path)
