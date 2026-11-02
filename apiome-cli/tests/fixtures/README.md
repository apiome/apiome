# CLI test fixtures

Synthetic OpenAPI, Arazzo, AsyncAPI, GraphQL, gRPC/Protobuf, OData, Avro, WSDL, RAML, and API Blueprint documents used by pytest and integration tests. They contain **no credentials, API keys, or PII** — only example titles, paths, channels, types, and workflow IDs suitable for mocked REST tests.

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
| `bookshop-odata-v4.edmx` | OData v4 CSDL XML service metadata (entity types, enum, bound action, function import) for `import odata` file and `--discover` tests (MFI-11.6) |
| `sales-odata-v2.xml` | SAP Gateway-style OData v2 service metadata (associations, `sap:` annotations, `m:HttpMethod` function import) for `import odata` tests (MFI-11.6) |
| `orders-avro.avsc` | Avro `.avsc` record schema (uuid / timestamp-millis / decimal logical types, enum with a `default`, nullable aliased field) for `import avro` file and `--registry` tests (MFI-12.6) |
| `orders-avro.avdl` | The same orders schema as an Avro IDL protocol (enum default, `error`, one RPC message) for `import avro` tests (MFI-12.6) |
| `calculator-soap11.wsdl` | WSDL 1.1 document/literal service with a fault and SOAP 1.1 + SOAP 1.2 bindings, for `import wsdl` file and `--discover` tests (MFI-13.6) |
| `shipping-wsdl20.wsdl` | WSDL 2.0 description (in-out and robust-in-only operations, interface fault, SOAP binding) for `import wsdl` tests (MFI-13.6) |
| `orders-wsdl-set/` | WSDL 1.1 description in `wsdl/` whose types live in `schemas/orders.xsd` (`../schemas/…`) and `schemas/common/address.xsd`, for directory `import wsdl` tests (MFI-13.6, MFI-13.1) |
| `petstore-raml10.raml` | Self-contained RAML 1.0 API (types, a `collection` resource type, a `paged` trait) for `import raml` file tests (MFI-15.5) |
| `bookstore-raml-set/` | RAML 1.0 API whose `Book` type is `!include`d from `types/` and whose `Error` type and `paged` trait come from a `uses` library in `libraries/`, for directory `import raml` tests (MFI-15.5) |
| `shelter-apiblueprint.apib` | API Blueprint 1A with resource groups, an enum parameter, a named request, response headers, and MSON inheritance (`## Cat (Pet)`) and a mixin (`+ Include Problem`), for `import apiblueprint` tests (MFI-16.4) |
| `notes-apiblueprint.md` | A minimal API Blueprint saved with a `.md` extension, for `import apiblueprint` tests (MFI-16.4) |
| `export-openapi-lossless.json` | Reconstructed OpenAPI 3.1 document returned by the browse export, for `export openapi` round-trip tests |
| `export-grpc.proto` | Emitted proto3 document returned by `/export/document`, for `export grpc` round-trip tests (MFX-12.5) |
| `export-graphql.graphql` | Emitted GraphQL SDL returned by `/export/document`, for `export graphql` round-trip tests (MFX-13.5) |
| `export-avro.avsc` | Emitted Avro `.avsc` JSON returned by `/export/document`, for `export avro` round-trip tests (MFX-19.5) |
| `export-preview-grpc-lossless.json` | `ExportPreviewResponse` for a lossless protobuf export (native gRPC source) |
| `export-preview-grpc-lossy.json` | `ExportPreviewResponse` for a lossy protobuf export (REST/OpenAPI source), with advisory |
| `export-preview-graphql-lossless.json` | `ExportPreviewResponse` for a lossless GraphQL export (native Graph source) |
| `export-preview-graphql-lossy.json` | `ExportPreviewResponse` for a lossy GraphQL export (REST/OpenAPI source), with advisory |
| `export-preview-avro-lossless.json` | `ExportPreviewResponse` for a lossless Avro export (native data-schema source) |
| `export-preview-avro-types-only.json` | `ExportPreviewResponse` for a types-only Avro export (REST/OpenAPI source), with critical advisory |
| `export-preview-lossless.json` | `ExportPreviewResponse` for a lossless OpenAPI export (fidelity preview) |
| `export-preview-lossy.json` | `ExportPreviewResponse` for a lossy (event-source) OpenAPI export, with advisory |
| `export-targets.json` | `ExportTargetsResponse` listing the `openapi` + `sample` emitter targets |
