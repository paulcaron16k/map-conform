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
| 2026-11-22T08:00:00Z | UPDATED | decisions/0008-naming-defaults | Amended: default reserved dialects postgres, duckdb, snowflake; ansi opt-in |
| 2026-11-22T10:00:00Z | UPDATED | components/spec-loader | P1 built: modules and behaviour as merged; draft → active |
| 2026-11-22T10:00:00Z | UPDATED | components/name-conformer | P1 built: pipeline, streams, nested, properties; naming: sdk planned (WBS 12.10); draft → active |
| 2026-11-22T10:00:00Z | UPDATED | schemas/plugin-settings | P1 built: settings as merged; SDK-compatible settings planned (E12); draft → active |
| 2026-11-22T10:00:00Z | UPDATED | schemas/conform-spec | P1 built: generated schema, YAML 1.2, step rule; draft → active |
| 2026-11-22T10:00:00Z | UPDATED | plans/roadmap | P1 done; P3 is 53 points with WBS 12.10 |
| 2026-11-22T12:00:00Z | UPDATED | components/metadata-and-errors | P2 built: _sdc_*, errors, rejects, thresholds, metrics; draft → active |
| 2026-11-22T12:00:00Z | UPDATED | components/type-system-and-builtins | P2 status: types, builtins, macros built; expr/UDF/compat pending |
| 2026-11-22T12:00:00Z | UPDATED | components/execution-engines | P2 status: plan compiler and row executor built; BATCH pending |
| 2026-11-22T12:00:00Z | UPDATED | concepts/clean-landing-contract | Delivered by the RECORD path as of P2 |
| 2026-11-22T12:00:00Z | UPDATED | qa/test-strategy | Layers built through P2 |
| 2026-11-22T12:00:00Z | UPDATED | plans/roadmap | P2 done |
| 2026-11-22T18:00:00Z | UPDATED | components/type-system-and-builtins | P3 built: expressions, case/when/fields, UDFs, masking, Faker, stream-map compatibility; draft → active |
| 2026-11-22T18:00:00Z | UPDATED | components/metadata-and-errors | rows_filtered metric built (P3) |
| 2026-11-22T18:00:00Z | UPDATED | components/execution-engines | P3 status: derived-column order, filter, flattening |
| 2026-11-22T18:00:00Z | UPDATED | qa/test-strategy | Expression and SDK parity layers built (P3) |
| 2026-11-22T18:00:00Z | UPDATED | plans/roadmap | P3 done |
| 2026-11-22T18:00:00Z | UPDATED | decisions/0007-wire-encoding | Amended: decimals inside JSON text are exact numbers |
| 2026-11-22T18:00:00Z | UPDATED | decisions/0010-stream-map-superset | Amended: compatibility defaults for stream_maps |
| 2026-11-22T18:00:00Z | UPDATED | components/name-conformer | naming: sdk preset and flattening built (P3) |
| 2026-11-22T19:00:00Z | UPDATED | decisions/0005-sdc-metadata | Amended: add_record_metadata, default false, for RECORD and BATCH |
| 2026-11-22T19:00:00Z | UPDATED | decisions/0010-stream-map-superset | Compatibility defaults no longer set metadata |
| 2026-11-22T19:00:00Z | UPDATED | components/metadata-and-errors | _sdc_* columns follow add_record_metadata (default false) |
| 2026-11-22T19:30:00Z | UPDATED | plans/roadmap | Added WBS 7.5 (done) and 8.10 (first in P4) |
| 2026-11-22T20:00:00Z | CREATED | qa/benchmarks | Throughput baseline and the CI regression gate (WBS 8.9) |
| 2026-11-22T20:00:00Z | UPDATED | qa/test-strategy | Parity and bench layers built; draft → active |
| 2026-11-22T21:00:00Z | UPDATED | components/execution-engines | P4 built: BATCH I/O, columnar executor, case lowering, polars; draft → active |
| 2026-11-22T21:00:00Z | UPDATED | concepts/clean-landing-contract | BATCH delivers the contract as of P4; _sdc_* follow add_record_metadata |
| 2026-11-22T21:00:00Z | UPDATED | qa/benchmarks | CI's first benchmark numbers |
| 2026-11-22T21:00:00Z | UPDATED | plans/roadmap | P4 done |
| 2026-11-23T14:00:00Z | UPDATED | components/spec-loader | spec validate compiles every plan (MAPC-128) |
| 2026-11-23T14:30:00Z | UPDATED | runbooks/dev-environment | e2e and bench are opt-in test runs (MAPC-130) |
| 2026-11-23T15:00:00Z | UPDATED | components/execution-engines | engine: row, route logging, option guard (MAPC-132) |
| 2026-11-23T16:00:00Z | UPDATED | concepts/existing-systems-survey | Specific findings kept to public systems (MAPC-138) |
| 2026-11-23T16:00:00Z | UPDATED | concepts/clean-landing-contract | uuid_as is not a setting in 0.1.0 (MAPC-138) |
| 2026-11-23T16:00:00Z | UPDATED | decisions/0011-uuid-in-batch | uuid_as recorded as planned, not built (MAPC-138) |
| 2026-11-23T16:00:00Z | UPDATED | runbooks/dev-environment | Personal git identity removed (MAPC-138) |
| 2026-11-23T18:00:00Z | CREATED | components/cli-and-tools | The map-conform command, validate, doctor and the bridges (MAPC-144) |
| 2026-11-23T18:00:00Z | CREATED | runbooks/release | Cutting a release (MAPC-145) |
| 2026-11-23T18:00:00Z | UPDATED | index | 0.1.0 released; start-here and reading paths for users and maintainers |
| 2026-11-23T18:00:00Z | UPDATED | architecture/overview | Active; module map points to the HLD; CLI row |
| 2026-11-23T18:00:00Z | UPDATED | plans/roadmap | P5 done except the Hub PR; post-release fixes |
| 2026-11-23T18:00:00Z | UPDATED | schemas/plugin-settings | Points to the generated reference; how settings stay in step |
| 2026-11-23T18:00:00Z | UPDATED | schemas/conform-spec | Points to the generated reference instead of duplicating it |
| 2026-11-23T18:00:00Z | UPDATED | components/metadata-and-errors | members_dropped; BATCH built; doctor reports an error |
| 2026-11-23T18:00:00Z | UPDATED | components/type-system-and-builtins | Vector kernels built (P4); conditionals |
| 2026-11-23T18:00:00Z | UPDATED | components/name-conformer | Declared shapes; column flatten; collapse |
| 2026-11-23T18:00:00Z | UPDATED | components/execution-engines | Every row through the row executor; BATCH vs RECORD triage |
| 2026-11-23T18:00:00Z | UPDATED | concepts/clean-landing-contract | Active; tested by tests/test_contract.py; reserved dialects; compatibility mode |
| 2026-11-23T18:00:00Z | UPDATED | decisions/0002-transform-authoring | What vectorises, as built |
| 2026-11-23T18:00:00Z | UPDATED | decisions/0005-sdc-metadata | doctor reports an error |
| 2026-11-23T18:00:00Z | UPDATED | decisions/0010-stream-map-superset | Inference note is INFO |
| 2026-11-23T18:00:00Z | UPDATED | qa/test-strategy | Contract layer; definition of done |
| 2026-11-23T18:00:00Z | UPDATED | qa/benchmarks | Baseline from CI runners; 60% floor on CI; 3x columnar; re-recording |
| 2026-11-23T18:00:00Z | UPDATED | runbooks/wiki-maintenance | Wiki changes via pull requests; what claim tests check; ADR conventions |
| 2026-11-23T18:00:00Z | UPDATED | runbooks/dev-environment | Definition of done, generated files, checklists (MAPC-145) |
| 2026-11-23T18:00:00Z | UPDATED | ci-cd/pipeline | All jobs; publishing on; release job |
| 2026-11-23T20:00:00Z | UPDATED | plans/roadmap | 0.2.0 released (MAPC-147) |
| 2026-11-23T20:00:00Z | UPDATED | runbooks/release | 0.2.0 released this way |
| 2026-11-24T12:00:00Z | UPDATED | concepts/clean-landing-contract | Copy-ready reviewer snippet, two variants (MAPC-67) |
| 2026-11-24T12:00:00Z | UPDATED | plans/roadmap | P6 in progress: 11.1, 11.3 done (MAPC-67, MAPC-69) |
