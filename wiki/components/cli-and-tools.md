---
type: component
title: "CLI and tools"
description: "The map-conform command: the mapper, spec validate/explain/schema/import/export, doctor and functions."
resource: map_conform/cli.py
tags: [engineering, interface, active]
timestamp: 2026-11-23T18:00:00Z
sources:
  - path: map_conform/cli.py
  - path: map_conform/doctor.py
  - path: map_conform/plan/validate.py
  - path: map_conform/spec/check.py
  - path: map_conform/spec/bridge.py
  - path: map_conform/spec/zamboni.py
  - path: map_conform/spec/importer.py
  - path: docs/detailed-design.md
---

# CLI and tools

Parent: [Wiki Index](../index.md) · Related: [Detailed design §2](../../docs/detailed-design.md#2-cli) ·
[Spec loader](spec-loader.md)

## Dispatch

`map-conform` is one console script (path:map_conform/cli.py). When its first argument is
one of the tool commands (`spec`, `functions`, `doctor`), click runs the tool. Otherwise
every argument goes to the Singer SDK's CLI for the mapper (`--config`, `--about`,
`--input`), which is how Meltano runs it.

## Modules

| Module | Does |
|---|---|
| `map_conform/cli.py` | The click group, dispatch and the tool commands |
| `map_conform/plan/validate.py` | `spec validate`: compiles every plan, with a catalog or from the rules alone |
| `map_conform/spec/check.py` | Checks against a catalog; `spec explain`'s report |
| `map_conform/spec/importer.py` | `spec import --stream-maps`: SDK settings to a native spec |
| `map_conform/spec/bridge.py` | `spec import --catalog` (a draft spec) and `spec export --zamboni` |
| `map_conform/spec/zamboni.py` | Zamboni table-config (version 2) read and write |
| `map_conform/doctor.py` | `doctor`: checks a Meltano project's use of map-conform |
| `map_conform/spec/reference.py` | Generates `docs/spec-reference.md` (not a command; `python -m`) |

## Commands

| Command | Behaviour |
|---|---|
| `spec validate SPEC [--catalog C] [--strict] [--var N=V] [--allow-python-udfs]` | Strict parse, then compile every plan. With a catalog, plans compile against its schemas and the spec is checked against its streams. Without, rules compile against the tap columns they imply; problems in untyped tap columns are warnings. Exit 1 on an error (or a warning with `--strict`). |
| `spec explain SPEC --stream S [--catalog C] [--json]` | Rules matched, output names and, with a catalog, each column's compiled plan |
| `spec schema` | The shipped JSON Schema, for editor completion |
| `spec import --catalog C [--zamboni TC]` | A draft spec with an explicit type per property |
| `spec import --stream-maps CONFIG [--catalog C]` | SDK stream maps as a native spec, compatibility defaults included |
| `spec export SPEC --zamboni TC --catalog C` | Canonical types into Zamboni `columns`, the rest of the file kept |
| `doctor [--meltano-yml F] [--strict]` | Settings, `spec_path`, UDF opt-in, and `add_record_metadata` on loaders after a mapping that adds `_sdc_*` |
| `functions [--json]` | Steps with signatures and the engines that vectorise them, casts, expression functions, installed UDFs |

## Adding a command

Add it to `TOOL_COMMANDS` and the click group in `cli.py`, test it through the installed
script (`tests/test_cli.py` runs the real executable) and with `CliRunner`, and list it in
the README's command line section and detailed design §2.
