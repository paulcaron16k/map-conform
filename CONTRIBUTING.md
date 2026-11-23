# Contributing to map-conform

Thank you for helping. Bug reports, recipes that should be in the cookbook, and pull requests
are all welcome.

## Reporting a bug

Open an issue with:

- the map-conform version (`map-conform --version`) and Python version;
- the spec (or the part that matters) and the settings;
- a few input records, or the SCHEMA and a RECORD, that show the problem;
- what map-conform wrote, and what you expected.

`map-conform spec validate` and `map-conform spec explain --catalog` often show the cause.
For a security problem, do not open an issue: see [SECURITY.md](SECURITY.md).

## Setting up

The [dev environment runbook](wiki/runbooks/dev-environment.md) has the commands: `uv sync --all-groups`, the tests, lint and types, and the checklists for adding a step, a cast option,
a setting or a type. The [wiki](wiki/index.md) explains how the code is organised, and
[docs/detailed-design.md](docs/detailed-design.md) why it behaves as it does.

## How work is tracked

Work is tracked as GitHub issues on this repository, organised on a GitHub Project by the
[`gh agile`](https://github.com/paulcaron16k/gh-agile) extension, which labels each issue
with a key, `MAPC-<number>` (the number is the issue number). You do not need it to
contribute: open an issue or a pull request as usual, and a maintainer files it on the
board. To use it yourself: `gh extension install paulcaron16k/gh-agile`; the profile is
[.github/agile.json](.github/agile.json), and `gh agile validate` checks the board.

## Branches, commits and pull requests

- **Branches:** `<kind>/mapc-<n>_<slug>`, where kind is `feat`, `fix`, `docs`, `chore`, `ci`
  or `release`, e.g. `fix/mapc-141_column-flatten`.
- **Commits:** an imperative subject that ends with the issue key, e.g.
  `Honour a column's flatten: true without a shape (MAPC-141)`; a body that says what
  changed and why.
- **Pull requests:** one issue per pull request, `Closes #<n>` in the description, what
  changed, and how it was verified. Pull requests are squash-merged, so the subject becomes
  the commit on `main`.
- **Done** means the [definition of done](wiki/runbooks/dev-environment.md#definition-of-done):
  tests, lint, types and pre-commit pass, generated files are current, and the docs, the
  wiki pages and the changelog's Unreleased section describe the change. CI checks the rest.
- **The wiki** changes in the same pull request as the code it describes. Its rules are in
  [wiki maintenance](wiki/runbooks/wiki-maintenance.md).
- **Design decisions** are ADRs in [wiki/decisions/](wiki/decisions/0001-name-and-licence.md);
  changing the [Clean-Landing Contract](wiki/concepts/clean-landing-contract.md), which
  targets rely on, always needs one.

## Licence

By contributing you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE), like the rest of the project.
