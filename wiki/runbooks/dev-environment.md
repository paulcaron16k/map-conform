---
type: runbook
title: "Development environment"
description: "Set-up, the definition of done, generated files, and checklists for adding a step, setting or type."
resource: pyproject.toml
tags: [platform, active]
timestamp: 2026-11-23T18:00:00Z
sources:
  - path: pyproject.toml
  - path: .pre-commit-config.yaml
  - path: tests/fixtures/README.md
  - path: map_conform/transforms/builtins.py
  - path: map_conform/settings.py
  - path: map_conform/types/canonical.py
---

# Development environment

Parent: [Wiki Index](../index.md)

Requires [uv](https://docs.astral.sh/uv/). Python 3.11–3.14 are supported (path:pyproject.toml).

## Everyday commands

| Task | Command |
|---|---|
| Install everything (dev = lint + test + typing groups) | `uv sync --all-groups` |
| Tests (offline) | `uv run pytest` |
| End-to-end, into a real target-jsonl (needs uvx and network; CI runs it) | `uv run pytest -m e2e` |
| Benchmarks and their gate | `uv run pytest -m bench tests/bench` |
| Lint and format | `uv run ruff check . && uv run ruff format --check .` |
| Types | `uv run mypy map_conform tests && uv run ty check map_conform tests` |
| Every Python, plus typing, as CI runs it (uv fetches missing Pythons) | `uvx --with tox-uv tox` |
| Pre-commit hooks, once per clone | `uvx pre-commit install` |
| All hooks over the tree | `uvx pre-commit run --all-files` |
| Wiki frontmatter | `uv run bin/wiki-lint-frontmatter.py` |
| Regenerate derived fixtures | `uv run python -m tests.fixtures.generate` |
| Try the mapper | `uv run map-conform --about` |
| The example Meltano project, as CI runs it | see [examples/README.md](../../examples/README.md) |

pre-commit runs through `uvx`, not as a project dependency, so its tool chain stays out of the
project's lockfile.

## Hooks

`.pre-commit-config.yaml` (path:.pre-commit-config.yaml) runs file hygiene, zizmor,
check-jsonschema (workflows, Dependabot, `meltano.yml`), ruff, uv-audit/uv-lock, mdformat
(not on `wiki/`), typos, mypy and the wiki frontmatter linter. Fixture data under
`tests/fixtures/{sources,streams,batch}/` is exempt from the whitespace hooks, because it is
messy on purpose.

## Fixtures

See [tests/fixtures/README.md](../../tests/fixtures/README.md). The case tables in
`corpus/` are edited by hand; everything else is generated, and a test fails when it is
stale.

## Definition of done

A change is done when all of these pass; CI runs the same, plus the example project and
zizmor.

1. `uv run pytest` (and `-m e2e` when the change touches the wire or Meltano)
2. `uv run ruff check . && uv run ruff format --check .`
3. `uv run mypy map_conform tests && uv run ty check`
4. `uvx pre-commit run --all-files`
5. Generated files are current (below), docs and wiki pages that describe the change are
   updated, and the changelog's Unreleased section has a line for anything a user notices.

## Generated files

Never edit these by hand. A test fails when one is stale, and its message names the command.

| File | Regenerate with | Guarded by |
|---|---|---|
| `map_conform/map-conform-spec.schema.json` | `uv run python -m map_conform.spec.jsonschema` | `tests/spec/test_jsonschema.py` |
| `docs/spec-reference.md` | `uv run python -m map_conform.spec.reference` | `tests/spec/test_reference.py` |
| `plugin-definition.yml` | `uv run bin/render-hub-definition.py` | `tests/test_hub_definition.py` |
| `tests/fixtures/{sources,streams,catalogs,batch}/` | `uv run python -m tests.fixtures.generate` | `tests/test_fixtures.py` |
| `tests/types/snapshots/` | review, then `UPDATE_SNAPSHOTS=1 uv run pytest tests/types` | `tests/types/test_type_mappings.py` |
| `map_conform/naming/ascii-table.json` | `uv run --python 3.14 python -m map_conform.naming.translit` (needs Python 3.14's Unicode data) | `tests/naming/test_translit.py` |

## Adding a builtin step

1. Write the function and its kwargs dataclass in the right `map_conform/transforms/` module
   (text, numeric, temporal, casts, privacy, nested) and register it in that module's
   `register()`. Document each kwarg with `documented(...)`.
2. Add a one-line entry to `DOCS` in `map_conform/transforms/builtins.py`; the registry does
   not build without one, and it is the step's line in the reference and `functions`.
3. Test it in `tests/transforms/`; cases that are input → output tables belong in
   `tests/fixtures/corpus/`.
4. For a vector kernel too: add it to `TRANSFORMS` in `map_conform/transforms/vector.py` (or
   `polars_vector.py`), marking as *todo* every row it is not sure of, and add it to the
   generated parity cases (`TEXT_STEPS` in `tests/parity/test_parity.py`;
   `test_every_kernel_has_parity_cases` fails until you do).
5. Regenerate `docs/spec-reference.md`; add the step to detailed design §6 and the changelog.

## Adding a cast option (`parse`)

1. Add the field, with `documented(...)`, to the cast's options dataclass (`NumberCast`,
   `TemporalCast`, `StringCast`, … in `map_conform/transforms/`), and implement it in the
   scalar cast. If a stream default should set it, add it to the cast's `defaults` function
   and mark the field `metadata={"from": "<defaults path>"}`.
2. The vector kernels hand every value to the row path while the option differs from its
   default (`claims` in `vector.py`). Only when a kernel implements the option, add it to that
   kernel's understood set, and add parity cases that set it.
3. Regenerate `docs/spec-reference.md` (its `parse` options section lists the field).

## Adding a setting

1. Add the field, with `documented(...)`, to `Settings` in `map_conform/settings.py`.
2. Declare it in the root `meltano.yml` (name, `kind`, `label`, `description`);
   `tests/test_settings.py` checks the names match.
3. Regenerate `plugin-definition.yml` and `docs/spec-reference.md`.
4. If `doctor` should check it, extend `map_conform/doctor.py`.
5. Update [Plugin settings](../schemas/plugin-settings.md) if it adds a group or a layering
   rule, and the changelog.

## Adding a canonical type

A type is a new `Kind` in `map_conform/types/canonical.py`, and every module that lists the
kinds needs a decision: `types/` (from and to JSON Schema, to Arrow, wire values), the casts
(`transforms/registry.py`, `transforms/builtins.py` and the cast module), the vector tables
if it gets a kernel, `batch/arrow.py`, and the bridges (`spec/bridge.py`,
`spec/stream_maps.py`). `grep -rln timestamptz map_conform` lists them. Then:

1. Update the type table in detailed design §4 and the type snapshot
   (`UPDATE_SNAPSHOTS=1`).
2. Add corpus cases and, with a kernel, parity cases.
3. A new type changes what targets receive: write an ADR or an amendment, and update the
   [Clean-Landing Contract](../concepts/clean-landing-contract.md).
