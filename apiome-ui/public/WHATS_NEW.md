# Apiome 07-2026 RC2

We continue to improve the platform based on your feedback with improvements and new features!

---

## Features

- Import: OpenAPI-family conformance matrix (Swagger 2.0, OAS 3.0/3.1/3.2, Arazzo) runs in CI — detect/normalize agreement, entity counts, fingerprint stability, and Project routing are regression-gated (MFI-30.4)
- Import: OpenAPI 3.2 documents (QUERY method, additionalOperations, hierarchical tags) now import, normalize, lint, and publish through the multi-format SPI; fidelity preview notes 3.2→3.1 conversion

## Bug Fixes

- Import: Arazzo workflow documents now import through the multi-format SPI with canonical model, lint, and step-level diff support
- Browser: Updated to show MCP Catalog
- Browser: Updated to show activity spinner when searching
- Catalog: Implementation of the catalog to import API sources other than OpenAPI and Arazzo
- Catalog: Implements gRPC/Protobuf/GraphQL/AsyncAPI import cataloging
- CLI: Corrected Swagger 2.0 support in auto import mode
- CLI: Adds --force option to import so that warnings do not prevent publication
- CLI: Import shows correct elapsed time for an import job
- CLI: Adds "--import-timeout (seconds)" option to import to override 120 second timeout
- CLI: Adds MCP registration functionality to the system
- DB: Optimizations made to increase speed for import processing
- DB: Implements catalog storage and indexing
- Import: Corrected import for Swagger responses in paths to capture the schema properly for array items
- Import: Import speed greatly improved
- Import: Special cases with unicode characters are now properly handled
- Import: Better duplication checks - now compares project and version IDs before rejecting
- Import: Fixes publish flag when importing via CLI
- Import: Publish uses short note via description, title, or slug and version if not provided
- Import: Updates import service to include benchmarking output
- Import: Fixes linting problem in rare cases during import
- Import: Corrects base ref and $ref external dereferencing
- Import: Updating class creation step to increase speed using transactions and commits in groups
- Import: Catalog import dialog accepts `.zip`/`.tar.gz` archives for multi-file gRPC/GraphQL/AsyncAPI sources (MFI-29.1)
- Import: gRPC, GraphQL, and AsyncAPI adapters accept multi-document fileset input — split SDL, proto trees, and AsyncAPI suites resolve cross-file refs with identical fingerprints to pre-flattened imports (MFI-29.2)
- REST: Swagger 2.0 documents normalize into the canonical model through the import SPI (MFI-30.1), closing the detect-without-normalize gap for cross-format diff and catalog persistence
- Projects: Now displays quality and linting information in each project
- UI: Fixes Published Versions viewing of OpenAPI and Arazzo URLs
- UI: Fixes Published Versions list so versions starting with a "v" don't duplicate and show "vv"
- UI: Adds the ability to import MCP servers as an input for API cataloging
- UI: Adds MCP linting and scoring based on interally set criteria
- UI: Repositories are no longer in preview
- UI: MCP entries provide a small summary once imported
- UI: Updated MCP registries to be published either public or private
- UI: Applied Fable 5 to improve overall UI additions
- UI: Improved Profile layout
- UI: Fixed sidebar so that "Sunset Timeline" doesn't also highlight Projects at the same time
- UI: Fixed sidebar to be static with scrollable content to the right-hand side
- Naming: Renamed the project to Apiome

---

View our YouTube channel [here](https://www.youtube.com/) for detailed tutorials and walkthroughs!

---

## Feedback

We'd love to hear your thoughts! Your feedback helps us make Apiome better.

---

**Thank you for using Apiome!**

*Last updated: June 23, 2026*

