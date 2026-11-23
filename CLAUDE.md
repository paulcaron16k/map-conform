# map-conform — agent instructions

Public repository, published to PyPI. **Never include company names, internal hostnames,
customer data or credentials** in code, docs, commits, issues or PRs.

## Orientation

- Founding brief: `creating-a-better-mapper-guidance.md`
- Design docs: `docs/` (exec overview, HLD, detailed design, plan/WBS)
- Knowledge base: `wiki/`. Read `wiki/runbooks/wiki-maintenance.md` before editing anything
  under `wiki/`.
- Tracking: `gh agile`, key `MAPC`. Issues are generated from `docs/plan-wbs.md` by
  `bin/create-agile-issues.py`.

## Invariants

- **Declared, not inferred.** Output types come from the spec or the tap SCHEMA, never from
  values or expression text.
- **One plan, two executors.** Any change to a transform must keep RECORD/BATCH parity tests
  green.
- **Fail loud.** The default `on_error` is `raise`. Never swallow exceptions in transforms.
- **The Clean-Landing Contract** (`wiki/concepts/clean-landing-contract.md`) is a public
  interface. Changing it needs an ADR in `wiki/decisions/`.
- The spec JSON Schema is generated from code. Never hand-edit the shipped schema file.

## Workflow

- Push only to `origin`; work lands through pull requests.
- Before calling work done: `uv run pytest`, `uv run ruff check . && uv run ruff format --check .`, `uv run mypy map_conform`, `bin/wiki-lint-frontmatter.py`.
- Wiki content syncs happen on `main` after a merge (see the maintenance runbook), with a
  `wiki/log.md` row for each page change.
