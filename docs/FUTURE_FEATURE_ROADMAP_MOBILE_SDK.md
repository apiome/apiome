# Objectified: Mobile SDK - Feature Roadmap

> Native mobile SDKs that provide type-safe API clients generated directly from Objectified schemas—giving mobile teams production-ready networking, serialization, authentication, and offline caching without writing boilerplate.
>
> **Revenue Model**: Per-SDK generation, enterprise SDK customization
>
> **Tech Stack**: NextJS (app router), Radix UI, PostgreSQL, Handlebars (code generation templates), OpenAPI 3.1, Swift (iOS), Kotlin (Android), TypeScript (React Native), Dart (Flutter), C# (Xamarin)
>
> **Last Updated**: April 2, 2026

---

## MVP Definition

- Code generation engine that converts Objectified schemas to type-safe models in Swift, Kotlin, and TypeScript
- iOS SDK template with Swift models, URLSession networking, Codable serialization, and error handling
- Android SDK template with Kotlin data classes, Retrofit networking, and kotlinx.serialization
- Authentication handling for OAuth 2.0, JWT, and API key authentication patterns
- Offline caching with local persistence and background sync on connectivity restore
- One-click SDK generation from the Objectified web UI with downloadable ZIP output
- Automatic SDK regeneration when schemas are updated with diff-based changelog
- SDK versioning aligned with schema versions using semver

---

## Epic 1: Code Generation Engine

### Summary Table

| #   | Title                                | Description                                                                  | Labels                                   | Parallel |
|-----|--------------------------------------|------------------------------------------------------------------------------|------------------------------------------|----------|
| 1.1 (#1127) | Schema-to-AST Parser                 | Parse Objectified schemas into a language-agnostic abstract syntax tree      | `enhancement`, `mvp`, `mobile-sdk`       | Yes      |
| 1.2 (#1128) | Template System & Handlebars Engine  | Pluggable template engine for rendering AST nodes into language-specific code | `enhancement`, `mvp`, `mobile-sdk`       | Yes      |
| 1.3 (#1129) | Multi-Language Output Pipeline       | Pipeline that routes AST through language-specific templates and formatters  | `enhancement`, `mvp`, `mobile-sdk`, `rest` | No    |
| 1.4 (#1130) | Type Mapping Registry                | Configurable mapping from JSON Schema types to native language types          | `enhancement`, `mvp`, `mobile-sdk`       | Yes      |
| 1.5 (#1131) | Generation API & Job Queue           | REST API for triggering SDK generation with async job processing             | `enhancement`, `mvp`, `mobile-sdk`, `rest` | No    |

### Detailed Issue Descriptions

---

#### 1.1 (#1127) — Schema-to-AST Parser

The code generation engine needs a language-agnostic intermediate representation. This issue builds the parser that converts Objectified JSON Schema definitions into an Abstract Syntax Tree (AST) that captures all the information needed for code generation without being tied to any specific output language.

The AST represents schema structures as typed nodes: `ClassNode` (name, properties, relationships, description), `PropertyNode` (name, type, nullable, constraints, description, default), `EnumNode` (name, values, descriptions), `RelationshipNode` (type: one-to-one | one-to-many | many-to-many, target class, cascade behavior). The parser resolves `$ref` pointers within the schema, flattens `allOf`/`anyOf`/`oneOf` compositions into concrete types, and normalizes naming conventions (the AST stores names in a canonical form; language-specific casing is applied at template time).

```
JSON Schema Input                    AST Output
┌──────────────────┐                 ┌──────────────────────┐
│ {                │                 │ ClassNode            │
│   "type":"object"│  ──────────▶   │   name: "Order"      │
│   "properties":{ │                 │   properties: [      │
│     "id": {...}, │                 │     PropertyNode {   │
│     "total":{...}│                 │       name: "id"     │
│   },             │                 │       type: UUID     │
│   "required":[   │                 │       nullable: false│
│     "id","total" │                 │     },               │
│   ]              │                 │     PropertyNode {   │
│ }                │                 │       name: "total"  │
│                  │                 │       type: Decimal  │
│                  │                 │       nullable: false│
│                  │                 │       minimum: 0     │
│                  │                 │     }                │
│                  │                 │   ]                  │
└──────────────────┘                 └──────────────────────┘
```

The parser handles edge cases: circular `$ref` (detected and broken with forward declarations), deeply nested objects (flattened into separate classes with relationship links), and polymorphic types (`oneOf` → protocol/interface with concrete implementations). Validation errors in the input schema produce structured error reports rather than silent incorrect output.

**Acceptance Criteria**

- All JSON Schema primitive types (string, integer, number, boolean, array, object) parse to AST type nodes
- `$ref` pointers are resolved and produce `RelationshipNode` connections between classes
- `allOf` composition is flattened into a single class with merged properties
- `oneOf`/`anyOf` produce protocol/interface AST nodes with concrete variant classes
- Circular references are detected and handled with forward declaration markers
- Validation errors produce structured reports with JSON Pointer paths to the issue

**Part of Epic: Code Generation Engine**

---

#### 1.2 (#1128) — Template System & Handlebars Engine

The AST captures what to generate; templates capture how. This issue builds the Handlebars-based template engine that renders AST nodes into language-specific source code files, with custom helpers for common code generation patterns.

Each target language has a template bundle containing: `model.hbs` (class/struct definition), `enum.hbs` (enumeration definition), `serializer.hbs` (JSON serialization/deserialization), `api-client.hbs` (networking client), `auth.hbs` (authentication handler), and `index.hbs` (barrel file/module definition). Templates are stored in the template registry (managed via the REST API) and loaded at generation time.

Custom Handlebars helpers provide code generation utilities: `{{pascalCase name}}` for class names, `{{camelCase name}}` for properties, `{{snakeCase name}}` for Python/Ruby, `{{typeMap type language}}` for native type lookup, `{{indent level content}}` for consistent indentation, `{{pluralize name}}` for collection names, and `{{docComment description language}}` for language-specific documentation comment syntax.

The template engine supports conditional blocks for optional features: `{{#if auth}}` includes authentication code, `{{#if offline}}` includes caching code, `{{#if pagination}}` includes pagination helpers. These feature flags are passed as generation options.

**Acceptance Criteria**

- Handlebars templates render AST nodes into syntactically correct source code for each target language
- Custom helpers (`pascalCase`, `camelCase`, `snakeCase`, `typeMap`, `pluralize`) work correctly
- Feature flags (`auth`, `offline`, `pagination`) conditionally include/exclude template sections
- Templates are loadable from the template registry and overridable per tenant
- Template rendering errors produce meaningful messages with template name and line number
- Generated output preserves consistent indentation and formatting per language conventions

**Part of Epic: Code Generation Engine**

---

#### 1.3 (#1129) — Multi-Language Output Pipeline

Individual templates generate individual files; the pipeline orchestrates the full SDK generation by routing AST nodes through the correct templates, assembling the output directory structure, and applying language-specific formatters.

The pipeline runs in stages: (1) **Parse** — convert schema to AST (issue 1.1), (2) **Map** — apply type mappings for the target language (issue 1.4), (3) **Render** — process each AST node through its template to produce source files, (4) **Format** — run language-specific formatters (SwiftFormat for Swift, ktlint for Kotlin, Prettier for TypeScript, dart format for Dart), (5) **Package** — assemble the output directory with the correct project structure (Package.swift for iOS, build.gradle for Android, package.json for React Native, pubspec.yaml for Flutter).

The output directory structure for each platform follows conventions:

```
iOS SDK Output                    Android SDK Output
├── Package.swift                 ├── build.gradle.kts
├── Sources/                      ├── src/main/kotlin/
│   ├── Models/                   │   ├── models/
│   │   ├── Order.swift           │   │   ├── Order.kt
│   │   └── Customer.swift        │   │   └── Customer.kt
│   ├── API/                      │   ├── api/
│   │   └── ObjectifiedClient.swift│   │   └── ObjectifiedClient.kt
│   └── Auth/                     │   └── auth/
│       └── AuthManager.swift     │       └── AuthManager.kt
└── Tests/                        └── src/test/kotlin/
    └── ModelsTests.swift             └── ModelsTest.kt
```

The pipeline is exposed as a library that the generation API (1.5) and the CLI invoke. It accepts: schema ID, target language, feature flags, and custom template overrides. Output is a directory tree that can be zipped or written to a Git repository.

**Acceptance Criteria**

- The pipeline produces compilable SDK projects for Swift, Kotlin, TypeScript, Dart, and C#
- Language-specific formatters are applied to all generated code (SwiftFormat, ktlint, Prettier, etc.)
- Output directory structure follows each platform's conventions (Package.swift, build.gradle, etc.)
- Project metadata files (package.json, pubspec.yaml, etc.) are generated with correct dependencies
- The pipeline is invocable as a library with schema ID, language, and feature flags
- Generated test files include basic model serialization round-trip tests

**Part of Epic: Code Generation Engine**

---

#### 1.4 (#1130) — Type Mapping Registry

JSON Schema types do not map one-to-one to native types. `string` with `format: date-time` is `Date` in Swift, `Instant` in Kotlin, and `DateTime` in Dart. This issue builds the configurable type mapping registry that controls these translations.

The registry stores mappings as a matrix: (JSON Schema type × format × constraints) → native type. Default mappings are provided for all supported languages:

| JSON Schema | Swift | Kotlin | TypeScript | Dart | C# |
|---|---|---|---|---|---|
| `string` | `String` | `String` | `string` | `String` | `string` |
| `string` + `format: uuid` | `UUID` | `UUID` | `string` | `String` | `Guid` |
| `string` + `format: date-time` | `Date` | `Instant` | `Date` | `DateTime` | `DateTimeOffset` |
| `string` + `format: uri` | `URL` | `URI` | `string` | `Uri` | `Uri` |
| `integer` | `Int` | `Int` | `number` | `int` | `int` |
| `integer` + `format: int64` | `Int64` | `Long` | `number` | `int` | `long` |
| `number` | `Double` | `Double` | `number` | `double` | `double` |
| `number` + `format: decimal` | `Decimal` | `BigDecimal` | `string` | `Decimal` | `decimal` |
| `boolean` | `Bool` | `Boolean` | `boolean` | `bool` | `bool` |
| `array` | `[T]` | `List<T>` | `T[]` | `List<T>` | `List<T>` |
| `object` (untyped) | `[String: Any]` | `Map<String, Any>` | `Record<string, unknown>` | `Map<String, dynamic>` | `Dictionary<string, object>` |

Mappings are overridable per tenant via `PUT /api/v1/mobile-sdk/type-mappings/{tenantId}`. The mapping UI is a NextJS page at `/mobile-sdk/type-mappings` using Radix `Table` for the mapping matrix, `Dialog` for editing individual mappings, and `Select` for language selection.

**Acceptance Criteria**

- Default type mappings are provided for Swift, Kotlin, TypeScript, Dart, and C#
- `format` specifiers (uuid, date-time, uri, int64, decimal) map to appropriate native types
- Array and object types produce correct generic/parameterized type syntax per language
- Nullable types use language-appropriate optional syntax (`?` in Swift/Kotlin/Dart/C#, `| null` in TS)
- Tenant-specific mapping overrides are supported via REST API
- The type mapping UI displays the full matrix with per-cell editing

**Part of Epic: Code Generation Engine**

---

#### 1.5 (#1131) — Generation API & Job Queue

SDK generation for large schemas can take 30+ seconds with formatting and packaging. This issue builds the REST API that accepts generation requests and processes them asynchronously via a job queue, providing progress updates and downloadable output.

The generation endpoint `POST /api/v1/mobile-sdk/generate` accepts: `schemaId`, `language` (swift | kotlin | typescript | dart | csharp), `features` (auth: boolean, offline: boolean, pagination: boolean), and `templateOverrides` (optional tenant-specific template IDs). It returns a `jobId` immediately.

The job queue (backed by Redis + BullMQ) processes generation requests sequentially per tenant to prevent resource contention. Job status is queryable via `GET /api/v1/mobile-sdk/jobs/{jobId}` returning: `status` (queued | processing | completed | failed), `progress` (0–100), `stage` (parsing | mapping | rendering | formatting | packaging), and `output_url` (presigned S3 URL for the ZIP download, available when completed).

A WebSocket endpoint `wss://api.objectified.dev/mobile-sdk/jobs/{jobId}/progress` streams real-time progress updates to the UI. The generation page at `/mobile-sdk/generate` shows a progress bar (Radix `Progress`) with stage indicators and auto-downloads the ZIP on completion.

**Acceptance Criteria**

- `POST /api/v1/mobile-sdk/generate` accepts parameters and returns a `jobId` immediately
- Job status endpoint reports stage-level progress (parsing, mapping, rendering, formatting, packaging)
- Completed jobs provide a presigned S3 URL for ZIP download (valid for 24 hours)
- Failed jobs include error details with the failing stage and error message
- WebSocket progress streaming updates the UI in real-time during generation
- Concurrent generation requests from the same tenant are queued (not rejected)

**Part of Epic: Code Generation Engine**

---

## Epic 2: iOS & Android SDK Templates

### Summary Table

| #   | Title                              | Description                                                                  | Labels                                   | Parallel |
|-----|------------------------------------|------------------------------------------------------------------------------|------------------------------------------|----------|
| 2.1 (#1133) | Swift Model Generation             | Generate Swift structs with Codable, Equatable, and Hashable conformance     | `enhancement`, `mvp`, `mobile-sdk`       | Yes      |
| 2.2 (#1134) | iOS Networking & API Client        | URLSession-based API client with async/await, error handling, and interceptors| `enhancement`, `mvp`, `mobile-sdk`       | Yes      |
| 2.3 (#1135) | Kotlin Data Class Generation       | Generate Kotlin data classes with kotlinx.serialization annotations          | `enhancement`, `mvp`, `mobile-sdk`       | Yes      |
| 2.4 (#1136) | Android Networking & API Client    | Retrofit/OkHttp-based API client with coroutines and interceptors            | `enhancement`, `mvp`, `mobile-sdk`       | Yes      |
| 2.5 (#1137) | Auth & Offline Caching (Shared)    | Cross-platform auth handling and offline persistence with sync               | `enhancement`, `mvp`, `mobile-sdk`       | No       |

### Detailed Issue Descriptions

---

#### 2.1 (#1133) — Swift Model Generation

iOS developers expect models that feel native to Swift's type system. This issue builds the Swift template that generates structs with full `Codable` support, proper optionality, and Swift naming conventions.

Each schema class generates a Swift `struct` conforming to `Codable`, `Equatable`, `Hashable`, and `Sendable`. Properties use Swift-idiomatic types (`UUID`, `Date`, `URL`, `Decimal`) based on the type mapping registry. Optional fields are declared as `T?`. Enum properties generate a nested `enum` conforming to `String` and `Codable` with all declared values.

The `CodingKeys` enum maps between the schema's property names (often snake_case or camelCase) and Swift-idiomatic property names. Custom `init(from:)` and `encode(to:)` implementations handle edge cases: date format parsing (ISO 8601 with fractional seconds), polymorphic types (`oneOf` → protocol with concrete struct decoders), and default values for optional fields.

Generated models include documentation comments derived from schema property descriptions. Relationship properties generate lazy-loaded references that use the API client to fetch related objects on access. The models are organized in a Swift Package (Package.swift) with separate targets for models, networking, and auth.

**Acceptance Criteria**

- Generated structs conform to `Codable`, `Equatable`, `Hashable`, and `Sendable`
- Optional schema fields generate `T?` properties with correct `CodingKeys` mapping
- Enum properties generate nested `enum` types with `String` raw values
- ISO 8601 date parsing handles fractional seconds and timezone offsets
- Polymorphic types (`oneOf`) generate protocol + concrete struct decoders
- Generated Swift Package compiles without errors in Xcode 16+

**Part of Epic: iOS & Android SDK Templates**

---

#### 2.2 (#1134) — iOS Networking & API Client

Models are useless without a way to call the API. This issue generates the iOS networking client using URLSession with Swift concurrency (async/await), providing type-safe methods for every CRUD operation.

The generated `ObjectifiedClient` class exposes methods matching the schema's endpoints: `func getOrders() async throws -> [Order]`, `func getOrder(id: UUID) async throws -> Order`, `func createOrder(_ order: Order) async throws -> Order`, etc. Each method constructs the URL, serializes the request body, sends the request via URLSession, deserializes the response, and returns the typed result. Errors are decoded into a typed `APIError` enum with cases for validation errors (422), authentication failures (401), not found (404), and server errors (5xx).

The client supports request/response interceptors for cross-cutting concerns: authentication header injection, request logging, retry logic, and analytics. Interceptors conform to a `RequestInterceptor` protocol and are registered during client initialization.

Configuration includes: base URL, timeout interval, custom headers, and certificate pinning for security-sensitive applications. The client is thread-safe and designed for use with Swift's structured concurrency.

**Acceptance Criteria**

- Type-safe methods are generated for list, get, create, update, and delete operations per schema class
- async/await API uses URLSession under the hood with configurable timeout
- `APIError` enum covers 401, 403, 404, 422 (with field-level errors), and 5xx cases
- Request interceptors support authentication injection, logging, and retry
- Certificate pinning is configurable for security-sensitive deployments
- Generated client compiles and runs on iOS 16+ / macOS 13+

**Part of Epic: iOS & Android SDK Templates**

---

#### 2.3 (#1135) — Kotlin Data Class Generation

Android developers expect Kotlin-idiomatic data classes with serialization support. This issue generates Kotlin data classes with kotlinx.serialization annotations, proper nullability, and Kotlin naming conventions.

Each schema class generates a Kotlin `data class` annotated with `@Serializable`. Properties use Kotlin-idiomatic types (`UUID`, `Instant`, `BigDecimal`, `URI`) with `kotlinx.serialization` custom serializers for non-primitive types. Nullable fields are declared as `T?` with `@Required` annotation on non-nullable fields. Enum properties generate a Kotlin `enum class` with `@Serializable` annotation.

The `@SerialName` annotation maps between schema property names and Kotlin-idiomatic property names (camelCase). Default values are generated from the schema's `default` keyword. Validation annotations from the schema's constraints are included as `@field:` annotations using Jakarta Validation (Bean Validation 3.0): `@field:Size(min=, max=)`, `@field:Pattern(regexp=)`, `@field:Min`, `@field:Max`.

Generated classes are organized in a Kotlin library module with `build.gradle.kts` configured with kotlinx.serialization plugin, proper dependencies, and a minimum SDK version of 26.

**Acceptance Criteria**

- Generated data classes have `@Serializable` annotation with correct `@SerialName` mappings
- Nullable schema fields produce `T?` properties; required fields use non-null types
- Enum properties generate `enum class` with `@Serializable` and correct values
- JSON Schema constraints map to Jakarta Validation annotations (`@Size`, `@Pattern`, `@Min`)
- Custom serializers handle `Instant`, `UUID`, `BigDecimal`, and `URI` types
- Generated Kotlin module compiles with Gradle without errors on API level 26+

**Part of Epic: iOS & Android SDK Templates**

---

#### 2.4 (#1136) — Android Networking & API Client

This issue generates the Android networking client using Retrofit and OkHttp with Kotlin coroutines, providing type-safe API methods with proper error handling.

The generated SDK produces a Retrofit `interface` with annotated methods: `@GET("orders") suspend fun getOrders(): List<Order>`, `@POST("orders") suspend fun createOrder(@Body order: Order): Order`, etc. A companion `ObjectifiedClient` class configures the Retrofit instance with: OkHttp client, kotlinx.serialization converter factory, base URL, and interceptors.

OkHttp interceptors handle cross-cutting concerns: `AuthInterceptor` injects authentication tokens, `LoggingInterceptor` logs requests and responses, `RetryInterceptor` retries failed requests with exponential backoff. The generated `ApiException` sealed class covers: `ValidationError` (422 with field-level errors), `AuthenticationError` (401), `NotFoundError` (404), `ServerError` (5xx), and `NetworkError` (connectivity failures).

The client is designed for Android's lifecycle: requests are scoped to coroutine contexts, cancellation is automatic when the scope is cancelled, and the OkHttp connection pool is shared. Configuration supports custom certificate authorities and proxy settings for enterprise environments.

**Acceptance Criteria**

- Retrofit interface methods are generated for all CRUD operations per schema class
- Kotlin coroutines (`suspend fun`) are used for all API calls
- `ApiException` sealed class covers 401, 404, 422, 5xx, and network errors
- OkHttp interceptors support auth injection, logging, and retry with backoff
- Request cancellation is automatic when the coroutine scope is cancelled
- Generated Android library compiles with Gradle and runs on API level 26+

**Part of Epic: iOS & Android SDK Templates**

---

#### 2.5 (#1137) — Auth & Offline Caching (Shared)

Authentication and offline caching are needed on both iOS and Android. This issue builds shared logic (generated in both Swift and Kotlin) for auth token management and local data persistence with background sync.

**Authentication**: The generated `AuthManager` supports three auth modes: (1) **API Key** — stored securely in the platform keychain (iOS Keychain / Android EncryptedSharedPreferences) and injected as a header, (2) **OAuth 2.0** — authorization code flow with PKCE, token storage, automatic refresh, and logout, (3) **JWT** — bearer token management with expiration checking and refresh. The auth mode is configured at SDK initialization. The auth manager conforms to the networking interceptor protocol so it injects credentials automatically.

**Offline Caching**: The generated `CacheManager` persists API responses to local storage (Core Data on iOS, Room on Android). Each cached response is keyed by (endpoint + parameters) and stored with a TTL. When the device is offline (detected via network reachability monitoring), GET requests are served from cache. POST/PUT/DELETE requests are queued in an offline queue and replayed when connectivity returns, with conflict detection based on the server's `ETag` or `Last-Modified` headers.

```
┌──────────┐     ┌──────────────┐     ┌──────────────┐
│  App UI  │────▶│  API Client  │────▶│  Server      │
│          │     │              │     │              │
│          │     │  ┌─────────┐ │     └──────────────┘
│          │     │  │ Auth    │ │           ▲
│          │     │  │ Manager │ │           │ online
│          │     │  └─────────┘ │           │
│          │     │  ┌─────────┐ │     ┌──────────────┐
│          │◀────│  │ Cache   │◀┼─────│  Local DB    │
│          │     │  │ Manager │ │     │  (offline)   │
│          │     │  └─────────┘ │     └──────────────┘
└──────────┘     └──────────────┘
```

**Acceptance Criteria**

- API Key auth stores keys securely in platform keychain and injects as request header
- OAuth 2.0 PKCE flow completes login, stores tokens, and refreshes automatically
- JWT bearer tokens are refreshed before expiration using the configured refresh endpoint
- GET responses are cached locally with configurable TTL per endpoint
- Offline GET requests return cached data when network is unavailable
- Offline mutations are queued and replayed on reconnect with ETag-based conflict detection

**Part of Epic: iOS & Android SDK Templates**

---

## Epic 3: Cross-Platform SDK Templates

### Summary Table

| #   | Title                              | Description                                                                  | Labels                                   | Parallel |
|-----|------------------------------------|------------------------------------------------------------------------------|------------------------------------------|----------|
| 3.1 (#1139) | React Native SDK Template          | TypeScript models, fetch client, and React hooks for React Native apps       | `enhancement`, `mobile-sdk`              | Yes      |
| 3.2 (#1140) | Flutter SDK Template               | Dart models, Dio client, and Provider/Riverpod integration for Flutter apps  | `enhancement`, `mobile-sdk`              | Yes      |
| 3.3 (#1141) | Xamarin SDK Template               | C# models, HttpClient wrapper, and MVVM support for Xamarin/MAUI apps        | `enhancement`, `mobile-sdk`              | Yes      |
| 3.4 (#1142) | Platform-Specific Adaptations      | Platform detection and conditional features (biometric auth, push, etc.)     | `enhancement`, `mobile-sdk`              | No       |
| 3.5 (#1143) | Cross-Platform Test Harness        | Shared test generation for model serialization and API contract testing      | `enhancement`, `mobile-sdk`              | No       |

### Detailed Issue Descriptions

---

#### 3.1 (#1139) — React Native SDK Template

React Native teams need TypeScript models and React-idiomatic API hooks. This issue generates a React Native SDK with TypeScript models, a fetch-based API client, and custom React hooks for data fetching.

Generated models are TypeScript interfaces with Zod validation schemas for runtime type checking. Each schema class produces: a TypeScript `interface` for the type definition, a Zod `z.object()` schema for validation, and a `parse` function that validates raw API responses. Enum properties generate TypeScript `enum` or `const` object patterns.

The API client uses the standard `fetch` API (available in React Native) wrapped in a typed client class. Custom React hooks are generated for each resource: `useOrders()` returns `{ data, error, loading, refetch }`, `useOrder(id)` returns a single resource, `useCreateOrder()` returns a mutation function. Hooks use React Query (TanStack Query) under the hood for caching, background refetching, and optimistic updates.

The generated package includes: `package.json` with dependencies (Zod, TanStack Query), TypeScript configuration, and an `index.ts` barrel file. Integration with React Navigation is included for deep-linking schema-defined resources.

**Acceptance Criteria**

- TypeScript interfaces match the Objectified schema with correct optional/required typing
- Zod schemas validate API responses at runtime with type-safe error reporting
- React hooks use TanStack Query for caching, loading states, and error handling
- `useCreateOrder()` / `useUpdateOrder()` hooks support optimistic updates
- The generated package includes `package.json`, `tsconfig.json`, and all dependencies
- Generated SDK installs and runs in a React Native 0.73+ project without modification

**Part of Epic: Cross-Platform SDK Templates**

---

#### 3.2 (#1140) — Flutter SDK Template

Flutter developers need Dart models with JSON serialization and Dio-based networking. This issue generates a Flutter SDK package with models, API client, and state management integration.

Generated models are Dart classes with `json_serializable` annotations. Each schema class produces: a `@JsonSerializable()` class with typed fields, a `fromJson` factory constructor, a `toJson` method, and `copyWith` for immutable updates. Nullable fields use Dart's null safety (`String?`). Enum properties generate Dart `enum` types with `@JsonValue` annotations.

The API client uses Dio with interceptors for authentication, logging, and retry. Each resource generates a repository class: `OrderRepository` with methods `getAll()`, `getById()`, `create()`, `update()`, `delete()`. Repositories return `Either<ApiError, T>` (from the dartz package) for explicit error handling without exceptions.

State management integration generates Riverpod providers for each repository: `final orderProvider = FutureProvider.family<Order, String>((ref, id) => ...)`. The generated Flutter package includes: `pubspec.yaml` with dependencies, `analysis_options.yaml`, and an export barrel file.

**Acceptance Criteria**

- Generated Dart classes use `@JsonSerializable` with correct `fromJson`/`toJson` implementations
- Null safety is correctly applied: required fields are non-null, optional fields use `?`
- Dio-based API client includes interceptors for auth, logging, and retry
- Repository classes return `Either<ApiError, T>` for explicit error handling
- Riverpod providers are generated for each repository and resource
- Generated Flutter package passes `flutter analyze` and `dart format` without issues

**Part of Epic: Cross-Platform SDK Templates**

---

#### 3.3 (#1141) — Xamarin SDK Template

Enterprise mobile teams using Xamarin/MAUI need C# models and HttpClient networking. This issue generates a .NET class library with models, API client, and MVVM support.

Generated models are C# `record` types (for value semantics and immutability) with `System.Text.Json` serialization attributes. Each schema class produces: a C# `record` with `[JsonPropertyName]` attributes, a `required` modifier on non-nullable properties, and `init`-only setters. Enum properties generate C# `enum` types with `[JsonStringEnumConverter]`. Validation uses `System.ComponentModel.DataAnnotations`: `[Required]`, `[StringLength]`, `[Range]`, `[RegularExpression]`.

The API client is a typed `HttpClient` wrapper using `IHttpClientFactory` patterns. Each resource generates a service class implementing an interface: `IOrderService` with `GetAllAsync()`, `GetByIdAsync()`, `CreateAsync()`, `UpdateAsync()`, `DeleteAsync()`. Services use `System.Text.Json` for serialization and return `Result<T>` types for error handling.

MVVM support generates `ViewModel` classes for MAUI/Xamarin.Forms with `ObservableProperty` attributes (from CommunityToolkit.Mvvm): `OrderListViewModel` with `ObservableCollection<Order>`, `IsLoading`, `LoadCommand`.

**Acceptance Criteria**

- C# `record` types use `System.Text.Json` attributes with correct property naming
- Data validation annotations (`[Required]`, `[StringLength]`, `[Range]`) map from JSON Schema constraints
- Service interfaces follow `IHttpClientFactory` patterns with `Result<T>` return types
- ViewModel classes use CommunityToolkit.Mvvm with `ObservableProperty` and `RelayCommand`
- Generated .NET class library targets .NET 8+ and compiles without errors
- NuGet package metadata (`*.csproj`) is generated with correct dependencies

**Part of Epic: Cross-Platform SDK Templates**

---

#### 3.4 (#1142) — Platform-Specific Adaptations

Mobile platforms have unique capabilities. This issue adds optional platform-specific features to generated SDKs: biometric authentication, push notification integration, and platform keychain/secure storage access.

Biometric auth wraps the platform's biometric API (Face ID/Touch ID on iOS via LocalAuthentication, BiometricPrompt on Android, react-native-biometrics for React Native) and integrates with the SDK's auth manager. When enabled, the SDK can require biometric verification before sending authenticated API calls—useful for sensitive operations.

Push notification integration generates the boilerplate for registering device tokens with the Objectified backend. When the server sends a push notification (e.g., "schema updated"), the SDK receives it and triggers a cache refresh for the affected resources.

Secure storage uses the platform's keychain (iOS Keychain, Android EncryptedSharedPreferences, Expo SecureStore for React Native, flutter_secure_storage for Flutter) instead of plain-text storage for tokens and sensitive configuration.

Platform adaptations are opt-in via generation flags. The code generator detects the target platform and includes the appropriate implementation.

**Acceptance Criteria**

- Biometric auth integration works on iOS (Face ID/Touch ID) and Android (BiometricPrompt)
- Push notification token registration is generated for iOS (APNs) and Android (FCM)
- Secure storage uses platform-native keychain APIs on all supported platforms
- Platform-specific features are opt-in and excluded when not requested
- Feature availability is detected at runtime with graceful fallback on unsupported devices
- Generated code compiles on the minimum supported platform versions

**Part of Epic: Cross-Platform SDK Templates**

---

#### 3.5 (#1143) — Cross-Platform Test Harness

Generated SDKs should come with tests. This issue generates a cross-platform test harness that validates model serialization round-trips and API contract compliance across all target languages.

For each model, the harness generates: (1) **serialization round-trip tests** — create a model instance, serialize to JSON, deserialize back, and assert equality; (2) **fixture-based tests** — load JSON fixtures (from the schema's examples) and assert they deserialize correctly; (3) **validation tests** — assert that invalid data (violating schema constraints) is rejected by the model's validation logic; (4) **API contract tests** — mock HTTP responses matching the schema's response examples and assert the API client correctly deserializes them.

Test frameworks are language-specific: XCTest for Swift, JUnit 5 for Kotlin, Jest for TypeScript, flutter_test for Dart, xUnit for C#. Mock HTTP layers use platform-specific tools: URLProtocol for iOS, MockWebServer for Android, MSW for React Native, Mockito for Flutter, MockHttp for C#.

Shared JSON fixtures are generated from the schema's `example` and `default` values and stored in a `fixtures/` directory within each SDK. This ensures all platforms test against the same data.

**Acceptance Criteria**

- Serialization round-trip tests pass for all model types on all platforms
- Fixture-based tests load shared JSON fixtures and deserialize correctly
- Validation tests confirm that invalid data is rejected per schema constraints
- API contract tests mock HTTP responses and verify client deserialization
- Each platform uses its native test framework (XCTest, JUnit, Jest, flutter_test, xUnit)
- Shared JSON fixtures are generated from schema examples and included in each SDK

**Part of Epic: Cross-Platform SDK Templates**

---

## Epic 4: SDK Management & Distribution

### Summary Table

| #   | Title                              | Description                                                                  | Labels                                   | Parallel |
|-----|------------------------------------|------------------------------------------------------------------------------|------------------------------------------|----------|
| 4.1 (#1145) | Generation UI & Configuration      | Web interface for configuring and triggering SDK generation                   | `enhancement`, `mvp`, `mobile-sdk`       | Yes      |
| 4.2 (#1146) | Auto-Update & Schema Change Hooks  | Automatic SDK regeneration when source schemas are updated                   | `enhancement`, `mvp`, `mobile-sdk`       | No       |
| 4.3 (#1147) | SDK Versioning & Changelog         | Version generated SDKs aligned with schema versions and produce changelogs   | `enhancement`, `mvp`, `mobile-sdk`       | Yes      |
| 4.4 (#1148) | SDK Portal & Documentation         | Public-facing portal for SDK documentation, downloads, and integration guides| `enhancement`, `mobile-sdk`              | No       |
| 4.5 (#1149) | Enterprise SDK Customization       | Template customization, branding, and internal distribution for enterprises  | `enhancement`, `mobile-sdk`, `rest`      | Yes      |

### Detailed Issue Descriptions

---

#### 4.1 (#1145) — Generation UI & Configuration

Developers should be able to generate SDKs from the Objectified web interface without touching the CLI. This issue builds the generation configuration page where users select a schema, target platform, features, and trigger generation with a single click.

The generation page lives at `/mobile-sdk/generate` in the NextJS app. The workflow is a multi-step form: (1) **Select Schema** — choose from published schema versions using a Radix `Select` dropdown, (2) **Choose Platform** — pick the target language/framework from a card grid (iOS, Android, React Native, Flutter, Xamarin), (3) **Configure Features** — toggle optional features using Radix `Switch` components (authentication mode, offline caching, pagination, biometric auth), (4) **Review & Generate** — summary of selections with a "Generate SDK" button.

After triggering generation, the page transitions to a progress view showing the job's current stage (from issue 1.5) with a Radix `Progress` bar and stage indicators. On completion, the page offers a "Download ZIP" button and a "Push to Git" button (if a Git repository is connected).

```
┌──────────────────────────────────────────────────────┐
│  Generate Mobile SDK                                 │
│                                                      │
│  Step 1: Select Schema                               │
│  ┌──────────────────────────────────┐                │
│  │ Payment System v2.1  ▼          │                │
│  └──────────────────────────────────┘                │
│                                                      │
│  Step 2: Choose Platform                             │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐        │
│  │  iOS   │ │Android │ │React   │ │Flutter │        │
│  │ Swift  │ │Kotlin  │ │Native  │ │ Dart   │        │
│  │   ✓    │ │        │ │        │ │        │        │
│  └────────┘ └────────┘ └────────┘ └────────┘        │
│                                                      │
│  Step 3: Features                                    │
│  Auth: OAuth 2.0 ▼     Offline: [ON]                │
│  Pagination: [ON]      Biometric: [OFF]             │
│                                                      │
│  [Generate SDK]                                      │
└──────────────────────────────────────────────────────┘
```

The page persists the last-used configuration per project so returning users can regenerate with the same settings quickly.

**Acceptance Criteria**

- Multi-step form guides users through schema, platform, and feature selection
- Platform selection uses a card grid with visual icons for each platform
- Feature toggles use Radix `Switch` with clear labels and descriptions
- Generation progress displays with stage indicators and Radix `Progress` bar
- ZIP download is available on completion; Push-to-Git requires a connected repository
- Last-used configuration is persisted per project and pre-filled on return visits

**Part of Epic: SDK Management & Distribution**

---

#### 4.2 (#1146) — Auto-Update & Schema Change Hooks

Schemas change over time, and SDKs must keep up. This issue builds automatic SDK regeneration triggered by schema updates, with notifications to SDK consumers about what changed.

When a schema version is published, a webhook fires to the Mobile SDK service. If auto-update is enabled for any SDK configuration targeting that schema, the service queues a regeneration job with the same settings used for the last generation. The new SDK is stored alongside the previous version.

A diff engine compares the old and new generated SDKs and produces a changelog: new models added, properties added/removed/type-changed, new API methods, and deprecated methods. This changelog is attached to the SDK version and available via `GET /api/v1/mobile-sdk/sdks/{sdkId}/changelog`.

Notification is sent to configured recipients (email and webhook) when an auto-update completes. The notification includes: the schema version that triggered the update, the SDK changelog, a download link for the new SDK, and migration notes for breaking changes (e.g., "Property `Order.total` changed from `Double` to `Decimal`—update all call sites").

**Acceptance Criteria**

- Schema version publish triggers automatic SDK regeneration for configured SDKs
- Auto-update is configurable per SDK (enable/disable) via the generation UI
- The diff engine produces changelogs comparing old and new generated SDKs
- Notifications are sent via email and webhook with changelog and download link
- Breaking changes are highlighted in the notification with migration notes
- Auto-updated SDKs are versioned and stored alongside previous versions

**Part of Epic: SDK Management & Distribution**

---

#### 4.3 (#1147) — SDK Versioning & Changelog

Each generated SDK needs a clear version identity that aligns with the source schema version, enabling consumers to track which SDK version corresponds to which schema. This issue builds the versioning system and automated changelog.

SDK versions follow the pattern: `{schemaVersion}-sdk.{buildNumber}`. For example, schema version `2.1.3` produces SDK `2.1.3-sdk.1`. If the SDK templates are updated without a schema change, the build number increments: `2.1.3-sdk.2`. This pattern lets consumers know at a glance which schema version the SDK targets.

The changelog aggregates: model changes (added/removed/modified classes and properties), API method changes, authentication changes, and dependency updates. It is generated in the platform's conventional format: CHANGELOG.md for all platforms, plus release notes formatted for GitHub Releases (if Git-pushed), CocoaPods (for iOS), Maven Central (for Android), and pub.dev (for Flutter).

Version history is queryable via `GET /api/v1/mobile-sdk/sdks/{sdkId}/versions` and displayed on the SDK portal (issue 4.4). Each version entry includes: version string, generation date, schema version, changelog, and download link.

**Acceptance Criteria**

- SDK version format `{schemaVersion}-sdk.{buildNumber}` is applied consistently
- Build numbers increment when SDK templates change without a schema change
- CHANGELOG.md is generated with categorized changes (models, API, auth, dependencies)
- Platform-specific release notes are formatted for GitHub, CocoaPods, Maven, and pub.dev
- Version history API returns all versions with changelog and download links
- Older SDK versions remain downloadable for consumers pinning to specific versions

**Part of Epic: SDK Management & Distribution**

---

#### 4.4 (#1148) — SDK Portal & Documentation

SDK consumers need a single destination for documentation, downloads, and integration guides. This issue builds the public-facing SDK portal where developers find everything they need to integrate the generated SDK into their mobile app.

The portal is a NextJS page at `/mobile-sdk/portal/[schemaId]` with sections: **Overview** (which platforms are available, current versions, quick-start code snippet), **Installation** (platform-specific installation instructions—SPM for iOS, Gradle for Android, npm for React Native, pub.dev for Flutter), **Getting Started** (step-by-step tutorial for first API call), **API Reference** (auto-generated from the SDK's models and methods), and **Changelog** (version history with migration guides).

The API reference is generated from the SDK's AST: each model class gets a documentation page with all properties, types, and descriptions. Each API method gets a page with parameters, return type, error cases, and a code example. The reference is searchable and navigable via a sidebar.

The portal uses Radix `Tabs` for switching between platforms, `NavigationMenu` for the sidebar, `Accordion` for expandable code examples, and `CopyButton` for one-click code copying. Branding is customizable per tenant (logo, colors, domain) for white-labeling.

**Acceptance Criteria**

- Portal displays all available platforms with current versions and quick-start snippets
- Installation instructions are platform-specific (SPM, Gradle, npm, pub.dev)
- Getting Started tutorial walks through authentication setup and first API call
- API Reference is auto-generated with searchable model and method documentation
- Changelog displays version history with migration guides for breaking changes
- Branding customization (logo, colors) is supported for white-labeling

**Part of Epic: SDK Management & Distribution**

---

#### 4.5 (#1149) — Enterprise SDK Customization

Enterprise customers need SDKs that match their internal standards: custom networking layers, internal auth providers, corporate code style, and private distribution channels. This issue builds the customization layer that lets enterprises tailor generated SDKs.

Template overrides allow enterprises to replace or extend default templates. An enterprise might override `api-client.hbs` to use their internal networking library instead of URLSession/Retrofit, or override `auth.hbs` to integrate with their corporate SSO. Overrides are uploaded via `POST /api/v1/mobile-sdk/templates/{tenantId}/overrides` and stored per-tenant.

Code style configuration lets enterprises specify: naming conventions (prefix all classes with company abbreviation), documentation format (Javadoc vs. KDoc vs. Swift DocC), and file organization (group by feature vs. group by layer). These preferences are stored in a tenant configuration and applied during generation.

Private distribution support generates SDK packages ready for internal distribution: a private CocoaPods spec for iOS, a private Maven repository artifact for Android, or a private npm package for React Native. The generation pipeline produces the distribution-ready artifact alongside the ZIP download.

The enterprise customization page at `/mobile-sdk/enterprise` uses Radix `Tabs` for template overrides, code style, and distribution settings. `Dialog` components handle file uploads for template overrides. `Select` handles code style choices.

**Acceptance Criteria**

- Template overrides are uploaded per-tenant and applied during SDK generation
- Code style configuration controls naming conventions, doc format, and file organization
- Private CocoaPods spec generation produces valid `.podspec` files for internal distribution
- Private Maven artifact generation produces valid POM and AAR files
- Enterprise customizations are isolated per-tenant with no cross-tenant leakage
- The enterprise customization page provides template upload, preview, and style configuration

**Part of Epic: SDK Management & Distribution**

---

## Parallel Work Guide

The following issues can be worked simultaneously within and across epics:

**Epic 1 (Code Generation Engine):**
- 1.1 (Schema-to-AST Parser), 1.2 (Template System), and 1.4 (Type Mapping Registry) are independent foundations and can all be developed in parallel.
- 1.3 (Multi-Language Pipeline) depends on 1.1, 1.2, and 1.4 to assemble the end-to-end pipeline.
- 1.5 (Generation API) depends on 1.3 for the pipeline but can stub the pipeline during development.

**Epic 2 (iOS & Android SDK Templates):**
- 2.1 (Swift Models), 2.2 (iOS Networking), 2.3 (Kotlin Models), and 2.4 (Android Networking) can all be developed in parallel since they are independent platform templates.
- 2.5 (Auth & Offline Caching) depends on 2.1/2.2 (iOS) and 2.3/2.4 (Android) for the platform integration points.

**Epic 3 (Cross-Platform SDK Templates):**
- 3.1 (React Native), 3.2 (Flutter), and 3.3 (Xamarin) can all be developed in parallel as independent platform templates.
- 3.4 (Platform Adaptations) depends on at least 2 platform templates being available for testing.
- 3.5 (Test Harness) depends on all platform templates being partially available for fixture generation.

**Epic 4 (SDK Management & Distribution):**
- 4.1 (Generation UI), 4.3 (Versioning), and 4.5 (Enterprise Customization) can be developed in parallel.
- 4.2 (Auto-Update) depends on 4.3 for the versioning system and 1.5 for the generation API.
- 4.4 (SDK Portal) depends on 4.3 for version history data.

**Cross-Epic Parallelism:**
- Epic 1 is the foundation; all other epics depend on the code generation engine.
- Epic 2 and Epic 3 are independent of each other and can be developed by separate teams once Epic 1 is complete. These represent the largest parallelization opportunity.
- Epic 4 depends on Epics 2 and 3 for generated SDK content but can be stubbed during development.
- Within Epic 1, the three foundation issues (1.1 + 1.2 + 1.4) form a parallelizable first sprint.
