# Apiome 10-2026 RC7

We continue to improve the platform based on your feedback with improvements and new features!

---

## Features/Improvements

- Suite Access:
  - **Designer** and **Developer** now show in the **Build** section and on the launcher only for a user an administrator gives **Suite Access** (admin console → **Users** → ⋮ → **Grant Suite Access**). A license, including the free plan, no longer shows them
- Version:
  - The version shown on the home page, in the user menu and on **Help & docs** now names its release candidate (`RC7`)
- Import:
  - Changes step — importing a spec whose slug matches an existing project now stops at **Changes** before **Import**: added, changed, removed and breaking counts against the project's latest version, a filterable list of every changed path, operation, schema and property (breaking first), and a **Side-by-side spec** tab with the latest version on the left and the incoming spec on the right. Breaking changes are a warning, never a block — **Continue to import** is always available, for a dry run too
- API Formats:
  - Adds formats:
    - Bruno collection import — a Bruno collection folder (`bruno.json` and its `.bru` files) imports as one REST API from an archive or straight from git, with the same result either way: folders as operation groups, requests as operations with inferred body schemas, `{{baseUrl}}` as a server variable and whole-variable parameters with their value as default; credentials and secret variables are never kept, and scripts and tests are listed in the coverage ledger
    - Insomnia collection import — an Insomnia v4 (JSON) or v5 (YAML) export and its environment files become one REST API: folders as operation groups, requests as operations with inferred body schemas, `{{ _.baseUrl }}` as a server variable and whole-variable parameters with their environment value as default; saved credentials, secret variables and cookie jars are never kept, and scripts, template tags, gRPC and WebSocket requests are listed in the coverage ledger
    - HAR capture import — save your browser's devtools Network log (or a proxy capture) as HAR and catalog the API it called: repeated calls become parameterized operations with request and response schemas inferred from the traffic, page assets and analytics are left out, each host becomes its own catalog item, and cookies and credentials are never kept
  - Collection source cards — **HAR (inferred)**, **Insomnia collection** and **Bruno collection** each have a card in **Import to catalog** (HAR with an activity icon), take a file or a `.zip` / `.tar.gz` archive, and import from the CLI with `apiome import har`, `apiome import insomnia` and `apiome import bruno`. A single Bruno `.bru` request is no longer mistaken for an `.http` file
  - RAML includes and libraries — a RAML API split across files imports whole: types pulled in with `!include` and the types of `uses` libraries (as `alias.Type`) join the catalog item, references that leave the upload are refused, and a missing file or invalid document says exactly what and where
  - RAML resource types and traits — a RAML API that shares shapes through `type:` and `is:` imports with them applied: each operation carries the headers, parameters, bodies and responses they add (with `<<parameters>>` filled in), bodiless responses such as `204` keep their status, the operation records which resource type and traits shaped it, and an OpenAPI export keeps every response under its own status code
  - Thrift file sets — upload a `.zip` / `.tar.gz` of a Thrift API split across files and every `include`d file joins the catalog item: `shared.Money` links to its definition, services that `extend` another record it, diffs between versions grade fields by their Thrift id (a rename that keeps the id is dangerous, a reused id breaking), and a Thrift lint pack checks namespaces, `required` fields, duplicate ids, enum numbering and `oneway` methods
  - Smithy multi-file models — upload a `.zip` / `.tar.gz` of a Smithy model split across files and the Smithy CLI assembles it into one JSON AST before cataloging: namespaces spread over files and shapes from other namespaces join one catalog item, and the item records the model's `$version`, namespaces and source files. A Smithy JSON AST (`.json`) imports on its own too
  - TypeSpec projects — upload a `.zip` / `.tar.gz` of a TypeSpec API split across `.tsp` files and the TypeSpec compiler turns it into OpenAPI, which is cataloged (with the server now shipping `@typespec/http`, `rest`, `openapi3` and `versioning`); a project that does not compile lists each error with its file and line, and archives of RAML, Smithy, Thrift and TypeSpec files now find their entry point instead of being refused
  - TypeSpec `tspconfig.yaml` — a TypeSpec project's `tspconfig.yaml` now sets the emitted OpenAPI version and options (`omit-unreachable-types`, `safeint-strategy`, …), a single `.tsp` with its config compiles as a project, every setting left out is listed on the catalog item, and `apiome import typespec ./my-api/` imports a project folder from the CLI
  - OData CSDL JSON — OData v4 metadata imports in its JSON form as well as XML, every v4 document is checked against the OASIS CSDL schema, and a document that strays from it still imports with each problem listed on the catalog item and reported by the new `odata.csdl-schema` lint rule
  - Smithy from the CLI — `apiome import smithy` takes a `.smithy` file, a JSON AST, an archive or a model folder (packed for you, build output left out), and the Smithy card accepts the same files
  - OData live discovery — `apiome import odata --discover <service root>` imports a running OData service's `$metadata` (a `$metadata` URL or SAP `sap-client` query works too), and OData now counts among the live-discovery formats
  - WSDL live fetch — `apiome import wsdl --discover <service URL>` imports a running SOAP service's WSDL (`?singleWsdl` first, so WCF services arrive fully inlined), a WSDL split across files with `wsdl:import` now imports whole, and archives of `.wsdl` / `.xsd` files find their root
  - OpenRPC live discovery — `apiome import openrpc --discover <endpoint>` imports a running JSON-RPC service's OpenRPC document through `rpc.discover`, diffs now grade parameter changes by position, name and requiredness, and a new `openrpc` lint pack checks duplicate methods and parameters and parameter order
  - OData validation — OData metadata is now checked against the OASIS CSDL XML schemas too (catching misspelled attributes the JSON form cannot see), and every name it uses is followed: an undeclared type, entity set, partner, binding or operation, or an entity type with no usable key, is listed on the catalog item and reported by the new `odata.unresolved-reference` and `odata.entity-key` lint rules (v2, v3 and v4)
  - Avro lint pack — Avro schemas (`.avsc` and IDL) are now linted as written: a default that is not a value of its type (or of a union's first branch), a nested or repeated union branch, an optional field written `[T, "null"]` or missing `"default": null`, an invalid or clashing alias, and a `doc` tools would drop are each reported by a new `avro.*` rule
  - Avro fingerprints — every Avro schema now records Avro's Parsing Canonical Form hashes (CRC-64-AVRO and SHA-256) and a semantic hash that also covers `doc`, `default`, `aliases` and `order` for each type it declares; a `doc`-only edit changes the semantic hash but not the PCF, and mints no new catalog version
  - Avro compatibility — Avro schemas are now checked the way a Confluent Schema Registry checks them: comparing two versions grades each change by whether new readers can read old data (breaking) or only old readers fail (dangerous), and the schema registry enforces `BACKWARD`, `FORWARD` and `FULL` (and their `TRANSITIVE` forms) on Avro subjects, refusing an incompatible version with Confluent's own messages
  - REST hypermedia conventions — an OpenAPI, Swagger or RAML API that declares JSON:API, HAL, HAL-FORMS, JSON-LD or Hydra media types is tagged with them: the catalog item lists each convention with its resource types, link relations or templates, a **Convention** filter appears on the Catalog to narrow the list to one, and a new `rest-conventions` lint pack checks each body against its convention (resource objects, `_links.self`, link `href`s, `_templates.default`, `@context`, Hydra members)
  - z/OS Connect binding — a z/OS Connect descriptor, the copybooks that declare its request and response structures, and the OpenAPI it targets are suggested as links to each other, and the descriptor's catalog item shows a **z/OS Connect binding** panel: each operation with its COBOL structures, the copybook items that declare them and the OpenAPI that defines it
  - WS-I lint pack — SOAP / WSDL descriptions are now checked against the WS-I Basic Profile: `encoded` messages, bindings that mix rpc and document styles, document-/rpc-literal bodies with the wrong parts, operations a receiver cannot tell apart, shared `soapAction`s, and imports that do not resolve are each reported by a new `wsi.*` lint rule
  - TypeSpec compiler warnings — a compiled TypeSpec project now runs TypeSpec's built-in linter rules, and every warning the compile reports (such as `deprecated` or `@typespec/http/op-reference-container-route`) is kept on the catalog item with its file and line and reported by the new `typespec.compiler-diagnostic` lint rule
  - RAML lint pack — RAML APIs are now checked by AMF's validation of the RAML profile on every import, each problem reported with its file and line (a self-contained document AMF rejects now imports, with its violations as errors), plus hygiene checks for undeclared `securedBy` schemes, unused base-URI and URI parameters, and methods without responses
  - API Blueprint lint pack — API Blueprint imports are now also run through drafter, the reference API Blueprint parser, and each warning (a parameter missing from the URI template, a duplicate resource, an action with no response) or error (an undefined base type) is reported with its line by a new `apiblueprint.*` lint rule
  - Smithy lint pack — Smithy models are now validated by the Smithy CLI on import with the `smithy-linters` validators switched on (`CamelCase`, `MissingPaginatedTrait`, `AbbreviationName`, `ShouldHaveUsedTimestamp`, `MissingSensitiveTrait`, …), and each event is reported with its file and line by a new `smithy.*` lint rule
  - OData breaking changes — comparing two versions of an OData service now grades each change by OData's own model-versioning rules: a new nullable property or collection navigation is safe, a new required property, a changed key or a changed property type is breaking, and every breaking change says whether the schema's `Core.SchemaVersion` was bumped
  - WSDL / XSD breaking changes — comparing two versions of a SOAP service now grades soapAction, binding-style and message-pattern changes, and XML Schema changes element by element (minOccurs / maxOccurs, nillable, defaults, enumerations, lengths, patterns and bounds), treating new optional elements as dangerous because SOAP receivers validate strictly
  - Fuller WSDL catalog items — a SOAP service's faults now appear as error messages, rpc-style messages with several parts keep every part, and each port is a server with its SOAP 1.1 / SOAP 1.2 / HTTP binding, all written back when you export to WSDL
  - TypeSpec versioned services — a TypeSpec service using `@typespec/versioning` now compiles every version: the catalog item describes the newest one, and lists each version with whether the step from the previous one was breaking or safe (and why)
  - RAML breaking changes — comparing two versions of a RAML API now grades parameter, property and enum changes individually: a new required parameter or property, a changed type or a removed enum value is breaking, a new optional one is safe
  - Smithy breaking changes — comparing two versions of a Smithy model now runs Smithy's own `smithy diff` and grades each change by its findings: `ERROR` is breaking, `DANGER` and `WARNING` are dangerous, `NOTE` is safe. Findings that belong to no single change, such as reordered members, are listed separately and still count toward the overall result, and a single `.smithy` file is now read by the Smithy CLI too, inline input and output members included
  - Arazzo source resolution — a Projects import of an Arazzo workflow validates its `sourceDescriptions` and resolves each step's `operationId` / `operationPath` against the documents supplied with the import, keeps an unresolved reference with a warning, and returns the result as `arazzoResolution` on the import job; the **Import** dialog sends only the workflow for now, so sources show as not in the import bundle
  - OpenAPI 3.2 `$self` references — a `$ref` that resolves against the document's `$self` back into the same document links to its class like a local reference, references to other documents are kept and listed in a warning, a `summary` / `description` beside a `$ref` is kept as a local override, and **Analyze** lists **Document base URI ($self)**
  - OpenAPI 3.2 tag hierarchy — tags keep their `summary`, `parent`, `kind` and `externalDocs` on the project (`x-apiome-tag-taxonomy`), classes list the tags their schema declares, a cyclic or undeclared parent imports as a top-level tag with a warning, and **Analyze** lists the taxonomy under **Feature compatibility**
  - OpenAPI 3.2 QUERY and custom methods — a path's `query` operation and its `additionalOperations` entries (such as `REPORT`) import as path operations with their request and response schemas, keep their method token, and export to `x-apiome-query-operation` / `x-apiome-additional-operations` so they survive a round-trip
  - OpenAPI 3.2 streaming responses — an `itemSchema` under JSON Lines (`application/jsonl`), JSON text sequences (`application/json-seq`) or Server-Sent Events (`text/event-stream`) imports its element schema as a class tagged `x-apiome-stream-kind`, the operation links to it, and **Analyze** lists the streaming media types under **Feature compatibility**
  - Secret scrubbing for collections and captures — Postman, Insomnia, Bruno, HAR and `.http` imports always strip credentials, whatever your workspace's scrub policy says. Variables keep their names but not their secret values, auth becomes security-scheme stubs in the converted OpenAPI document, and the catalog item's **Provenance** tab lists every redaction in a new **Secret scrub** row

## Bug Fixes

- Sign-in:
  - Confirming a new account no longer flashes *We could not sign you in automatically* before the **Let's set up your first workspace** screen
  - **Sign In** stays disabled while you are being signed in, instead of turning back on and inviting a second click; it comes back only if the attempt fails
  - The sign-in page's *Watch our intro video* link, which no longer worked, is now **Explore our YouTube** and opens the Apiome YouTube channel
- Admin console:
  - Signing up again with the address of a deleted account no longer fails with *We could not send the confirmation email*. Deleting a user now releases their email address and linked sign-ins, signs them out everywhere, and the reason for a failed sign-up is logged
  - A disabled or deleted account can no longer sign in with its password
  - The **Users** list shows each account's **Created** date instead of *Invalid Date*, and a new **Last active** column shows its last sign-in or activity (*Never* for an unused account). Email and password sign-ins are now recorded too, not just provider sign-ins

---

View our YouTube channel [here](https://www.youtube.com/) for detailed tutorials and walkthroughs!

---

## Feedback

We'd love to hear your thoughts! Your feedback helps us make Apiome better.

---

**Thank you for using Apiome!**

*Last updated: October 25, 2026*

