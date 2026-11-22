#!/usr/bin/env python3
"""File the map-conform initiative, epics and stories with `gh agile`.

The single source of truth is docs/plan-wbs.md. Epics are the "### E<n> <name> (P<k>) — <n>"
headings; stories are the "| <wbs> | <story> | <pts> | <acceptance> |" rows beneath them.

Idempotent: an issue whose title already exists in the repo is reused, not re-filed.
Dry run by default; pass --apply to create issues.

    bin/create-agile-issues.py                 # print what would be filed
    bin/create-agile-issues.py --apply         # file it (needs `gh agile init` done)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = "paulcaron16k/map-conform"
PLAN = Path(__file__).resolve().parent.parent / "docs" / "plan-wbs.md"
INITIATIVE_TITLE = "map-conform: clean landing for Singer pipelines"
INITIATIVE_SLUG = "map-conform"

EPIC_RE = re.compile(r"^### (E(\d+)) (.+?) \((P\d)\) — \d+\s*$")
ROW_RE = re.compile(r"^\| (\d+\.\d+) \| (.+?) \| (\d+) \| (.+?) \|\s*$")


@dataclass
class Story:
    """One story row of a WBS table."""

    wbs: str
    title: str
    points: int
    acceptance: str


@dataclass
class Epic:
    """One `### E<n>` epic heading and the stories under it."""

    code: str
    number: int
    name: str
    phase: str
    stories: list[Story] = field(default_factory=list)

    @property
    def title(self) -> str:
        """The issue title: `E<n> <name> [P<k>]`."""
        return f"{self.code} {self.name} [{self.phase}]"


def parse_plan(text: str) -> tuple[str, str, list[Epic]]:
    """Return (initiative intent, initiative acceptance, epics) from plan-wbs.md."""
    init = re.search(r"## Initiative\n\n(.+?)\n\n## ", text, re.DOTALL)
    if not init:
        sys.exit("plan-wbs.md: '## Initiative' section not found")
    blurb = " ".join(init.group(1).split())
    intent, _, acceptance = blurb.partition("*Acceptance:*")
    epics: list[Epic] = []
    for line in text.splitlines():
        if m := EPIC_RE.match(line):
            epics.append(Epic(m.group(1), int(m.group(2)), m.group(3), m.group(4)))
        elif (m := ROW_RE.match(line)) and epics:
            epics[-1].stories.append(Story(m.group(1), m.group(2), int(m.group(3)), m.group(4)))
    if not epics:
        sys.exit("plan-wbs.md: no epics parsed")
    for e in epics:
        if not e.stories:
            sys.exit(f"plan-wbs.md: epic {e.code} has no stories")
        bad = [s.wbs for s in e.stories if not s.wbs.startswith(f"{e.number}.")]
        if bad:
            sys.exit(f"plan-wbs.md: stories {bad} are not numbered under {e.code}")
    return intent.strip(), acceptance.strip(), epics


def existing_titles() -> dict[str, int]:
    """Map every issue title in the repo, key prefix stripped, to its number."""
    out = subprocess.run(
        [
            "gh",
            "issue",
            "list",
            "-R",
            REPO,
            "--state",
            "all",
            "--limit",
            "1000",
            "--json",
            "number,title",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    # Strip a "MAPC-n " title prefix the profile may add, so lookups match plain titles.
    return {re.sub(r"^[A-Z]+-\d+\s+", "", i["title"]): i["number"] for i in json.loads(out)}


def run(cmd: list[str]) -> int:
    """Run a gh agile create command; return the issue number it printed."""
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    m = re.findall(r"/issues/(\d+)", out) or re.findall(r"#(\d+)", out)
    if not m:
        sys.exit(f"could not find an issue number in output of {cmd[:4]}:\n{out}")
    return int(m[-1])


def main() -> None:
    """Parse the plan and print, or with --apply file, the missing issues."""
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--apply", action="store_true", help="create issues (default: dry run)")
    args = ap.parse_args()

    intent, acceptance, epics = parse_plan(PLAN.read_text())
    total = sum(s.points for e in epics for s in e.stories)
    print(
        f"Initiative: {INITIATIVE_TITLE}  ({len(epics)} epics, "
        f"{sum(len(e.stories) for e in epics)} stories, {total} points)"
    )
    if not args.apply:
        for e in epics:
            print(f"  Epic {e.title}")
            for s in e.stories:
                print(f"    [{s.points}] {s.title} [WBS {s.wbs}]")
        print("\nDry run. Re-run with --apply to file these issues.")
        return

    have = existing_titles()
    init_no = have.get(INITIATIVE_TITLE) or run(
        [
            "gh",
            "agile",
            "initiative",
            "create",
            "-R",
            REPO,
            "-t",
            INITIATIVE_TITLE,
            "--slug",
            INITIATIVE_SLUG,
            "--intent",
            intent,
            "--acceptance",
            acceptance,
        ]
    )
    for e in epics:
        epic_no = have.get(e.title) or run(
            [
                "gh",
                "agile",
                "epic",
                "create",
                "-R",
                REPO,
                "-t",
                e.title,
                "--initiative",
                str(init_no),
                "--intent",
                f"WBS {e.number}, phase {e.phase}. See docs/plan-wbs.md.",
                "--acceptance",
                "All child stories done; phase gate verification passed.",
            ]
        )
        for s in e.stories:
            title = f"{s.title} [WBS {s.wbs}]"
            if title in have:
                continue
            run(
                [
                    "gh",
                    "agile",
                    "story",
                    "create",
                    "-R",
                    REPO,
                    "-t",
                    title,
                    "--epic",
                    str(epic_no),
                    "--points",
                    str(s.points),
                    "--intent",
                    f"WBS {s.wbs}. See docs/plan-wbs.md and docs/detailed-design.md.",
                    "--acceptance",
                    s.acceptance,
                ]
            )
        print(f"  filed {e.title}")


if __name__ == "__main__":
    main()
