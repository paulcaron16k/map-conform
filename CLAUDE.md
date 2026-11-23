# map-conform — agent instructions

Public repository, published to PyPI. **Never include company names, internal hostnames,
customer data or credentials** in code, docs, commits, issues or PRs.

## Orientation

- Founding brief (the original intent, kept as a record): `creating-a-better-mapper-guidance.md`
- Contributor workflow: `CONTRIBUTING.md`; releases: `wiki/runbooks/release.md`
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
- Before calling work done: the definition of done in `wiki/runbooks/dev-environment.md`
  (tests, ruff, mypy and ty, pre-commit, generated files, docs, wiki and changelog).
- Wiki changes go in the same pull request as the code (see the maintenance runbook), with a
  `wiki/log.md` row for each page change.
