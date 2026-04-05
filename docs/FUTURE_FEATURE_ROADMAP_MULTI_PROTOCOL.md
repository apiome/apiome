# Objectified: Multi-Protocol Support - Feature Roadmap

> Multi-protocol schema design platform extending Objectified beyond REST to support GraphQL, gRPC/Protocol Buffers, and AsyncAPI—with visual editors for each protocol, bidirectional schema translation between formats, and a cross-protocol gateway for unified API access.
>
> **Revenue Model**: Enterprise tier feature, per-protocol add-ons
>
> **Tech Stack**: NextJS App Router, Radix UI primitives, Monaco Editor, GraphQL.js, protobuf.js, AsyncAPI parser, REST/OpenAPI 3.1, PostgreSQL, Envoy (cross-protocol proxy)
>
> **Last Updated**: April 2, 2026

---

## MVP Definition

- GraphQL schema editor with type definitions, query/mutation builders, and directive configuration
- Protobuf message designer with service definitions, enum/oneof support, and import management
- AsyncAPI channel designer with message schemas and protocol bindings (Kafka, MQTT, WebSocket)
- Bidirectional schema translation between OpenAPI, GraphQL, and Protobuf formats
- Cross-protocol gateway routing REST requests to GraphQL/gRPC backends with unified authentication
- Breaking change detection for proto files and GraphQL schemas
- Protocol-specific playground and testing tools for each supported format

---

## Epic 1: GraphQL Schema Design & Tooling

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 1.1 (#1342) | GraphQL Schema Editor | Visual schema designer with type definitions, directives, and resolver mapping | `enhancement`, `mvp`, `multi-protocol`, `rest`, `ai-generated` | Yes |
| 1.2 (#1360) | Query, Mutation & Subscription Builder | Build and validate GraphQL operations with schema-aware autocomplete | `enhancement`, `mvp`, `multi-protocol`, `ai-generated` | Yes |
| 1.3 (#1365) | GraphQL Playground & Performance Analysis | Integrated playground with query profiling and DataLoader pattern detection | `enhancement`, `mvp`, `multi-protocol`, `ai-generated` | No |
| 1.4 (#1371) | Federation & Advanced Features | Apollo Federation support, schema stitching, and Relay-style pagination | `enhancement`, `multi-protocol`, `ai-generated` | No |

### Detailed Issue Descriptions

---

#### 1.1 (#1342) — GraphQL Schema Editor

The GraphQL Schema Editor provides a visual environment for designing GraphQL schemas within Objectified. Instead of writing SDL by hand, developers use a structured form-based editor alongside a live Monaco Editor pane showing the generated SDL. The visual editor covers object types, input types, interfaces, unions, enums, custom scalars, and directives. Each type definition card shows its fields with their types, arguments, nullability, and descriptions.

The editor page lives at `/app/protocols/graphql/[schemaId]/editor` in the NextJS app. The left panel contains a type explorer using Radix `Accordion` to expand/collapse type categories (Objects, Inputs, Interfaces, Unions, Enums, Scalars). Selecting a type opens its detail view in the center panel where fields are displayed in a Radix `Table` with inline editing. Adding a field opens a Radix `Dialog` with `Select` dropdowns for type selection, `Switch` for nullability, and `TextArea` for description. The right panel shows the live SDL output in a read-only Monaco Editor.

Resolver mapping connects each field to a data source. The editor supports mapping fields to REST endpoints (using existing Objectified schemas), database queries, or custom resolver stubs. Resolver configurations are stored in PostgreSQL alongside the schema definition and are used by the cross-protocol gateway (Epic 4) to execute queries at runtime.

```
┌──────────────────────────────────────────────────────────────────────┐
│  GraphQL Schema Editor — ProductAPI v2                               │
├──────────────┬──────────────────────────┬────────────────────────────┤
│ Type Explorer │  Type Detail             │  SDL Preview (Monaco)      │
│              │                          │                            │
│ ▼ Objects    │  type Product {          │  type Product {             │
│   Product    │  ┌──────┬──────┬─────┐  │    id: ID!                  │
│   Order      │  │Field │Type  │Null?│  │    name: String!            │
│   User       │  ├──────┼──────┼─────┤  │    price: Float!            │
│ ▼ Inputs     │  │id    │ID!   │ No  │  │    category: Category!      │
│   ProductIn  │  │name  │Str!  │ No  │  │    reviews(first: Int):     │
│ ▼ Enums      │  │price │Float!│ No  │  │      [Review!]!             │
│   Category   │  │...   │      │     │  │  }                          │
│ ▼ Interfaces │  └──────┴──────┴─────┘  │                            │
│   Node       │        [+ Add Field]     │  input ProductInput {      │
│              │                          │    name: String!            │
│ [+ Add Type] │  Resolver: REST → GET    │    price: Float!            │
│              │  /api/v1/products/{id}   │    category: Category!      │
│              │                          │  }                          │
└──────────────┴──────────────────────────┴────────────────────────────┘
```

The backend REST API provides `POST /api/v1/protocols/graphql/schemas` (create), `GET /api/v1/protocols/graphql/schemas/{id}` (retrieve with SDL), `PUT /api/v1/protocols/graphql/schemas/{id}/types` (update types), and `POST /api/v1/protocols/graphql/schemas/{id}/validate` (validate SDL). Schema definitions are stored in PostgreSQL with types as JSONB and the compiled SDL as a text column regenerated on each change.

**Acceptance Criteria**

- Visual editor supports object types, input types, interfaces, unions, enums, and custom scalars
- Fields are configurable with type, arguments, nullability, default values, and descriptions
- Live SDL preview updates in real-time as types are modified in the visual editor
- Directive configuration (`@deprecated`, `@auth`, custom directives) is supported per field and type
- Resolver mapping links fields to REST endpoints, database queries, or custom stubs
- Schema validation reports SDL errors with line numbers and suggestions
- Type explorer uses Radix `Accordion` and field editing uses Radix `Dialog` and `Table`

**Part of Epic: GraphQL Schema Design & Tooling**

---

#### 1.2 (#1360) — Query, Mutation & Subscription Builder

The Query, Mutation & Subscription Builder provides a visual interface for composing GraphQL operations against a defined schema. Developers select root fields, expand nested types to choose subfields, configure arguments with form inputs, and see the generated operation string update live. This builder serves both documentation (showing consumers how to query the API) and testing (operations can be executed against a live endpoint).

The builder page at `/app/protocols/graphql/[schemaId]/operations` renders a three-column layout. The left column shows available root fields grouped by operation type (Query, Mutation, Subscription) using Radix `Tabs`. The center column displays the operation being constructed as an interactive tree where each node is a field that can be toggled on/off. Argument inputs appear inline with type-aware form controls (number input for `Int`, `Select` for enums, nested forms for input types). The right column shows the generated GraphQL operation string and variables JSON.

Operations can be saved to a library per schema, functioning as reusable query templates. Saved operations are versioned alongside the schema—when a schema changes, the builder flags operations that reference removed or modified fields. The REST API exposes `POST /api/v1/protocols/graphql/schemas/{id}/operations` (save), `GET /api/v1/protocols/graphql/schemas/{id}/operations` (list), and `POST /api/v1/protocols/graphql/schemas/{id}/operations/{opId}/validate` (check against current schema).

**Acceptance Criteria**

- Builder displays available queries, mutations, and subscriptions from the schema
- Nested field selection uses an expandable tree with toggle checkboxes per field
- Argument inputs render type-appropriate form controls (number, text, enum `Select`, nested form)
- Generated operation string and variables JSON update in real-time
- Saved operations are versioned and flagged when schema changes break them
- Operations are executable from the builder, dispatching to the GraphQL endpoint and displaying results

**Part of Epic: GraphQL Schema Design & Tooling**

---

#### 1.3 (#1365) — GraphQL Playground & Performance Analysis

The GraphQL Playground integrates a full-featured query execution environment with performance profiling. Developers write queries in a Monaco Editor with schema-aware autocomplete, execute them against a configured endpoint, and view results alongside timing breakdowns per resolver. The playground also detects N+1 query patterns and suggests DataLoader optimizations.

The playground page at `/app/protocols/graphql/[schemaId]/playground` embeds a Monaco Editor with GraphQL syntax highlighting and IntelliSense powered by the schema. A variables panel (Radix `Tabs` switching between Variables, Headers, and Settings) sits below the editor. The results panel shows the JSON response with syntax highlighting, a timing waterfall showing resolver execution duration, and a trace panel showing the full execution path.

Performance analysis runs during query execution. The profiler records resolver execution time, database query count, and data volume per field. When it detects N+1 patterns (multiple sequential queries for the same entity type), it surfaces a warning with a suggested DataLoader batching pattern. Integration with Apollo Studio is provided via `PUT /api/v1/protocols/graphql/schemas/{id}/integrations` for schema registry synchronization. Hasura integration supports schema introspection from a running Hasura instance.

The REST API exposes `POST /api/v1/protocols/graphql/schemas/{id}/execute` (run query), `GET /api/v1/protocols/graphql/schemas/{id}/traces` (execution traces), and `PUT /api/v1/protocols/graphql/schemas/{id}/integrations` (configure external tools).

**Acceptance Criteria**

- Monaco Editor provides GraphQL syntax highlighting and schema-aware autocomplete
- Query execution returns results with timing breakdown per resolver in a waterfall view
- N+1 detection flags queries that trigger sequential resolver calls for the same type
- DataLoader suggestions include sample batching code in the warning panel
- Apollo Studio integration syncs schema definitions bidirectionally
- Hasura integration supports schema introspection from a running Hasura instance
- Execution traces are stored and queryable for performance trend analysis

**Part of Epic: GraphQL Schema Design & Tooling**

---

#### 1.4 (#1371) — Federation & Advanced Features

Apollo Federation allows composing a single GraphQL API from multiple independently deployed subgraph schemas. This issue adds federation-aware tooling to the schema editor: `@key` directive configuration for entity definitions, entity reference field management, and a composition validator that checks all subgraphs for compatibility before merging into a supergraph.

The federation management page at `/app/protocols/graphql/federation` displays all registered subgraphs in a Radix `Table` with columns for name, URL, schema version, and composition status. Adding a subgraph opens a Radix `Dialog` where the developer specifies the name, endpoint URL, and uploads or introspects the schema. Supergraph composition runs automatically when any subgraph changes, with errors displayed inline.

Relay-style pagination is supported as a first-class pattern. When a field returns a list type, the editor offers a "Convert to Connection" action that wraps the field in a Relay connection type with `edges`, `node`, `cursor`, and `pageInfo` fields. The generated SDL follows the Relay specification, and the resolver mapping is updated to support cursor-based pagination arguments (`first`, `after`, `last`, `before`).

The REST API exposes `POST /api/v1/protocols/graphql/federation/subgraphs` (register), `DELETE /api/v1/protocols/graphql/federation/subgraphs/{id}` (remove), `POST /api/v1/protocols/graphql/federation/compose` (trigger composition), and `GET /api/v1/protocols/graphql/federation/supergraph` (retrieve composed supergraph SDL).

**Acceptance Criteria**

- Subgraph registration supports schema upload and endpoint introspection
- `@key` directive configuration is available in the schema editor for entity types
- Supergraph composition validates all subgraphs and reports compatibility errors
- Composition runs automatically when any subgraph schema is updated
- Relay connection type conversion wraps list fields with proper edges/node/pageInfo structure
- Cursor-based pagination arguments (`first`, `after`, `last`, `before`) are added to converted fields
- Federation composition errors reference the specific subgraph and conflicting types

**Part of Epic: GraphQL Schema Design & Tooling**

---

## Epic 2: gRPC & Protocol Buffer Support

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 2.1 (#1400) | Protobuf Message Designer | Visual editor for protobuf messages, enums, oneofs, and imports | `enhancement`, `mvp`, `multi-protocol`, `rest`, `ai-generated` | Yes |
| 2.2 (#1409) | gRPC Service Definition Editor | Design gRPC services with unary, streaming, and bidirectional RPCs | `enhancement`, `mvp`, `multi-protocol`, `rest`, `ai-generated` | Yes |
| 2.3 (#1417) | Proto Generation & Client Stubs | Generate .proto files and language-specific client/server code | `enhancement`, `mvp`, `multi-protocol`, `ai-generated` | No |
| 2.4 (#1427) | gRPC Testing & Breaking Change Detection | Test gRPC endpoints and detect breaking changes across proto versions | `enhancement`, `multi-protocol`, `rest`, `ai-generated` | No |

### Detailed Issue Descriptions

---

#### 2.1 (#1400) — Protobuf Message Designer

The Protobuf Message Designer provides a visual editor for defining Protocol Buffer messages without writing proto syntax manually. Developers create message types using a form-based interface that supports all proto3 features: scalar fields (int32, string, bytes, etc.), nested messages, enums, repeated fields, map fields, oneof groups, and reserved fields. A live preview pane shows the generated `.proto` syntax updating as changes are made.

The editor page at `/app/protocols/protobuf/[schemaId]/messages` renders a message explorer on the left using Radix `Accordion` to group messages by proto package. Selecting a message opens the field editor in a Radix `Table` with columns for field number, name, type, label (optional/repeated), and options. Adding a field opens a Radix `Dialog` with `Select` for type (including custom message types and well-known types like `google.protobuf.Timestamp`), `Switch` for repeated, and a number input for field number with auto-increment.

Import management allows referencing types from other proto files. The import panel shows available proto packages (both user-defined and well-known types from `google/protobuf/`) and lets developers add imports via Radix `Combobox` search. Circular import detection runs on save and flags violations. The proto syntax is validated on every change, with errors displayed inline in the Monaco Editor preview.

```
┌───────────────────────────────────────────────────────────────────┐
│  Protobuf Message Designer — order-service.proto                  │
├──────────────┬──────────────────────────┬─────────────────────────┤
│ Messages     │  message Order           │ syntax = "proto3";      │
│              │  ┌────┬──────┬─────────┐ │                         │
│ ▼ orders     │  │ #  │ Name │ Type    │ │ package orders;         │
│   Order      │  ├────┼──────┼─────────┤ │                         │
│   OrderItem  │  │ 1  │ id   │ string  │ │ import "google/proto... │
│   Status     │  │ 2  │ items│ repeated│ │                         │
│ ▼ common     │  │    │      │ OrderIt.│ │ message Order {         │
│   Money      │  │ 3  │ total│ Money   │ │   string id = 1;       │
│   Address    │  │ 4  │ stat.│ Status  │ │   repeated OrderItem    │
│              │  └────┴──────┴─────────┘ │     items = 2;          │
│ [+ Message]  │       [+ Add Field]      │   Money total = 3;      │
│              │                          │   Status status = 4;    │
│ Imports: 2   │  oneof delivery {        │ }                       │
│ google/prot..│    Address pickup = 5;   │                         │
│ common.proto │    Address shipping = 6; │ enum Status {           │
│              │  }                       │   PENDING = 0;          │
└──────────────┴──────────────────────────┴─────────────────────────┘
```

The backend REST API provides `POST /api/v1/protocols/protobuf/schemas` (create), `GET /api/v1/protocols/protobuf/schemas/{id}` (retrieve with proto source), `PUT /api/v1/protocols/protobuf/schemas/{id}/messages` (update messages), and `POST /api/v1/protocols/protobuf/schemas/{id}/validate` (validate proto syntax). Message definitions are stored in PostgreSQL with fields as JSONB and the compiled `.proto` source regenerated on each change.

**Acceptance Criteria**

- Visual editor supports all proto3 field types including nested messages, maps, and well-known types
- Oneof groups are configurable with visual grouping of member fields
- Enum definitions support value assignment with alias detection
- Field numbers auto-increment and validate for uniqueness and reserved range conflicts
- Import management resolves well-known types and user-defined packages with circular dependency detection
- Live `.proto` preview in Monaco Editor updates on every change with syntax error highlighting
- Reserved field numbers and names are tracked and enforced during field creation

**Part of Epic: gRPC & Protocol Buffer Support**

---

#### 2.2 (#1409) — gRPC Service Definition Editor

The gRPC Service Definition Editor extends the protobuf designer to define gRPC services with their RPC methods. Each service groups related RPC methods, and each method specifies its request message, response message, and streaming mode: unary (request-response), server streaming (one request, stream of responses), client streaming (stream of requests, one response), or bidirectional streaming (both sides stream).

The service editor page at `/app/protocols/protobuf/[schemaId]/services` displays registered services in a Radix `Table` with columns for service name, method count, and proto package. Selecting a service expands its methods in a nested table. Adding an RPC method opens a Radix `Dialog` with `Select` dropdowns for request and response message types (populated from defined messages), and a `RadioGroup` for streaming mode selection. Metadata configuration (custom headers/trailers) is available per method.

```
service OrderService {
  rpc CreateOrder (CreateOrderRequest)
      returns (Order);                          // Unary

  rpc StreamOrderUpdates (OrderFilter)
      returns (stream OrderUpdate);             // Server streaming

  rpc BatchCreateOrders (stream CreateOrderRequest)
      returns (BatchResult);                    // Client streaming

  rpc OrderChat (stream ChatMessage)
      returns (stream ChatMessage);             // Bidirectional
}
```

The editor validates that request and response types reference existing messages within the proto package or its imports. Deadline/timeout configuration is available per RPC method with a default of 30 seconds. The REST API exposes `POST /api/v1/protocols/protobuf/schemas/{id}/services` (create service), `PUT /api/v1/protocols/protobuf/schemas/{id}/services/{serviceId}/methods` (manage methods), and `GET /api/v1/protocols/protobuf/schemas/{id}/services` (list with method details).

**Acceptance Criteria**

- Service editor supports unary, server streaming, client streaming, and bidirectional streaming RPCs
- Request and response type selectors show only valid message types from the proto package and imports
- Streaming mode is visually indicated with icons distinguishing the four RPC patterns
- Metadata configuration allows defining custom headers and trailers per RPC method
- Deadline/timeout defaults are configurable per method and per service
- Generated `.proto` output includes service definitions with correct streaming annotations

**Part of Epic: gRPC & Protocol Buffer Support**

---

#### 2.3 (#1417) — Proto Generation & Client Stubs

Proto Generation & Client Stubs produces production-ready `.proto` files and generates language-specific client and server code from the visual proto definitions. The generation pipeline compiles the JSONB message and service definitions into canonical `.proto` files, then runs language-specific code generators for Go, TypeScript/JavaScript, Python, Java, and Rust.

The generation page at `/app/protocols/protobuf/[schemaId]/generate` presents language options as a grid of selectable cards. Selecting a language opens a Radix `Dialog` with generation options: output package name, import path prefix, and plugin-specific flags (e.g., `grpc-gateway` for Go, `nice-grpc` for TypeScript). A "Generate" button triggers the backend pipeline, and the output is downloadable as a ZIP archive organized by language.

Server stubs include the service interface definition and a skeleton implementation with TODO markers for each RPC method. Client stubs include a typed client class with methods for each RPC, handling connection management, deadline propagation, and metadata attachment. A gRPC reflection service descriptor is also generated, enabling runtime schema discovery for debugging tools.

The REST API exposes `POST /api/v1/protocols/protobuf/schemas/{id}/generate` (trigger generation with language and options), `GET /api/v1/protocols/protobuf/schemas/{id}/generate/{jobId}` (check status), and `GET /api/v1/protocols/protobuf/schemas/{id}/generate/{jobId}/download` (download archive). Generation jobs run asynchronously with status tracking in a `proto_generation_jobs` table.

**Acceptance Criteria**

- `.proto` files are generated from visual definitions with correct syntax and import paths
- Client stubs are generated for Go, TypeScript, Python, Java, and Rust
- Server stubs include interface definitions and skeleton implementations with TODO markers
- gRPC reflection service descriptor is included in generated output
- Generation options (package name, import prefix, plugins) are configurable per language
- Generated code is downloadable as a ZIP archive with a clear directory structure
- Generation jobs run asynchronously with status polling and completion notification

**Part of Epic: gRPC & Protocol Buffer Support**

---

#### 2.4 (#1427) — gRPC Testing & Breaking Change Detection

gRPC Testing provides an interactive environment for sending RPC requests to a live gRPC endpoint and inspecting responses, similar to Postman but purpose-built for gRPC. Breaking Change Detection compares proto versions and flags incompatible changes before they ship.

The testing page at `/app/protocols/protobuf/[schemaId]/test` connects to a gRPC endpoint via server reflection or a loaded proto definition. Available services and methods are displayed in a Radix `Select` dropdown. The request editor renders a form generated from the request message definition, with fields for each message field. For streaming RPCs, a message timeline shows sent and received messages in chronological order. Responses display the deserialized message alongside raw bytes and metadata.

Breaking change detection runs automatically when a proto schema is updated. The detector compares the new version against the previous version and classifies changes as: safe (adding optional fields, adding new RPCs), warning (adding required fields, changing field types with compatible wire format), or breaking (removing fields, changing field numbers, removing RPCs, changing streaming mode). Results are displayed on the schema editor page as inline annotations.

The REST API exposes `POST /api/v1/protocols/protobuf/schemas/{id}/test` (execute RPC), `GET /api/v1/protocols/protobuf/schemas/{id}/breaking-changes` (compare against previous version), and `POST /api/v1/protocols/protobuf/schemas/{id}/compare` (compare two arbitrary versions). Breaking change reports are stored per version pair for audit purposes.

**Acceptance Criteria**

- Testing page connects to gRPC endpoints via reflection or uploaded proto definitions
- Unary, server streaming, client streaming, and bidirectional RPCs are all testable
- Request forms are auto-generated from message definitions with type-appropriate inputs
- Breaking change detection classifies changes as safe, warning, or breaking
- Removing fields, changing field numbers, and removing RPCs are flagged as breaking
- Breaking change report is generated automatically on schema update and blocks publishing when breaking changes are present
- Streaming RPC testing displays a chronological message timeline with send/receive indicators

**Part of Epic: gRPC & Protocol Buffer Support**

---

## Epic 3: AsyncAPI & Event-Driven Architecture

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 3.1 (#1447) | AsyncAPI Visual Editor | Channel designer with message schemas and protocol bindings | `enhancement`, `mvp`, `multi-protocol`, `rest`, `ai-generated` | Yes |
| 3.2 (#1458) | Event Pattern Designer | Visual tools for publish/subscribe, event sourcing, CQRS, and saga patterns | `enhancement`, `mvp`, `multi-protocol`, `ai-generated` | Yes |
| 3.3 (#1464) | Event Streaming Integration | Connect to Kafka, RabbitMQ, Redis Streams, and cloud event services | `enhancement`, `multi-protocol`, `rest`, `ai-generated` | No |
| 3.4 (#1471) | Channel Testing & Message Simulation | Publish test messages, subscribe to channels, and validate event payloads | `enhancement`, `multi-protocol`, `ai-generated` | No |

### Detailed Issue Descriptions

---

#### 3.1 (#1447) — AsyncAPI Visual Editor

The AsyncAPI Visual Editor provides a form-driven interface for designing event-driven APIs following the AsyncAPI 3.0 specification. Developers define channels (topics/queues), messages (event payloads), servers (broker connections), and protocol bindings without writing YAML. A live preview pane shows the generated AsyncAPI document alongside a channel topology diagram.

The editor page at `/app/protocols/asyncapi/[schemaId]/editor` uses a multi-tab layout (Radix `Tabs`) with sections for Channels, Messages, Servers, and Security. The Channels tab displays a Radix `Table` of defined channels with columns for name, protocol, publish/subscribe operations, and message type. Adding a channel opens a Radix `Dialog` with fields for channel name (e.g., `orders/created`), protocol binding selection (Kafka, AMQP, MQTT, WebSocket), and operation type.

Message schemas reuse Objectified's existing schema definition infrastructure. When defining a message, developers select from existing schema classes or create new ones inline. Each message specifies headers, payload schema, correlation ID, and content type. Protocol-specific bindings (Kafka partition key, AMQP routing key, MQTT QoS level) are configurable per channel-message pair. Server definitions specify broker connection details: URL, protocol, description, and security scheme (SASL, TLS, OAuth2).

The REST API provides `POST /api/v1/protocols/asyncapi/schemas` (create), `GET /api/v1/protocols/asyncapi/schemas/{id}` (retrieve with generated YAML), `PUT /api/v1/protocols/asyncapi/schemas/{id}/channels` (manage channels), and `POST /api/v1/protocols/asyncapi/schemas/{id}/validate` (validate against AsyncAPI spec).

**Acceptance Criteria**

- Visual editor supports channels, messages, servers, and security scheme definitions
- Protocol bindings are configurable for Kafka, AMQP, MQTT, and WebSocket per channel
- Message schemas reference existing Objectified schema classes or define new ones inline
- Server definitions support multiple environments with protocol-specific connection details
- Generated AsyncAPI 3.0 YAML is valid and downloadable from the editor
- Channel topology diagram renders a visual map of publishers, channels, and subscribers
- Validation errors surface inline with references to the AsyncAPI specification

**Part of Epic: AsyncAPI & Event-Driven Architecture**

---

#### 3.2 (#1458) — Event Pattern Designer

The Event Pattern Designer provides visual tooling for modeling common event-driven architecture patterns: publish/subscribe, request/reply, event sourcing, CQRS (Command Query Responsibility Segregation), and saga choreography. Rather than designing channels in isolation, this tool helps developers model the full event flow across services.

The pattern designer at `/app/protocols/asyncapi/[schemaId]/patterns` offers a canvas-style editor where services are represented as blocks and event flows as directed arrows between them. Selecting a pattern template (Radix `DropdownMenu`) scaffolds a starting topology: pub/sub creates one publisher and N subscriber blocks connected via a channel; CQRS creates separate command and query services with an event store in between; saga creates a chain of services with compensating events on each link.

```
Event Sourcing Pattern — Order Service

  ┌──────────┐    OrderCreated     ┌──────────────┐    OrderProjected
  │  Command  │───────────────────▶│  Event Store  │───────────────────▶┌──────────┐
  │  Handler  │    OrderUpdated    │  (Kafka)      │    OrderProjected  │  Read     │
  │           │───────────────────▶│               │───────────────────▶│  Model    │
  └──────────┘    OrderCancelled   └──────────────┘                    └──────────┘
       ▲          ───────────────▶        │
       │                                  │  Replay events
  Commands                                ▼  for rebuild
  from API                          ┌──────────────┐
                                    │  Projection   │
                                    │  Rebuilder    │
                                    └──────────────┘
```

Each service block defines the events it publishes and subscribes to. The designer validates that every published event has at least one subscriber, flags orphan events, and detects cycles in saga chains. Event schemas are linked to the messages defined in the AsyncAPI editor (3.1), ensuring consistency between the pattern model and the API specification.

The REST API exposes `POST /api/v1/protocols/asyncapi/schemas/{id}/patterns` (save pattern), `GET /api/v1/protocols/asyncapi/schemas/{id}/patterns` (list), and `POST /api/v1/protocols/asyncapi/schemas/{id}/patterns/{patternId}/validate` (check for orphan events, cycles, and missing handlers).

**Acceptance Criteria**

- Pattern templates are available for pub/sub, request/reply, event sourcing, CQRS, and saga
- Canvas editor renders services as blocks with directed event flow arrows
- Each service block defines published and subscribed events linked to AsyncAPI messages
- Validation detects orphan events (published but never subscribed) and saga cycles
- CQRS template scaffolds separate command and query paths with an event store
- Saga template includes compensating event definitions for rollback scenarios
- Pattern definitions export as AsyncAPI channel groups with proper operation bindings

**Part of Epic: AsyncAPI & Event-Driven Architecture**

---

#### 3.3 (#1464) — Event Streaming Integration

Event Streaming Integration connects the AsyncAPI designer to live message brokers, enabling developers to browse topics, inspect live messages, and validate that running systems conform to their AsyncAPI schemas. Supported platforms include Apache Kafka, Amazon Kinesis, Azure Event Hubs, RabbitMQ, Redis Streams, and Google Pub/Sub.

The integration page at `/app/protocols/asyncapi/[schemaId]/integrations` displays configured broker connections in a Radix `Table` with status indicators (connected, disconnected, error). Adding a connection opens a Radix `Dialog` with protocol-specific fields: Kafka requires bootstrap servers and optional SASL credentials; RabbitMQ needs an AMQP URL; Redis Streams uses a Redis connection string. Connections are tested on save with a health check probe.

Once connected, the topic browser at `/app/protocols/asyncapi/[schemaId]/topics` shows available topics/queues with metadata (partition count, consumer groups, message count). Selecting a topic displays a live message stream with each message showing its key, value (deserialized against the AsyncAPI message schema), headers, timestamp, and partition/offset. Messages that fail schema validation are highlighted with the validation errors shown inline.

The REST API provides `POST /api/v1/protocols/asyncapi/schemas/{id}/connections` (add broker), `GET /api/v1/protocols/asyncapi/schemas/{id}/connections/{connId}/topics` (list topics), `GET /api/v1/protocols/asyncapi/schemas/{id}/connections/{connId}/topics/{topic}/messages` (recent messages), and `POST /api/v1/protocols/asyncapi/schemas/{id}/connections/{connId}/topics/{topic}/validate` (validate live messages against schema).

**Acceptance Criteria**

- Broker connections are configurable for Kafka, RabbitMQ, Redis Streams, Kinesis, Event Hubs, and Pub/Sub
- Connection health is monitored with status indicators updating in real-time
- Topic browser displays available topics with metadata (partitions, consumer groups, message count)
- Live message stream shows deserialized messages validated against the AsyncAPI schema
- Messages failing schema validation are highlighted with inline error details
- Broker credentials are encrypted at rest and never exposed in API responses
- Topic browsing supports pagination and filtering by time range and message key

**Part of Epic: AsyncAPI & Event-Driven Architecture**

---

#### 3.4 (#1471) — Channel Testing & Message Simulation

Channel Testing & Message Simulation provides tools for publishing test messages to channels, subscribing to live message streams, and validating event payloads against AsyncAPI schemas. This testing environment enables developers to verify event-driven integrations without deploying consumer services.

The testing page at `/app/protocols/asyncapi/[schemaId]/test` presents a split-pane interface. The left pane is the publisher: select a channel, choose a message type, and compose the payload in a Monaco Editor with schema-aware autocomplete. Protocol-specific fields (Kafka partition key, AMQP routing key, MQTT retain flag) are configurable via form inputs below the editor. The right pane is the subscriber: select channels to listen on, and messages appear in a chronological timeline as they arrive.

Message simulation generates realistic test data from the AsyncAPI message schema. The simulator uses schema constraints (types, formats, enums, ranges, patterns) to produce valid sample messages. A "Fuzz" mode generates edge-case messages (empty strings, max-length values, boundary numbers, null optionals) to test consumer resilience. Simulated messages can be published individually or as a configurable-rate stream.

The REST API provides `POST /api/v1/protocols/asyncapi/schemas/{id}/test/publish` (publish test message), `POST /api/v1/protocols/asyncapi/schemas/{id}/test/simulate` (generate simulated messages), and `GET /api/v1/protocols/asyncapi/schemas/{id}/test/subscribe/{channel}` (SSE stream of received messages). Test messages are tagged with an `x-test: true` header so consumers can filter them from production traffic.

**Acceptance Criteria**

- Publisher panel sends messages to configured broker channels with protocol-specific options
- Subscriber panel displays incoming messages in a chronological timeline with deserialized payloads
- Message simulation generates valid sample data from schema constraints
- Fuzz mode produces edge-case messages testing boundary conditions and optional field handling
- Test messages include an `x-test: true` header for production traffic filtering
- Monaco Editor provides schema-aware autocomplete for message payload composition
- Simulated message streams support configurable publish rates for load testing

**Part of Epic: AsyncAPI & Event-Driven Architecture**

---

## Epic 4: Protocol Conversion & Cross-Protocol Gateway

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 4.1 (#1483) | Schema Translation Engine | Bidirectional conversion between OpenAPI, GraphQL, AsyncAPI, and Protobuf | `enhancement`, `mvp`, `multi-protocol`, `rest`, `ai-generated` | Yes |
| 4.2 (#1488) | Cross-Protocol Gateway Core | Route and translate between REST, GraphQL, and gRPC with Envoy | `enhancement`, `mvp`, `multi-protocol`, `rest`, `ai-generated` | Yes |
| 4.3 (#1490) | Protocol Negotiation & Unified Authentication | Content negotiation and single auth layer across all protocols | `enhancement`, `multi-protocol`, `rest`, `ai-generated` | No |
| 4.4 (#1492) | Conversion Testing & Validation UI | Visual tools for testing schema translations and gateway routing | `enhancement`, `multi-protocol`, `ai-generated` | No |

### Detailed Issue Descriptions

---

#### 4.1 (#1483) — Schema Translation Engine

The Schema Translation Engine provides bidirectional conversion between OpenAPI 3.1, GraphQL SDL, AsyncAPI 3.0, and Protocol Buffer definitions. Rather than maintaining parallel schemas for each protocol, developers define their API once and generate compatible schemas for other protocols automatically. The engine handles structural mapping, type system differences, and protocol-specific annotations.

```
              Schema Translation Matrix

     FROM ╲ TO │  OpenAPI  │  GraphQL  │  AsyncAPI  │  Protobuf
    ───────────┼──────────┼──────────┼───────────┼──────────
     OpenAPI   │    —     │    ✓     │     ✓     │    ✓
     GraphQL   │    ✓     │    —     │     ✓     │    ✓
     AsyncAPI  │    ✓     │    ✓     │     —     │    ✓
     Protobuf  │    ✓     │    ✓     │     ✓     │    —
     WSDL      │    ✓     │    —     │     —     │    —
     RAML      │    ✓     │    —     │     —     │    —
```

The translation page at `/app/protocols/translate` presents a side-by-side view: source schema on the left, target schema on the right, with conversion controls in the center. Developers select the source format and target format from Radix `Select` dropdowns, upload or select an existing schema, and click "Translate." The engine produces the target schema with a translation report listing any lossy conversions, unsupported features, or manual decisions required.

Type mapping follows deterministic rules: OpenAPI `string` → GraphQL `String` → proto `string`; OpenAPI `integer` (int32) → GraphQL `Int` → proto `int32`; OpenAPI `array` → GraphQL list type → proto `repeated`. Lossy conversions (e.g., GraphQL union types have no direct OpenAPI equivalent) produce a warning and a best-effort approximation with `oneOf`. Legacy format support includes WSDL → OpenAPI and RAML → OpenAPI for migration paths.

The REST API provides `POST /api/v1/protocols/translate` (translate with source format, target format, and schema body), `GET /api/v1/protocols/translate/{jobId}` (retrieve result with translation report), and `POST /api/v1/protocols/translate/preview` (dry-run showing only warnings without full conversion). Translation results are cached by schema hash to avoid redundant computation.

**Acceptance Criteria**

- Bidirectional translation works between OpenAPI, GraphQL, AsyncAPI, and Protobuf
- Type mappings follow deterministic rules documented in the translation report
- Lossy conversions produce warnings with the approximation used and manual alternatives
- WSDL → OpenAPI and RAML → OpenAPI legacy translations produce valid OpenAPI 3.1 output
- Side-by-side view highlights corresponding elements between source and target schemas
- Translation results are cached by schema content hash to avoid redundant work
- Translation report includes a completeness percentage and lists all unsupported features

**Part of Epic: Protocol Conversion & Cross-Protocol Gateway**

---

#### 4.2 (#1488) — Cross-Protocol Gateway Core

The Cross-Protocol Gateway enables consumers to call APIs using their preferred protocol regardless of the backend's native protocol. A REST client can query a GraphQL backend, a gRPC client can hit a REST service, and a GraphQL query can fan out to both REST and gRPC upstreams. The gateway uses Envoy as the proxy layer with custom filter chains for protocol translation.

```
                     Cross-Protocol Gateway

  REST Client ──────▶┌─────────────────────────┐──────▶ GraphQL Backend
                     │                         │
  GraphQL Client ──▶│    Envoy Proxy Layer     │──────▶ REST Backend
                     │                         │
  gRPC Client ─────▶│  ┌───────────────────┐  │──────▶ gRPC Backend
                     │  │ Protocol Filters  │  │
                     │  │ • REST ↔ GraphQL  │  │
                     │  │ • REST ↔ gRPC     │  │
                     │  │ • GraphQL ↔ gRPC  │  │
                     │  └───────────────────┘  │
                     │                         │
                     │  ┌───────────────────┐  │
                     │  │ Schema Registry   │  │
                     │  │ (translation maps)│  │
                     │  └───────────────────┘  │
                     └─────────────────────────┘
```

The gateway configuration page at `/app/protocols/gateway/routes` displays protocol routing rules in a Radix `Table` with columns for consumer protocol, path/operation, upstream protocol, upstream URL, and status. Adding a route opens a Radix `Dialog` specifying the consumer-facing protocol and path, the upstream protocol and endpoint, and the schema mapping (which translation from 4.1 to apply).

REST-to-GraphQL translation maps REST path parameters and query strings to GraphQL query arguments, translates the REST response from the GraphQL JSON response, and handles pagination (REST offset/limit to GraphQL cursor-based). REST-to-gRPC translation maps HTTP methods to RPC names, JSON bodies to protobuf messages, and HTTP status codes to gRPC status codes. GraphQL-to-gRPC translation maps GraphQL resolvers to gRPC method calls with field-level resolution.

The REST API provides `POST /api/v1/protocols/gateway/routes` (create route), `GET /api/v1/protocols/gateway/routes` (list), `PUT /api/v1/protocols/gateway/routes/{id}` (update), and `GET /api/v1/protocols/gateway/routes/{id}/health` (check upstream connectivity). Envoy configuration is generated from the route definitions and hot-reloaded via Envoy's xDS API without gateway restart.

**Acceptance Criteria**

- REST-to-GraphQL routing translates path/query params to GraphQL arguments and returns flattened JSON
- REST-to-gRPC routing maps HTTP methods to RPC calls with JSON-to-protobuf body translation
- GraphQL-to-gRPC routing resolves GraphQL fields via gRPC method calls with batching
- Envoy configuration is generated from route definitions and applied via xDS hot-reload
- Route health checks verify upstream connectivity and report protocol-specific errors
- Gateway handles protocol-specific error translation (gRPC status codes ↔ HTTP status codes ↔ GraphQL errors)
- Routing rules support path-based and header-based matching for consumer request classification

**Part of Epic: Protocol Conversion & Cross-Protocol Gateway**

---

#### 4.3 (#1490) — Protocol Negotiation & Unified Authentication

Protocol Negotiation enables the gateway to automatically detect the consumer's intended protocol from request characteristics and route accordingly. Unified Authentication provides a single authentication layer that works across REST, GraphQL, and gRPC, translating credentials and identity tokens between protocol-specific formats.

Protocol detection uses a priority-based chain: explicit `X-Protocol` header (highest priority), content-type analysis (`application/grpc` for gRPC, `application/graphql` for GraphQL), path pattern matching (`/graphql` endpoint, gRPC service paths), and fallback to REST. The detection result determines which protocol filter chain processes the request.

Unified authentication accepts credentials in any protocol-native format: HTTP `Authorization` header (Bearer token, Basic auth) for REST, the same header or `variables.token` field for GraphQL, and gRPC metadata `authorization` key for gRPC. All formats are normalized to a common identity claim set, validated against the auth provider (JWT verification, OAuth introspection), and the authenticated identity is propagated to upstreams in their expected format.

The authentication configuration page at `/app/protocols/gateway/auth` uses Radix `Tabs` for switching between auth providers (JWT, OAuth2, API Key), `Select` for token extraction locations, and `Switch` for enabling/disabling per-protocol auth passthrough. The REST API exposes `PUT /api/v1/protocols/gateway/auth` (configure auth), `GET /api/v1/protocols/gateway/auth/providers` (list configured providers), and `POST /api/v1/protocols/gateway/auth/test` (validate a token against configured providers).

**Acceptance Criteria**

- Protocol detection correctly identifies REST, GraphQL, and gRPC from request characteristics
- `X-Protocol` header overrides automatic detection for explicit protocol selection
- JWT tokens are accepted and validated regardless of arrival via HTTP header, GraphQL variable, or gRPC metadata
- Authenticated identity is propagated to upstreams in their protocol-native format
- Auth configuration supports JWT verification, OAuth2 introspection, and API key validation
- Failed authentication returns protocol-appropriate errors (HTTP 401, GraphQL error, gRPC UNAUTHENTICATED)
- Auth provider configuration is hot-reloadable without gateway restart

**Part of Epic: Protocol Conversion & Cross-Protocol Gateway**

---

#### 4.4 (#1492) — Conversion Testing & Validation UI

The Conversion Testing & Validation UI provides an integrated environment for testing schema translations, validating gateway routing, and debugging protocol conversions end-to-end. Developers compose a request in one protocol format, route it through the gateway, and inspect the translated request that reaches the upstream—all within a single page.

The testing page at `/app/protocols/gateway/test` uses a three-panel layout. The left panel is the consumer request composer: select a protocol (REST, GraphQL, gRPC), compose the request using protocol-specific editors (form builder for REST, Monaco with GraphQL autocomplete, proto message form for gRPC). The center panel shows the gateway processing pipeline: protocol detection result, authentication validation, schema translation steps, and the translated upstream request. The right panel displays the upstream response and the reverse-translated consumer response.

A diff view highlights the structural changes made during translation: fields renamed, types coerced, pagination arguments transformed, and error formats converted. Validation mode runs the request through the full pipeline without sending to the upstream, checking schema compatibility at each translation step. A validation report lists incompatible types, missing required fields in the target format, lossy conversions, and authentication format warnings.

The REST API exposes `POST /api/v1/protocols/gateway/test/execute` (full end-to-end test), `POST /api/v1/protocols/gateway/test/validate` (dry-run validation), and `GET /api/v1/protocols/gateway/test/history` (recent test executions).

**Acceptance Criteria**

- Consumer request can be composed in REST, GraphQL, or gRPC format with protocol-specific editors
- Gateway processing pipeline is visualized step-by-step showing each translation phase
- Diff view highlights structural changes between consumer request and translated upstream request
- Validation mode checks schema compatibility without sending to upstream
- Validation report lists incompatible types, missing fields, and lossy conversions
- Test execution history is stored and reviewable for debugging regression
- End-to-end test shows the full round-trip: consumer request → translated upstream request → upstream response → translated consumer response

**Part of Epic: Protocol Conversion & Cross-Protocol Gateway**

---

## Parallel Work Guide

**Epic 1 — GraphQL Schema Design & Tooling:**
Issues 1.1 (Schema Editor) and 1.2 (Operation Builder) can be developed in parallel as they operate on independent UI pages with shared schema data. Issue 1.3 (Playground & Performance) depends on 1.1 for schema definitions to power autocomplete and profiling. Issue 1.4 (Federation) depends on 1.1 for the core schema editor to extend with federation directives.

**Epic 2 — gRPC & Protocol Buffer Support:**
Issues 2.1 (Message Designer) and 2.2 (Service Editor) can be developed in parallel—messages and services are independent proto constructs with a shared type system. Issue 2.3 (Proto Generation) depends on both 2.1 and 2.2 for complete proto definitions. Issue 2.4 (Testing & Breaking Changes) depends on 2.1 for message definitions and 2.2 for service definitions.

**Epic 3 — AsyncAPI & Event-Driven Architecture:**
Issues 3.1 (Visual Editor) and 3.2 (Pattern Designer) can be developed in parallel. The pattern designer references channels from 3.1 but can be stubbed initially. Issue 3.3 (Streaming Integration) depends on 3.1 for channel definitions to validate against. Issue 3.4 (Channel Testing) depends on 3.1 for message schemas and 3.3 for broker connections.

**Epic 4 — Protocol Conversion & Cross-Protocol Gateway:**
Issues 4.1 (Translation Engine) and 4.2 (Gateway Core) can be developed in parallel—the translation engine produces schema mappings and the gateway consumes them, but both can be built against interface contracts. Issue 4.3 (Negotiation & Auth) depends on 4.2 for the gateway routing infrastructure. Issue 4.4 (Testing UI) depends on all prior issues in this epic for full pipeline visualization.

**Cross-Epic Parallelism:** Epics 1, 2, and 3 are fully independent and can be developed by separate teams—each covers a distinct protocol. Epic 4 depends on schemas from all three preceding epics for translation and gateway routing, but the translation engine (4.1) and gateway core (4.2) can begin development using mock schemas while protocol-specific editors are being built. Within those constraints, all UI work across Epics 1–3 can proceed in parallel.
