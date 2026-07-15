# Planned Feature Roadmap: Repository Connector

## Completed

- REPO-3.3 (#2772): AsyncAPI 2.x/3.x importer persistence — catalog imports write Channel/Operation/Message rows into MFI-2.2 `api_*` tables, promote message payloads/headers into designer Classes (`payload_class_id` / `headers_class_id`), keep protocol bindings lossless, isolate per-channel `parse_error` without aborting the document, and round-trip Streetlights + Anyway Jobs through the normalize→persist-codec→emit path.
- REPO-4.1 (#2779): Added a scheduler tick dispatcher that atomically reserves due tracked branches, skips paused repositories, clamps poll cadence to enterprise/non-enterprise minimums, dispatches poll jobs to `repo.poll.<priority>`, and records `repository.polled` workflow audit rows per dispatch.
- REPO-3.8 (#2777): Added an in-scan virtual filesystem `$ref` resolver for repository imports that resolves relative file-path and JSON-pointer chains in dependency order, memoizes repeated nodes per scan, and emits deterministic cycle errors for cross-file loops.
- REPO-3.5 (#2774): Added a standalone repository JSON Schema importer for Draft 7, 2019-09, and 2020-12 documents, preserving source `$id`/draft metadata on class schemas, keeping composition keywords intact, and delegating sibling `$ref` resolution through the REPO-3.8 resolver contract.
- REPO-3.2 (#2771): Added `swagger_2_0` support to the repository OpenAPI importer pipeline so Swagger 2.0 repository specs run through the same conversion/parser path as OpenAPI 3.x, with semantic parity tests covering definitions, paths, parameters, and security scheme mapping.
- REPO-3.1 (#2770): Added a repository OpenAPI importer hook that reuses the existing one-shot `parseOpenAPISpec` conversion pipeline, accepts normalized `{source, format, content, refs}` input for repository ingestion, and delegates cross-file `$ref` handling to the REPO-3.8 resolver contract with fixture-set parity coverage.
- REPO-2.7 (#2768): Added scan diff classification against the previous completed scan keyed by `(repository_id, path)`, including persisted `new/unchanged/modified/removed` per-file statuses with carried-forward `removed` rows and `{added, modified, removed, unchanged}` diff summary counts.
- REPO-2.6 (#2767): Added `repository_scan` and `repository_file` history support with cursor-paginated scan/file REST endpoints, `force` rescan behavior, and `skipped_unchanged` audit/event tracking.
- REPO-2.4 (#2765): Added `.objectified/repo.yaml` manifest support with published JSON Schema validation, non-fatal `manifest_error` repository file recording, per-spec format/polling overrides, and untracked discovery output for files not explicitly listed.
- REPO-2.3 (#2764): Added provider-agnostic spec format detection with filename heuristics plus 64 KB content sniffing, confidence/discriminator output, and stream-mode sniffing for files larger than 5 MB.
- REPO-2.2 (#2763): Added scanner include/exclude rule support with published default ignore patterns, manifest-level ignore merge behavior, ignore skip telemetry (`files_skipped_by_ignore`), and explicit `specs` precedence over ignores.
- REPO-2.1 (#2762): Added a streaming repository tree walker that iterates files at a commit SHA, enforces typed scan limits (`SCAN_LIMIT_EXCEEDED`), applies subpath glob filtering at the walker boundary, and emits `repository.scan.walked` workflow audit events.
- REPO-1.8 (#2760): Implemented a Bitbucket Cloud repository provider adapter for REST API 2.0 with shared contract coverage, UUID-based webhook verification, and linked-account availability for Bitbucket linking.
- REPO-1.7 (#2759): Implemented the GitLab repository provider adapter with full contract coverage, keyset pagination for repository listing, and GitLab webhook registration/signature verification.
- REPO-1.4 (#2756): Added repository registration UI flow and REST registration endpoint for GitHub repositories.
- REPO-1.5 (#2757): Added per-repository branch management with per-branch subpath and polling settings, including default branch preselection and wildcard branch patterns.
- REPO-1.6 (#2758): Added repository settings edit/archive/unarchive/delete flows with typed delete confirmation, archival audit events, and deletion cascades for repository relations.

## Open Issues

- None currently tracked in this document.
