# map-conform

A Singer/Meltano **inline mapper** that makes data *land clean*. It sits between any tap and
any target and does the following, once, upstream:

- **cleans values** while casting strings to declared types: currency, thousands separators,
  null tokens, spreadsheet dates, epoch times, time zones, boolean words;
- **conforms names** so they are legal in every target: snake_case, ASCII, length limits,
  reserved words, collision checks;
- **casts to declared types**, never inferred: exact decimals, timestamp with or without zone;
- **prefixes and aliases streams**;
- **adds the `_sdc_*` metadata columns**, with Singer SDK semantics;
- **transforms BATCH messages** (parquet or JSONL) at columnar speed with Apache Arrow.

Targets then rely on the [Clean-Landing Contract](wiki/concepts/clean-landing-contract.md)
and do not re-implement cleanup.

> **Status: planning.** No code yet. Start with the
> [guidance](creating-a-better-mapper-guidance.md), then the
> [executive overview](docs/exec-overview.md), [architecture](docs/architecture-hld.md),
> [detailed design](docs/detailed-design.md) and [plan](docs/plan-wbs.md).
> The knowledge base is in [wiki/](wiki/index.md).

## Licence

Apache-2.0
