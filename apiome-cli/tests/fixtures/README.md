# CLI test fixtures

Synthetic OpenAPI, Arazzo, AsyncAPI, GraphQL, and gRPC/Protobuf documents used by pytest and integration tests. They contain **no credentials, API keys, or PII** — only example titles, paths, channels, types, and workflow IDs suitable for mocked REST tests.

| File | Purpose |
|------|---------|
| `checkout.arazzo.yaml` | Minimal Arazzo 1.0 import example |
| `payments-openapi.json` | Minimal OpenAPI 3.1 import example |
| `reconstructed-openapi.json` | Example browse spec export payload |
| `streetlights-asyncapi-2.6.yaml` | Minimal AsyncAPI 2.6 event API import example |
| `user-events-asyncapi-3.0.json` | Minimal AsyncAPI 3.0 event API import example |
| `account-asyncapi-3.1.yaml` | Minimal AsyncAPI 3.1 event API import example |
| `blog-graphql.graphql` | Minimal GraphQL SDL import example (Query/Mutation/types/enum) |
| `inventory-graphql.gql` | Minimal GraphQL SDL import example (`.gql` extension) |
| `echo-grpc.proto` | Self-contained proto3 gRPC service import example (`echo.v1`) |
| `export-openapi-lossless.json` | Reconstructed OpenAPI 3.1 document returned by the browse export, for `export openapi` round-trip tests |
| `export-grpc.proto` | Emitted proto3 document returned by `/export/document`, for `export grpc` round-trip tests (MFX-12.5) |
| `export-preview-grpc-lossless.json` | `ExportPreviewResponse` for a lossless protobuf export (native gRPC source) |
| `export-preview-grpc-lossy.json` | `ExportPreviewResponse` for a lossy protobuf export (REST/OpenAPI source), with advisory |
| `export-preview-lossless.json` | `ExportPreviewResponse` for a lossless OpenAPI export (fidelity preview) |
| `export-preview-lossy.json` | `ExportPreviewResponse` for a lossy (event-source) OpenAPI export, with advisory |
| `export-targets.json` | `ExportTargetsResponse` listing the `openapi` + `sample` emitter targets |
