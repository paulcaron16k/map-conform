#!/usr/bin/env python3
"""Lint wiki page frontmatter.

Checks every wiki/**/*.md except wiki/log.md:
  - the file starts with a YAML frontmatter block;
  - required keys are present and `type` is in the taxonomy;
  - `tags` come from the closed tag library and include exactly one lifecycle tag;
  - every `sources[]` entry has a `path`.

Exit codes: 0 clean, 1 findings, 2 usage or parse error.
Usage: bin/wiki-lint-frontmatter.py [FILE ...]   (default: all wiki pages)
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("wiki-lint-frontmatter: PyYAML is required (uv add --dev pyyaml)")

ROOT = Path(__file__).resolve().parent.parent
TYPES = {
    "api_spec",
    "architecture_doc",
    "ci_cd",
    "component",
    "concept",
    "dataset",
    "decision_log",
    "entity",
    "event",
    "glossary",
    "metric",
    "plan",
    "playbook",
    "resource",
    "runbook",
    "schema",
}
LIFECYCLE = {"draft", "active", "deprecated", "blocked"}
TAGS = LIFECYCLE | {
    "management",
    "planning",
    "decision",
    "engineering",
    "architecture",
    "types",
    "naming",
    "config",
    "interface",
    "contract",
    "performance",
    "observability",
    "research",
    "platform",
    "qa",
    "testing",
    "delivery",
    "ci",
    "docs",
}
REQUIRED = ("type", "title", "description", "resource", "tags", "timestamp", "sources")


def lint(path: Path) -> list[str]:
    """Return the frontmatter problems in one wiki page."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return ["missing frontmatter"]
    try:
        block = text[4:].split("\n---\n", 1)[0]
        fm = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        return [f"invalid YAML: {exc}"]
    if not isinstance(fm, dict):
        return ["frontmatter is not a mapping"]
    errs = [f"missing key: {k}" for k in REQUIRED if k not in fm]
    if "sha" in fm:
        errs.append("'sha' is not allowed")
    if fm.get("type") not in TYPES:
        errs.append(f"type {fm.get('type')!r} not in taxonomy")
    tags = fm.get("tags") or []
    errs += [f"unknown tag {t!r}" for t in tags if t not in TAGS]
    if len(LIFECYCLE.intersection(tags)) != 1:
        errs.append("needs exactly one lifecycle tag (draft|active|deprecated|blocked)")
    for i, src in enumerate(fm.get("sources") or []):
        if not isinstance(src, dict) or "path" not in src:
            errs.append(f"sources[{i}] has no path")
    return errs


def main(argv: list[str]) -> int:
    """Lint the given pages, or every wiki page; return the exit code."""
    files = [Path(a) for a in argv] or sorted((ROOT / "wiki").rglob("*.md"))
    files = [f for f in files if f.name != "log.md"]
    bad = 0
    for f in files:
        for e in lint(f):
            print(f"{f}: {e}")
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
