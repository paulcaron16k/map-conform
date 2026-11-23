---
type: runbook
title: "Wiki maintenance"
description: "Rules for keeping wiki/ in sync: taxonomy, frontmatter, tags, log, sync policy."
resource: wiki/
tags: [management, docs, active]
timestamp: 2026-11-23T18:00:00Z
sources:
  - path: CLAUDE.md
---

# Wiki maintenance

Parent: [Wiki Index](../index.md)

## Layout

| Folder | `type` |
|---|---|
| `index.md` | playbook |
| `log.md` | (no frontmatter) |
| `glossary.md` | glossary |
| `architecture/` | architecture_doc |
| `components/` | component; one per subsystem, never one per file |
| `concepts/` | concept |
| `decisions/` | decision_log; numbered ADRs `NNNN-slug.md` |
| `schemas/` | schema |
| `plans/` | plan |
| `qa/` | playbook |
| `runbooks/` | runbook |
| `ci-cd/` | ci_cd |

## Frontmatter (required on every page except `log.md`)

```yaml
---
type: <taxonomy>
title: "..."
description: "..."        # quote it when it contains ': '
resource: <file or dir summarised>
tags: [ ... ]             # from the tag library; include one lifecycle tag
timestamp: YYYY-MM-DDTHH:MM:SSZ
sources:
  - path: <source file>
---
```

Allowed `type` values: api_spec, architecture_doc, ci_cd, component, concept, dataset,
decision_log, entity, event, glossary, metric, plan, playbook, resource, runbook, schema.

## Tag library (closed)

| Group | Tags |
|---|---|
| management | management, planning, decision |
| engineering | engineering, architecture, types, naming, config, interface, contract, performance, observability, research |
| platform | platform |
| qa | qa, testing |
| delivery | delivery, ci, docs |
| lifecycle (exactly one) | draft, active, deprecated, blocked |

## Body conventions

- H1 title, then a `Parent: [Wiki Index](../index.md)` line.
- Relative Markdown links only. No orphan pages.
- Prefer tables and bullets to prose.
- Cite inline as `(path:some/file)`. Mark an unverified claim with `> TODO-VERIFY:`.
- `draft` means the page describes the design; `active` means it describes running code.

## Log

Append one row to [log.md](../log.md) per CREATED, UPDATED or DELETED page.

## Sync policy

- A routine code change updates the existing page. A structural change adds a page and an
  index row.
- Wiki changes go in the same pull request as the code they describe, or in a sync pull
  request at the end of a phase. Nothing is pushed to `main` directly.
- Claim tests (`tests/wiki/`) check that links, anchors, cited paths and named modules
  exist. They do not check that the prose is still true: a PR that changes behaviour
  updates the pages that describe it, and each phase ends with a wiki sync.
- `bin/wiki-lint-frontmatter.py` validates frontmatter. It runs in pre-commit, and mdformat is
  excluded from `wiki/` because it destroys frontmatter.

## Decisions (ADRs)

- One file per decision, `decisions/NNNN-slug.md`, numbered in order, `type: decision_log`,
  linked from the index's decision list.
- Body: `Status:` line (Accepted, Amended, Superseded), then **Context**, **Decision** and
  **Consequences** sections.
- A refinement that keeps the decision is an **amendment**: add `## Amendment (date): what`
  at the end and say so in the status line. A reversal is a **new ADR** that supersedes the
  old one; the old one's status line points to it.
- Changing the [Clean-Landing Contract](../concepts/clean-landing-contract.md) always needs an
  ADR or an amendment.
