---
type: runbook
title: "Wiki maintenance"
description: "Rules for keeping wiki/ in sync: taxonomy, frontmatter, tags, log, sync policy."
resource: wiki/
tags: [management, docs, active]
timestamp: 2026-11-21T00:00:00Z
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
- Content syncs happen on `main` after a merge, done by the session that made the change.
- Freshness is checked by claim tests (`tests/wiki/`), not by hashes.
- `bin/wiki-lint-frontmatter.py` validates frontmatter. It runs in pre-commit, and mdformat is
  excluded from `wiki/` because it destroys frontmatter.
