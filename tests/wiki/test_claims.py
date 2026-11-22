"""Claim tests from wiki/runbooks/wiki-maintenance.md.

``draft`` pages describe the design, so they may name modules that do not exist yet;
``active`` pages describe running code, so everything they name must exist.
"""

from __future__ import annotations

import re
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from tests.wiki.pages import (
    ROOT,
    WIKI,
    Page,
    anchors,
    citations,
    in_repo,
    links,
    markdown_files,
    module_paths,
    page_for,
    wiki_pages,
)

if TYPE_CHECKING:
    from pathlib import Path

LINTER = ROOT / "bin" / "wiki-lint-frontmatter.py"


def _id(page: Page) -> str:
    return page.rel


@pytest.mark.parametrize("page", markdown_files(), ids=_id)
def test_relative_links_resolve(page: Page) -> None:
    """Every relative link names a file that exists and, if given, an anchor in it."""
    broken = []
    for target in links(page):
        file_part, _, anchor = target.partition("#")
        dest = (page.path.parent / file_part).resolve() if file_part else page.path
        if not dest.exists():
            broken.append(f"{target}: no such file")
        elif anchor and dest.suffix == ".md" and anchor not in anchors(page_for(dest)):
            broken.append(f"{target}: no heading with anchor #{anchor}")
    assert not broken, broken


@pytest.mark.parametrize("page", wiki_pages(), ids=_id)
def test_sources_exist(page: Page) -> None:
    """A page's sources are what it was written from, so they exist whatever its lifecycle."""
    missing = [s["path"] for s in page.meta["sources"] if not (ROOT / s["path"]).exists()]
    assert not missing, missing


@pytest.mark.parametrize("page", wiki_pages(), ids=_id)
def test_active_page_resource_exists(page: Page) -> None:
    """An active page summarises something real."""
    if page.lifecycle != "active":
        pytest.skip(f"{page.lifecycle} page")
    assert (ROOT / page.meta["resource"]).exists(), page.meta["resource"]


@pytest.mark.parametrize("page", markdown_files(), ids=_id)
def test_citations_in_this_repo_exist(page: Page) -> None:
    """``(path:...)`` citations of this repository's files resolve; external ones are skipped."""
    missing = [c for c in citations(page) if in_repo(c) and not (ROOT / c).exists()]
    assert not missing, missing


@pytest.mark.parametrize("page", wiki_pages(), ids=_id)
def test_active_page_modules_exist(page: Page) -> None:
    """Modules an active page names are in the package.

    The index is exempt: its rows name each component page's resource, and the component
    page's own lifecycle governs that claim.
    """
    if page.lifecycle != "active" or page.path == WIKI / "index.md":
        pytest.skip("not an active content page")
    missing = [m for m in module_paths(page) if not (ROOT / m).exists()]
    assert not missing, missing


def test_every_page_is_reachable_from_the_index() -> None:
    """No orphan pages: each one is linked from wiki/index.md."""
    index = page_for(WIKI / "index.md")
    linked = {(WIKI / t.partition("#")[0]).resolve() for t in links(index)}
    orphans = [p.rel for p in wiki_pages() if p.path != index.path and p.path not in linked]
    orphans += [] if (WIKI / "log.md").resolve() in linked else ["wiki/log.md"]
    assert not orphans, orphans


def test_index_type_column_matches_frontmatter() -> None:
    """Where the index states a page's type, it is the type in that page's frontmatter."""
    row = re.compile(r"^\| \[[^\]]+\]\(([^)#]+)\) \| ([a-z_]+) \|", re.MULTILINE)
    index = page_for(WIKI / "index.md")
    wrong = [
        f"{target}: index says {stated}, page says {page_for(WIKI / target).meta['type']}"
        for target, stated in row.findall(index.body)
        if page_for(WIKI / target).meta["type"] != stated
    ]
    assert not wrong, wrong


def test_log_accounts_for_every_page() -> None:
    """Every page has a CREATED row, and nothing the log considers live is missing."""
    row = re.compile(r"^\| [^|]+ \| (CREATED|UPDATED|DELETED) \| ([^|]+?) \|", re.MULTILINE)
    last: dict[str, str] = {}
    created: set[str] = set()
    for action, concept in row.findall((WIKI / "log.md").read_text(encoding="utf-8")):
        last[concept] = action
        if action == "CREATED":
            created.add(concept)
    pages = {p.path.relative_to(WIKI).with_suffix("").as_posix() for p in wiki_pages()}
    problems = [f"{c}: no CREATED row" for c in sorted(pages - created)]
    problems += [f"{c}: logged as {last.get(c)}" for c in sorted(pages) if last.get(c) == "DELETED"]
    problems += [
        f"{c}: live in the log, no page"
        for c, action in sorted(last.items())
        if action != "DELETED" and c not in pages
    ]
    assert not problems, problems


def _lint(*files: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv: this interpreter and the repo's linter
        [sys.executable, str(LINTER), *map(str, files)],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_frontmatter_linter_passes_on_the_wiki() -> None:
    """The committed wiki is clean."""
    result = _lint()
    assert result.returncode == 0, result.stdout + result.stderr


def test_frontmatter_linter_rejects_a_bad_page(tmp_path: Path) -> None:
    """The pre-commit hook's linter fails a page with a bad type, tags and missing keys."""
    bad = tmp_path / "bad.md"
    bad.write_text("---\ntype: nonsense\ntitle: x\ntags: [shiny]\nsha: abc\n---\n# x\n")
    result = _lint(bad)
    assert result.returncode == 1
    for finding in (
        "missing key: description",
        "type 'nonsense' not in taxonomy",
        "unknown tag 'shiny'",
        "needs exactly one lifecycle tag",
        "'sha' is not allowed",
    ):
        assert finding in result.stdout
