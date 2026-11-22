# Wiki change log

Policy: [Wiki maintenance](runbooks/wiki-maintenance.md). Append-only.

| Timestamp | Action | Concept Path | Reason / Changes |
|---|---|---|---|
| 2026-11-21T00:00:00Z | CREATED | index | Initial knowledge base from the planning session |
| 2026-11-21T00:00:00Z | CREATED | glossary | Initial terms |
| 2026-11-21T00:00:00Z | CREATED | architecture/overview | Summary of docs/architecture-hld.md |
| 2026-11-21T00:00:00Z | CREATED | components/spec-loader | Planned component |
| 2026-11-21T00:00:00Z | CREATED | components/name-conformer | Planned component |
| 2026-11-21T00:00:00Z | CREATED | components/type-system-and-builtins | Planned component |
| 2026-11-21T00:00:00Z | CREATED | components/execution-engines | Planned component |
| 2026-11-21T00:00:00Z | CREATED | components/metadata-and-errors | Planned component |
| 2026-11-21T00:00:00Z | CREATED | concepts/clean-landing-contract | The contract targets rely on |
| 2026-11-21T00:00:00Z | CREATED | concepts/existing-systems-survey | Survey conclusions |
| 2026-11-21T00:00:00Z | CREATED | decisions/0001-name-and-licence | Planning quiz decisions |
| 2026-11-21T00:00:00Z | CREATED | decisions/0002-transform-authoring | Planning quiz decisions |
| 2026-11-21T00:00:00Z | CREATED | decisions/0003-own-spec-with-zamboni-bridge | Planning quiz decisions |
| 2026-11-21T00:00:00Z | CREATED | decisions/0004-batch-engine | Planning quiz decisions |
| 2026-11-21T00:00:00Z | CREATED | decisions/0005-sdc-metadata | Planning quiz decisions |
| 2026-11-21T00:00:00Z | CREATED | decisions/0006-error-policy | Planning quiz decisions |
| 2026-11-21T00:00:00Z | CREATED | decisions/0007-wire-encoding | Planning quiz decisions |
| 2026-11-21T00:00:00Z | CREATED | decisions/0008-naming-defaults | Planning quiz decisions |
| 2026-11-21T00:00:00Z | CREATED | decisions/0009-undeclared-columns | Planning quiz decisions |
| 2026-11-21T00:00:00Z | CREATED | schemas/conform-spec | Spec grammar |
| 2026-11-21T00:00:00Z | CREATED | schemas/plugin-settings | Plugin settings |
| 2026-11-21T00:00:00Z | CREATED | plans/roadmap | Phases and WBS pointer |
| 2026-11-21T00:00:00Z | CREATED | qa/test-strategy | Test layers |
| 2026-11-21T00:00:00Z | CREATED | runbooks/dev-environment | Dev setup |
| 2026-11-21T00:00:00Z | CREATED | runbooks/wiki-maintenance | Wiki rules |
| 2026-11-21T00:00:00Z | CREATED | ci-cd/pipeline | CI plan |
| 2026-11-21T12:00:00Z | CREATED | decisions/0010-stream-map-superset | Stream-map superset and masking parity (review feedback) |
| 2026-11-21T12:00:00Z | CREATED | decisions/0011-uuid-in-batch | Parquet UUID logical type, verified with pyarrow and DuckDB |
| 2026-11-21T12:00:00Z | UPDATED | decisions/0005-sdc-metadata | batched_at rule; no SDK proposal |
| 2026-11-21T12:00:00Z | UPDATED | concepts/clean-landing-contract | uuid in BATCH; batched_at |
| 2026-11-21T12:00:00Z | UPDATED | components/type-system-and-builtins | Masking table; stream-map compatibility |
| 2026-11-21T12:00:00Z | UPDATED | components/metadata-and-errors | batched_at |
| 2026-11-21T12:00:00Z | UPDATED | schemas/conform-spec | else, source, when, fields; filter on conformed names |
| 2026-11-21T12:00:00Z | UPDATED | schemas/plugin-settings | SDK-compatible settings |
| 2026-11-21T12:00:00Z | UPDATED | concepts/existing-systems-survey | Stream-map and masking features to keep |
| 2026-11-21T12:00:00Z | UPDATED | plans/roadmap | E12; open questions resolved |
| 2026-11-21T12:00:00Z | UPDATED | index | ADRs 0010-0011 |
| 2026-11-22T05:00:00Z | UPDATED | runbooks/dev-environment | P0 built: real commands, hooks, fixtures; draft → active |
| 2026-11-22T05:00:00Z | UPDATED | ci-cd/pipeline | P0 built: workflows as merged, publish gating; draft → active |
| 2026-11-22T05:00:00Z | UPDATED | qa/test-strategy | Fixtures, wiki claim tests and gates as built |
| 2026-11-22T05:00:00Z | UPDATED | plans/roadmap | P0 done; description says E1-E12 |
| 2026-11-22T06:00:00Z | CREATED | decisions/0012-bundled-transliteration-table | Q4 resolved: bundle a generated table |
| 2026-11-22T06:00:00Z | UPDATED | decisions/0001-name-and-licence | Amended: Python floor 3.11 |
| 2026-11-22T06:00:00Z | UPDATED | index | ADR 0012 |
| 2026-11-22T06:00:00Z | UPDATED | plans/roadmap | Q4 resolved |
| 2026-11-22T06:00:00Z | UPDATED | components/name-conformer | Transliteration links ADR-0012 |
| 2026-11-22T06:00:00Z | UPDATED | runbooks/dev-environment | Python 3.11–3.14 |
| 2026-11-22T06:00:00Z | UPDATED | ci-cd/pipeline | Python 3.11–3.14 |
