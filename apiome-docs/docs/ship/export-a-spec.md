---
title: "Export a spec"
description: "Export a catalog item or version to another format, in the app or CLI."
sidebar_position: 5
tags: [export]
---

Apiome reconstructs the full OpenAPI 3.1 document (or Arazzo workflow document, or JSON Schema)
for a **published** version on demand. You can download it from the CLI or fetch it directly over
REST in JSON or YAML.

Those three have dedicated endpoints, but they are not the whole export surface: Apiome emits
**54<!--format-count:exportable--> formats** — AsyncAPI, GraphQL, Proto3, Avro, Thrift, Smithy,
TypeSpec, WSDL, XSD, OData, EDI X12, SAP IDoc, HL7 v2, FHIR, COBOL copybooks and more —
through the export-target registry. The full list, and which formats round-trip (import *and*
export) versus export only, is generated at [Supported formats](../bring-in/supported-formats.md).

Run `apiome export targets` to see the same list for a specific version, and
`apiome export evidence --target <format>` to see what a given conversion preserves before you
generate it.

## In the app: the Export dialog

The **Export** dialog exports one source to one format, and shows what the conversion keeps before
you download anything.

1. Open it from a catalog item (**click "Export"** in the item's header) or from a version
   (on **Versions**, open the version's **⋯** menu and **click "Export to another format…"**).
2. The **Source** step names the item and version, and measures how well each format can carry
   it. **Click "Choose target"**.
3. Pick a format. Each card shows a fidelity badge for *this* source, such as *lossless* or
   *lossy*, and the line under the cards says how much is preserved (*64% preserved*). A card
   that cannot export this source is greyed out, with the reason written on it. **Click
   "Continue"**.
4. The fidelity report lists every construct the conversion drops, approximates or invents, and
   where each one lands. If the conversion loses something, tick the acknowledgement, or type the
   phrase it asks for when the result would be types only.
5. **Click "Export"** (**"Export anyway"** after an acknowledgement), review the file, and
   **click the "Download" button that names the file**, or **"Download .zip"** for everything in one
   archive.

   A format that writes several files (an Avro or Protobuf schema set, for example) previews its
   main file, and the zip button reads **"Download all files (.zip)"**. It runs the export as a job
   and downloads the job's bundle: every emitted file plus a `manifest.json` that lists them. The
   download starts when the job finishes; if the job fails, the dialog shows why.

**“Open in Export Studio”** at the foot of the dialog carries the source, target and options into
the [Export studio](./export-studio.mdx), which adds options, a verify step and a job you can watch.
For catalog items, including several at once, see [Export catalog items](./export-catalog-items.mdx).

<Screenshot id="export-dialog-targets" alt="The Export dialog's target step: format cards with fidelity badges, one greyed out with its reason" />

<Screenshot id="export-dialog-fidelity" alt="The Export dialog's fidelity report for Protobuf: what is kept, approximated and dropped, and the acknowledgement" />

## Formats the Export dialog offers

The dialog, `apiome export targets` and `GET …/export/targets` all offer the same **54<!--format-count:exportable--> formats**.
Most export from any source. A few write one format's own structure back out, so they export only
a source imported in that format: an EDI X12 interchange in the catalog exports back to EDI X12,
but an OpenAPI version does not. For any other source their card is greyed out with that reason,
and an export request is refused with `422`.

Formats that write HTTP routes or saved requests (Kong, Gateway API, Envoy, Istio, Traefik, Apigee,
AWS API Gateway, Azure API Management, Hoppscotch, Thunder Client and the `.http` file) need at least
one HTTP operation, and the data-contract formats (ODCS, Kafka Connect) need at least one record type.
API Blueprint needs at least one HTTP operation or one type. For a source without one, the card is
greyed out with that reason; for example, a GraphQL schema with no HTTP bindings cannot become a Kong
configuration.

A format that needs a tool this deployment does not have installed is greyed out the same way, with
the missing tool named on the card. It is never offered and then left to fail: an export to it is
refused with `422` and the same reason before anything runs. `apiome export targets` shows the reason
in its **Why not** column, and `apiome export <format>` stops with it (exit 2) before starting a job.

### When an item has nothing to export from

Exports are built from the source file captured when the item was imported. If that file was not
kept, or was not stored because it contained credentials, the **Export** dialog and the
[Export studio](./export-studio.mdx#1-source) say so instead of failing. **Click "Re-import"** to open **Import to catalog** and import the source
again.

<Screenshot id="export-dialog-missing-source" alt="The Export dialog for Orders RPC: it can't be exported because its source file wasn't kept, with a Re-import button" />

Over the API, every export route answers `422` with a structured `detail`:
`{"code": "source-not-captured" | "source-withheld", "message", "artifactId", "versionId", "reimport": true}`.
An export job fails with `SOURCE_LOAD_FAILED`, and its `error.context` carries the same `source_code`
and `reimport`.

### Protobuf and Thrift from an OpenAPI source

An OpenAPI schema's `type` and `format` become the target's own scalar types:

| OpenAPI | Protobuf | Thrift |
| --- | --- | --- |
| `integer` | `int32` | `i32` |
| `integer`, `format: int64` | `int64` | `i64` |
| `number` | `double` | `double` |
| `number`, `format: float` | `float` | `double` |
| `boolean` | `bool` | `bool` |
| `string` | `string` | `string` |

OpenAPI has no field numbers, so the first export numbers each field in the order the schema lists
it: `1`, `2`, `3` and so on. Apiome remembers those numbers for the item, so every later export to
the same format gives each field the same number, even after fields are added, removed or
reordered. A field added since gets the next number not used yet. The fidelity report lists every
number Apiome assigned as *synthesized*. A source that has its own numbers, such as a Protobuf or
Thrift import, keeps them.

### Thrift from any source

Exporting to **Apache Thrift** writes one `<Name>.thrift` file that the Thrift compiler accepts.
Each export is compiled with `thrift` before you download it, when the server has the Thrift
compiler, and read back with Apiome's Thrift importer otherwise.

- **Types.** Objects become `struct`s, enums `enum`s, and unions `union`s. A union that only lists
  its member types gets one optional field per member. Aliases and named scalars become `typedef`s,
  lists `list<…>`, sets `set<…>`, and maps `map<…, …>`. A required field is `required`; every other
  field is `optional`.
- **Errors.** A type returned only as an error response becomes an `exception` and is listed in the
  method's `throws`. An error type also used elsewhere stays a `struct`, and the report says its
  `throws` entry is not written, because Thrift throws only exceptions.
- **Services.** Each service becomes a `service` and each operation a method. A method returns its
  success response's type. An operation with parameters (an OpenAPI path or query parameter, say)
  takes one `<Method>Request` struct that holds them and the body; otherwise it takes its request
  type as `1: T arg`.
- **Names.** Thrift names are plain identifiers that are not reserved words. `com.acme.Order` is
  written `com_acme_Order`, `order-id` is `order_id`, and `default` is `default_`. Each rename is in
  the fidelity report, and a clash gets a number (`addPet2`).
- **Namespaces.** Set the **namespaces** option to write one `namespace` line per language, for
  example `{"java": "com.acme.shop", "py": "acme_shop"}`, or `*` for every language. A Thrift item
  keeps its own namespaces and `typedef`s.
- **uuid.** A UUID is written as `string`, because only Thrift 0.21 and later compilers know the
  `uuid` type. An item imported from Thrift keeps `uuid`.

### OMG IDL (CORBA or DDS) from any source

Exporting to **CORBA IDL** writes one `<Name>.idl` file in OMG IDL 4.2 that reference IDL compilers
accept: omniidl for the CORBA parts and Cyclone DDS `idlc` for the annotated data types. Before you
download it, Apiome reads the export back with its CORBA IDL importer.

- **Profile.** The **profile** option picks what is written. `corba` (the default) writes interfaces
  and exceptions. `dds` writes only the data types a DDS topic can use: no interfaces, no exceptions
  and no member that refers back to its own type. It also marks identifier fields `@key`. A source
  with no data types cannot be exported with `dds`, and the dialog says why.
- **Types.** Objects become `struct`s, enums `enum`s, and aliases and named scalars `typedef`s. Lists
  become `sequence<…>`. A map becomes a sequence of `<Map>Entry` key/value structs. A union becomes
  a discriminated `union` that switches on a generated `<Union>Kind` enum, with one case per member.
  A nullable field is marked `@optional`.
- **Modules.** The item's namespace becomes nested modules: `com.acme.orders` is written
  `module com { module acme { module orders { … }; }; };`. Set the **module** option (`acme::orders`)
  to choose another path. Every type reference is written in full (`::com::acme::orders::Order`).
- **Interfaces.** Each service becomes an `interface` and each operation an IDL operation. Its
  parameters and request body are `in` arguments, and it returns its success response's type. A list
  in a signature is given a `typedef` (`PetSeq`). A type returned only as an error response becomes
  an `exception` and is listed in the operation's `raises`. Any other error response is left out, and
  the report says so.
- **Keys (DDS).** A field named `id`, `<type>Id` or `<type>_id` gets `@key`. Set the **key_fields**
  option to choose the keys yourself, for example `{"Order": ["region", "number"]}`.
- **Names.** IDL names are identifiers, compared without regard to case. `order-id` is written
  `order_id`, `module` is `module_`, and of two members `id` and `ID` the second becomes `ID2`. A
  member cannot share its type's name, and an enum value must be unique in its module, so it may be
  prefixed with its enum's name (`Status_ACTIVE`). Each rename is in the fidelity report.
- **Recursion.** A type may contain itself only through a `sequence`. A direct reference to itself is
  written as a sequence of at most one element. A member that refers back through another type is
  left out, and so is any recursive member under the `dds` profile.
- **From a CORBA item.** An item imported from CORBA IDL keeps its module, `typedef`s, interfaces and
  parameter directions (`in`, `out`, `inout`).

### Smithy from any source

Exporting to **Smithy** writes a Smithy 2.0 model that `smithy validate` accepts. Set the **output**
option to choose the form: `idl` (the default) writes `<Name>.smithy`, `json-ast` writes the Smithy
JSON AST as `<Name>.json`, and `both` writes the two. They describe the same model, so load one of
them, not both together.

Each export is checked before you download it:

1. The **Smithy CLI** validates each file when the server has it, with the same validators a
   `smithy build` runs. An `ERROR` or `DANGER` event fails the export and names the validator, shape,
   line and column (`Target.UnresolvedShape`). `WARNING` and `NOTE` events do not. Without the CLI,
   Apiome's Smithy reader reads the model instead, and a parse error fails the export.
2. The built model is then imported again. If it does not import, the export fails
   (`smithy.reimport`).

- **Shapes.** Objects become `structure`s, unions `union`s, enums `enum`s, maps `map`s, and named
  lists `list`s. A list with no name of its own gets a `<Element>List` shape. A named scalar or an
  alias of a scalar becomes a simple shape (`string AccountId`). An enum value that differs from its
  member name is written `in_progress = "in-progress"`.
- **Traits.** A field that may not be null is `@required`, and a field default becomes `@default`.
  Length limits become `@length`, numeric bounds `@range`, and regular expressions `@pattern`. A list
  that must hold unique items targets a `<Element>Set` shape marked `@uniqueItems`. Descriptions
  become doc comments, and deprecated items get `@deprecated`. A constraint Smithy cannot express,
  such as `multipleOf`, is in the fidelity report.
- **Services.** Each service becomes a `service` and each operation an `operation`. An HTTP
  operation keeps its binding: `@http(method, uri, code)`, with path, query and header parameters
  bound by `@httpLabel`, `@httpQuery` and `@httpHeader`, and the body by `@httpPayload`. When an
  operation needs one, its input and output are generated structures (`<Operation>Input`,
  `<Operation>Output`). GET operations are `@readonly`, PUT and DELETE operations `@idempotent`. A
  GET, HEAD or DELETE request has no body in Smithy, and transport headers such as `Authorization`
  are not bound. The report lists both.
- **Errors.** A type returned only as an error response becomes an `@error` structure, with
  `@httpError` for its status, and is listed in the operation's `errors`.
- **Protocol.** Set the **protocol** option to `restJson1` or `rpcv2Cbor` to mark each service with
  that protocol trait. These traits come from separate Smithy packages, so a build needs them as
  dependencies.
- **Names.** Smithy names are identifiers that must stay unique when case is ignored. `order-id` is
  written `order_id` and keeps its wire name with `@jsonName("order-id")`. A shape cannot reuse a
  prelude name such as `String`, and a clash gets a number (`String2`). Each rename is in the
  fidelity report.
- **From a Smithy item.** An item imported from Smithy keeps its namespace, `$version`, service
  version and operation order. Traits that were imported by name only, such as a `@length` whose
  limits were not kept, cannot be written back, and the report says so. A `resource` is not written
  back either; its operations stay on the service.

The fidelity report lists what Smithy cannot carry, on the type, field or operation it concerns.
The report predicts exactly what the export writes:

- **Dropped:** constraints with no Smithy trait (`multipleOf`, a list of allowed values, a length on a
  number), and a default that does not fit its type. Also dropped: parameters Smithy cannot bind
  (cookies, and transport headers such as `Authorization`), the body of a GET, HEAD or DELETE
  request, error responses that are not objects, and event operations and channels. A route that is
  not a valid Smithy URI, or that repeats another, loses its `@http` binding.
- **Approximated:** renamed shapes and members, aliases written as the type they alias, bodies
  wrapped in a `body` member, scalars written as `String`, and a required member made optional to
  break a cycle.
- **The document.** Smithy has no title, description or servers, so for an item not imported from
  Smithy the report lists each one. The version moves to each service, or is dropped when there is
  no service.
- **Carried.** For each operation and type that is carried, the report names the Smithy shape it
  became, such as `operation getPet @http(GET /pets/{id})` or `structure Pet`.

### TypeSpec from any source

Exporting to **TypeSpec** writes one `.tsp` file that compiles with the TypeSpec compiler Apiome
ships (`tsp` 0.65 with `@typespec/http`), whatever the item was imported from.

Each export is checked before it is offered:

1. It is compiled to OpenAPI with `@typespec/openapi3`. A compile error fails the export and names
   the file, line, column and error code (`unknown-identifier`).
2. The OpenAPI the compile writes is imported the way an uploaded OpenAPI would be. If it does not
   import, the export fails (`typespec.openapi-import`).

Without the compiler on the server, the `.tsp` is read back by the TypeSpec importer instead.

Compiling to OpenAPI also shows what choosing TypeSpec costs compared with exporting straight to
**OpenAPI**: `@typespec/openapi3` names each operation `<Interface>_<operation>`
(`PetService_listPets`), writes a plain `integer` as `int32`, and makes a request body required.

- **Document.** The title becomes `@service({ title: "…" })` on the namespace, and the description
  becomes its doc comment. The version becomes `@info({ version: "…" })` (from `@typespec/openapi`),
  and each server becomes `@server(url, description)` with its variables.
- **Types.** Objects become `model`s, enums `enum`s, and unions `union`s, with named variants or
  their member types. Maps become `model X is Record<V>`, and named lists `model X is T[]`. A named
  scalar becomes `scalar X extends string` (or `int64`, `utcDateTime` …), and an alias of another type
  becomes `alias X = T`. An enum value that differs from its member name is written
  `inProgress: "in-progress"`, and a numeric enum keeps its numbers.
- **Members.** A field that may be null is optional (`tag?: string`). Length limits become
  `@minLength` and `@maxLength`, numeric bounds `@minValue` and `@maxValue` (or their `Exclusive`
  forms), list sizes `@minItems` and `@maxItems`, and patterns `@pattern`. A string format with a
  TypeSpec type of its own becomes that type (`date-time` is `utcDateTime`); any other format is kept
  with `@format`. A default becomes `= value`. Descriptions become `/** … */` doc comments, and
  deprecated items get `#deprecated`.
- **Operations.** Each service becomes an `interface`. An HTTP operation keeps its verb and
  `@route`, with parameters marked `@path`, `@query`, `@header("Name")` or `@cookie("name")`, and
  the body `@body`. A body that is not JSON names its media types in a `Content-Type` header. A plain
  200 response is the return type. Other responses are variants such as
  `{ @statusCode statusCode: 201; @body body: Pet; }`, a `4XX` range is a status between 400 and 499,
  and a `default` error is an `@error` model. An operation with no HTTP binding is written
  `@post @route("/<Service>/<operation>")`.
- **Decorators.** Tags become `@tag("…")`. A parameter's or header's description becomes
  `@doc("…")`, and a deprecated parameter or header gets `#deprecated`. A list of allowed values
  becomes a union of literals (`sort?: "name" | "age"`). A server variable with allowed values gets
  them as its type, and its description as `@doc`.
- **Names.** Every name is kept: a name that is not a TypeSpec identifier, or is a keyword, is written
  in backticks (`` `order-id` ``). A type cannot reuse a built-in name such as `string`, and a clash
  gets a number (`string2`). Each rename is in the fidelity report.
- **From a TypeSpec item.** An item imported from a `.tsp` file keeps its imports, namespace,
  interface routes, field types and decorators, so it exports and re-imports unchanged.

The fidelity report lists what TypeSpec cannot carry, on the type, field or operation it concerns:

- **Dropped:** constraints with no decorator (`multipleOf`, `uniqueItems`), a default that does not
  fit its type, and numeric enum values beside string ones. Also dropped: operations on a method
  TypeSpec has no verb for (such as `OPTIONS`), a second operation on the same route, a path
  parameter missing from its route, multipart media types on a body that is not an object, and
  event operations and channels. A response's own description is dropped too, since an inline
  response gets its status's standard text, and so is the document's id.
- **Approximated:** renames, RPC operations given an HTTP route, aliases (they compile to the type
  they alias), scalars written as `string`, inline schemas written as `unknown`, synthesized path
  parameters and `default` response models. Types from another namespace are declared in the
  document's one namespace.
- **Other API styles.** TypeSpec HTTP describes REST APIs. For a GraphQL, gRPC, event or data-schema
  item the report says the API is reframed as HTTP. Each operation without an HTTP binding is
  listed as a GraphQL query, mutation or subscription, a one-way call or an RPC call, with the
  `POST` route it became. A GraphQL subscription or a streaming call is listed as one request and
  response, and event messages and a second request body are listed as dropped.
- **Carried.** For each operation and type that is carried, the report names what it became, such as
  `op getPet @get /pets/{id}` or `model Pet`.

### FHIR (StructureDefinition) from any source

Exporting to **FHIR** writes each cataloged type as a FHIR **StructureDefinition logical model**
(`kind: logical`), with a **CodeSystem** and **ValueSet** for each enum, in one `collection` Bundle.
Set **fhir_version** to `R4` (4.0.1, the default) or `R5` (5.0.0). Set **packaging** to `per-type` for
one JSON file per resource. Each export is checked by the official HL7 FHIR validator against the
version it declares, or by Apiome's structural FHIR rules where the server has no validator.

**Where to find it.** In **Export studio**, the **FHIR** and **HL7 v2** cards are under
**Healthcare** on the **Target** step. From the CLI, run
`apiome export fhir <item> --option fhir_version=R5 --option packaging=per-type` or
`apiome export hl7v2 <item>`; `apiome export targets --project <item>` lists both. A public item's
**Export** dialog on Browse offers the same two targets.

- **Elements.** Each field is an element. An object used by only one field is nested in its
  parent as a `BackboneElement` (`Pet.owner.name`), and the `explicit-type-name` extension keeps
  its type name. Any other object is a logical model of its own, referenced by its canonical URL
  (`http://example.org/fhir/StructureDefinition/Owner`; set **canonical_base** to use your own).
- **Cardinality.** A field that may not be null has `min` 1, and a list has `max` `*`. `minItems`
  and `maxItems` set the bounds.
- **Types.** FHIR primitives: `string`, `boolean`, `integer`, `decimal`, `date`, `dateTime`, `time`,
  `uri`, `uuid` and `base64Binary`. A 64-bit integer is `integer64` in R5. R4 has no `integer64`,
  so it is written as `integer`, and the report says so.
- **Enums.** Each enum becomes a CodeSystem with one concept per value, plus a ValueSet that
  includes it. The field is a `code` with a `required` binding to that ValueSet.
- **Constraints.** `maxLength`, `minValue[x]` and `maxValue[x]`, and `defaultValue[x]` are written
  as element properties. Patterns, minimum lengths, exclusive bounds, `multipleOf` and allowed
  values become FHIRPath `constraint`s, such as `matches('^[A-Z]+$')`.
- **Unions.** A union whose alternatives are distinct single types (primitives, other models, at
  most one enum) becomes a FHIR **choice element**: a field `value` of that union is written
  `value[x]`, with one type per alternative. Any other union, such as one with two alternatives of
  the same type or a list of the union, becomes a model with one optional element per
  alternative, plus an invariant that exactly one is present.
- **Operations.** FHIR cannot declare operations on logical models. The **capability_statement**
  option (on by default) lists the source's operations in a CapabilityStatement's REST
  documentation, which also carries the title, description and version.
- **From a FHIR item.** An item imported from a FHIR profile or resource is written back in that
  form. An exported logical-model Bundle imports back unchanged.

The fidelity report lists what FHIR logical models cannot express, construct by construct:

| Source construct | In the report |
| --- | --- |
| Operations | Approximated: they are summarized in the CapabilityStatement, and the report warns that the source has operations. Without the CapabilityStatement they are dropped |
| A union of distinct single alternatives | Approximated: a choice element (`[x]`); the alternatives' names are not kept |
| Any other union | Dropped as a type: a model of optional elements with an exactly-one invariant |
| A map, and every field typed by one | Dropped |
| A regular expression, or an `email`, `hostname`, `ipv4` or `ipv6` format | Approximated: a FHIRPath `matches()` constraint, whose regex dialect may differ |
| Another format, `uniqueItems`, a default that does not fit | Dropped |
| A type that contains itself | Approximated: it is modelled by reference, and FHIR tools expand it only to a limited depth |
| A name that is not a FHIR name (`order-line`, `unit-price`) | Synthesized: `OrderLine`, `unitPrice` |
| Event operations, channels, servers | Dropped |
| Aliases, named scalars, coerced primitives | Approximated |

### OData (CSDL) from any source

Exporting to **OData** writes the service's metadata as **CSDL JSON 4.01** (`<Namespace>.csdl.json`),
the canonical form. Set the **output** option to `xml` for CSDL XML (`<Namespace>.edmx`), or `both`
for the two. Each export is checked against the OASIS CSDL JSON schema, or the CSDL XML schemas,
then read back by the OData importer.

- **Entity and complex types.** An object an HTTP operation sends or returns is a resource and
  becomes an `EntityType` with an entity set. Any other object becomes a `ComplexType`. An item
  with no operations (a data schema) exposes each object that no other object contains. An item
  imported from OData keeps its own entity types, complex types and entity sets.
- **Keys.** Every entity type has a `$Key`. An OData item keeps its own key. Otherwise a property
  named `id`, `<Type>Id` or `key` becomes the key, and the report says it was inferred. With no such
  property, a string `Id` property is added as the key, and the report says it was synthesized.
- **Types.** Primitives become their CSDL type: `int64` is `Edm.Int64`, `date-time` is
  `Edm.DateTimeOffset`, and `uuid` is `Edm.Guid`. An unsigned type is widened (`uint32` is
  `Edm.Int64`), and an unknown one is `Edm.String`; the report lists both. Enums become `EnumType`s,
  and a named scalar becomes a `TypeDefinition`. Unions become complex types with one nullable
  property per variant, and maps become open complex types; the report lists both.
- **Properties.** Lists become `$Collection`, and a property whose type is an entity becomes a
  `NavigationProperty`. `maxLength` becomes `$MaxLength` and a default `$DefaultValue`. Patterns,
  ranges, list sizes and allowed values become `Validation` annotations, descriptions
  `Core.Description`, and deprecations `Core.Revisions`.
- **Operations.** An entity set serves the CRUD operations on its resource: `GET /pets`,
  `GET /pets/{id}`, `POST /pets`, and `PUT`, `PATCH` and `DELETE /pets/{id}`. Every other operation
  becomes an unbound **Function** (a `GET` or query that returns a result) or **Action**, imported
  into the entity container. Its path and query parameters and its body become the operation's
  parameters.
- **From an OData 2 or 3 item.** It is written as CSDL 4.01. `MaxLength`, `Precision` and `Scale`
  stay facets, and `Edm.DateTime` becomes `Edm.DateTimeOffset`. The report lists the version
  upgrade and the `sap:` and `m:` annotations, which are not written.

The fidelity report lists what OData cannot carry, in three groups:

| Group | Source construct | In the report |
| --- | --- | --- |
| Keyless types | An entity with an `id`-like property but no declared key | Approximated: the property becomes the key, and is made non-nullable if it was nullable |
| Keyless types | An entity with no key and no `id`-like property | Synthesized: a string `Id` key is added |
| RPC and events | A unary RPC or a GraphQL query or mutation | Approximated: it becomes an Action, or a Function when it is a query that returns a result |
| RPC and events | A gRPC client or bidirectional stream, a GraphQL subscription | Dropped (critical): it is not written |
| RPC and events | A gRPC server stream | Approximated: it returns a collection of its messages |
| RPC and events | Publish and subscribe operations, channels | Dropped |
| Type coercion | An unsigned or unknown primitive | Approximated: it is widened, or written as `Edm.String` |
| Type coercion | A `format` with no CSDL type, such as `email` or `uri` | Dropped |
| Type coercion | `minLength`, `multipleOf`, `uniqueItems` | Dropped |
| Type coercion | Field numbers (Protobuf, Thrift) | Dropped (info) |

Also dropped: header and cookie parameters, declared error responses (OData uses its standard
error format), defaults that do not fit, servers, and the document's title, description and
version. Also approximated: CRUD operations served by an entity set (their query parameters become
OData query options such as `$top` and `$filter`), unions, maps, aliases and renamed elements.

### OpenRPC from any source

Exporting to **OpenRPC** writes an `openrpc.json` document that is valid against the OpenRPC
meta-schema. Each export is checked against that meta-schema before it is offered, then read back
by the OpenRPC importer.

- **Document.** `info` carries the title, version and description. OpenRPC requires a version, so
  an item without one gets `0.0.0`, and the report says so. Servers keep their name, description
  and variables. An item imported from OpenRPC keeps its own `openrpc` version.
- **Methods.** Each operation becomes a method named after the operation. When two services have
  an operation with the same name, the second is written `<Service>.<operation>`. The request
  becomes `params`: an OpenRPC item keeps its own parameter list, and another RPC item gets one
  `params` parameter holding its request type. The response becomes `result`, error responses
  `errors` (`code`, `message` and `data`), tags `tags`, and a deprecated operation gets
  `deprecated: true`.
- **Notifications.** A one-way operation is written as a notification: a method with no `result`.
  An item imported from OpenRPC reads its result-less methods back as notifications.
- **From a REST source.** Each REST operation is reframed as a method, and the report lists each
  one:
  - its path, query, header and cookie parameters and its body become by-name `params`
    (`paramStructure: by-name`), each labeled with where it came from;
  - the success response becomes `result`, and a response with no body is `{"type": "null"}`;
  - numeric error statuses become `errors` with the status as the `code`;
  - the HTTP method and path are kept in the extension `x-http`.
- **Events.** A publish or subscribe operation (from AsyncAPI, for example) becomes a notification.
  Its message and its channel's address parameters become by-name `params`, and the channel address
  is kept in the extension `x-channel`.
- **Schemas.** Named types become `components/schemas`, written with the same JSON Schema mapping
  as the OpenAPI export. Every `$ref` names a written component, and scalars such as `int64` or
  `timestamp` become their JSON Schema form (`{"type": "integer", "format": "int64"}`).

The fidelity report lists what OpenRPC cannot carry. JSON-RPC 2.0 has no HTTP semantics, no
streams and no channels, so each loss of a REST, gRPC or event item is listed on its own:

| Source construct | In the report | Why |
| --- | --- | --- |
| HTTP method and path | Dropped | A method has a name only. `x-http` keeps them, but JSON-RPC clients ignore it. |
| Path, query, header and cookie parameters | Approximated | They become by-name `params`, and each one's description names where it came from. |
| A success status other than 200, such as `201` | Dropped | A result has no status. |
| Error statuses such as `404` | Approximated | They become error codes with the same number. |
| `default` and `4XX` error responses | Dropped | An error needs an integer code. |
| Response headers | Dropped | A result has no headers. |
| gRPC streams, GraphQL subscriptions | Dropped | A JSON-RPC call is one request and one response. |
| Publish and subscribe operations | Approximated | They become notifications. |
| A channel used by an operation | Approximated | Its address is the notification's `x-channel`. |
| A channel no operation uses | Dropped | Nothing carries it. |
| Field numbers (Protobuf, Thrift) | Dropped (info) | JSON Schema properties have no numbers. |

Also dropped: a second success response (a method has one `result`), error payload types (an
OpenRPC error carries a `data` value, not a schema) and repeated field names. Also approximated: a
synthesized version, renamed methods and components, and types with no JSON Schema form (written as
any value).
- **Carried.** For each operation that is carried, the report names the method or notification it
  became, such as `method getPet`.

### Cap'n Proto from any source

Exporting to **Cap'n Proto** writes a `.capnp` schema that compiles with `capnp compile`, whatever
the item was imported from:

- **Types.** An object becomes a `struct`, an enumeration an `enum`, a `oneOf` (or another union) a
  `struct` holding a `union` of its variants, a map a `struct` with a list of `key`/`value` entries,
  and a list `List(T)`. Scalars map as for Protobuf, with Cap'n Proto's own names: `integer` is
  `Int32` (`Int64` with `format: int64`), `number` is `Float64`, `string` is `Text`.
- **Services.** Each service becomes an `interface`, and each operation a method. Its path, query and
  header parameters and its request body are the method's parameters, and its response body is the
  result.
- **Names.** Cap'n Proto wants type names that start with a capital letter and other names in
  camelCase with no underscore, so `first_name` is written `firstName` and `STATUS_ACTIVE` is
  `statusActive`.
- **Numbers.** Fields, enum values and methods are numbered `@0`, `@1`, `@2` in the order the source
  lists them, and the file gets its own `@0x…` id. Apiome remembers both for the item, so every later
  export writes the same numbers and the same file id. A field added since gets the next number.
  Cap'n Proto cannot leave a gap or drop a field, so a field removed from the source stays in the
  schema as `obsolete<Name>`, keeping its number and its size. The fidelity report lists every number
  Apiome assigned as *synthesized*. A Cap'n Proto import keeps its own numbers and file id.

When the server has the Cap'n Proto compiler, every export is compiled before it is delivered. A
schema that imports other `.capnp` files is not compiled on its own.

### FlatBuffers from any source

Exporting to **FlatBuffers** writes one `<Name>.fbs` schema that compiles with `flatc`, whatever the
item was imported from — for games, embedded devices and robotics. Operations and channels are left
out: a FlatBuffers schema describes data only.

- **Types.** An object becomes a `table`, an enumeration an `enum`, a `oneOf` (or another union) a
  `union`, and a list a vector `[T]`. An object imported from a FlatBuffers `struct` stays a `struct`
  when all its fields fit one (numbers, enums and other structs). An enum gets the smallest integer type
  its values fit (`enum Status : byte`) and lists them in ascending order.
- **Scalars.** Sized integers keep their width (`int32` is `int`, `uint8` is `ubyte`), an unsized
  `integer` is `long`, `number` is `double`, text and timestamps are `string`, and bytes are `[ubyte]`.
  FlatBuffers has no typedef, so an alias is written as the type it stands for.
- **What FlatBuffers cannot hold directly** gets a small table of its own, listed in the fidelity
  report: a map becomes a vector of `<Map>Entry` tables with a `key` (marked `(key)`, so a reader can
  look entries up) and a `value`; a list of lists becomes a vector of `<Name>Item` tables; a union
  member that is not a table (a `string`, say) is wrapped in `<Union><Member>`.
- **Required and defaults.** A required text, bytes, list or object field is marked `(required)`. A
  number, boolean or enum default is written as `= value`; an enum field with no default gets the
  enum's first value when `0` is not one of its values, because FlatBuffers would otherwise default it
  to `0`.
- **Names.** Names use letters, digits and underscores and are not FlatBuffers keywords: `order-id`
  is written `order_id` and a field named `string` is `string_`. Each rename is in the fidelity report.

**Field ids.** Every table field is written with its id, `(id: N)`, in id order — the id is what a
reader matches a field by. Ids start at `0`, and a union field takes two (its hidden `<name>_type`
field and its value). Apiome remembers the ids it assigned for the item, so every later export writes
the same ids and an unchanged item exports byte for byte the same. A field added since gets the next
free id. A field removed from the source keeps its id as a `(deprecated)` placeholder, so readers built
from the earlier schema still read the other fields correctly. A FlatBuffers import keeps its own ids
and deprecated slots.

Options:

- **root_type** — the table a buffer starts with, by type name (`Order`) or key. By default it is the
  imported schema's `root_type`, and none for other sources. Naming a type that is not a table is
  refused.
- **include_comments** — on by default; descriptions are written as `///` comments.

When the server has the FlatBuffers compiler, every export is compiled with `flatc` before it is
delivered; otherwise it is read back with Apiome's FlatBuffers importer. A schema that includes other
`.fbs` files is not compiled on its own.

### COBOL copybook from any source

Exporting to **COBOL Copybook** writes the item's data types as copybook record layouts, `<Name>.cpy`,
for z/OS Connect, CICS and IMS programs. An item imported from a copybook is written back exactly as
it was imported — its pictures, usages, tables and `REDEFINES` — and the options below do not change it.
Any other item is laid out like this:

- **Records.** Each object that no other object contains is an `01` record. Objects inside it are
  written inline as group items, with levels `05`, `10`, `15` … (a smaller step when a record nests too
  deep to stay within level 49). An object that contains itself is written once; the inner reference is
  left out and listed in the report. A model with no object is refused.
- **Names.** COBOL data names: `orderLineItems` and `order_line_items` are written `ORDER-LINE-ITEMS`,
  a reserved word gets `-X` (`STATUS-X`), and a name is cut to 30 characters. Every name is unique in the
  copybook — a clash gets `-2`, `-3` … within the 30 — so nothing needs `OF` to be referenced, and the
  same item always gets the same names.
- **Text** is `PIC X(n)`, `n` from `maxLength`. Dates are `PIC X(10)` (`YYYY-MM-DD`), times `X(15)`,
  timestamps `X(32)` and UUIDs `X(36)`. Other text gets the **default_string_length** (255), and the
  report lists each.
- **Numbers.** 16-, 32- and 64-bit integers are `PIC S9(4)`, `S9(9)` and `S9(18)` (`9(n)` when the
  minimum is 0 or more), binary (`COMP`). A decimal is packed, `PIC S9(p)V9(s) COMP-3`, with 18 digits in
  all and its scale from `multipleOf` (`0.01` is 2 places), else **decimal_scale**. A float is `COMP-1`
  or `COMP-2`.
- **Booleans and enumerations.** A boolean is a one-character flag with two condition names,
  `88 <NAME>-TRUE VALUE 'Y'` and `88 <NAME>-FALSE VALUE 'N'`. An enumeration is `PIC X(n)` (or a number)
  with one `88` level per value.
- **Lists.** A list of a fixed size is `OCCURS n TIMES`. Any other list is
  `OCCURS min TO max TIMES DEPENDING ON <NAME>-COUNT`, with the counter written just before it; `max` is
  `maxItems`, else **default_occurs** (10). A list inside another list is a fixed table of its maximum,
  because `DEPENDING ON` is not allowed there.
- **Unions** are written as items that share storage: each member after the largest one
  `REDEFINES` it. A union with a member holding a list that varies in size is left out, because COBOL
  cannot overlay an `OCCURS DEPENDING ON` table.
- **Rules a picture cannot hold** — a `pattern`, a `format` such as `email` — are written as comment lines
  just above the item (`* pattern: ^[A-Z]{3}$`).
- **Left out:** maps, operations and channels — a copybook describes record layouts only.

Options:

- **numeric_usage** — `comp` (default): binary integers, packed decimals and floats; `display`: every
  number zoned (`PIC S9(9)`, floats as decimals).
- **default_string_length**, **default_occurs**, **decimal_scale** — what is used when the source does
  not say (255, 10 and 2).
- **fixed_format** — on by default: code in columns 8–72, a long entry continued on the next line, and
  `*` comments in column 7. Turn it off for free format: no column limits and `*>` comments.
- **include_comments** — on by default; turn it off to leave out the header comment.

A copybook is fixed-width and positional, so the fidelity report lists — on each field, by its path in
the source — everything the layout had to invent or change, computed for the options you pick:

| In the source | In the report |
|---|---|
| Operations, services and channels | Dropped (critical). An item that has any also gets a **types-only** warning counting them — export it to OpenAPI or AsyncAPI as well to keep them |
| Text with no `maxLength` | Synthesized (warning): the default `PIC X(n)` |
| A list that varies in size | Synthesized (note): the `<NAME>-COUNT` counter. With no `maxItems`, also approximated (warning): the default maximum |
| A name changed to COBOL's rules (`order_id` → `ORDER-ID`) | Synthesized (note), naming the COBOL name |
| A union | Approximated (warning): `REDEFINES`. Dropped when a member varies in size |
| A `pattern`, a `format` | Approximated: a comment line, which nothing checks |
| An optional field | Approximated (note): a record has no null — the field is always present, and an absent value is written as spaces or zeros, a convention to agree with the record's readers |
| A list inside a list, a float with `display` usage, a type with no COBOL form | Approximated (warning) |
| A map, a record that contains itself, a field whose type holds no value | Dropped |
| A document of another format | Approximated (note): it reads back as a copybook item |

An item imported from a copybook is written back as it was, so its report lists nothing invented.

### X12 implementation guide from any source

Exporting to **X12 implementation guide** describes the item's types as an X12 transaction set, for
onboarding trading partners. It is not an interchange: it is the guide partners build their
interchanges from. You get three files, downloaded together as a `.zip`:

- `<Name>.x12-guide.json` — the machine-readable guide: the transaction set, every segment with its
  elements, and the structure (positions, loops, usage and maximum use);
- `<Name>.x12-segments.csv` — the segment dictionary, one row per element, for spreadsheet tools;
- `<Name>.x12-guide.md` — the same guide for people to read.

How the types are laid out:

- **Segments.** Each object becomes a segment of its plain values, in field order. Its segment ID is
  made from its name — `PurchaseOrder` is `PUR`, `OrderLine` is `ORD` — unique in the guide and never
  an envelope ID (`ST`, `SE`, `GS` …). Elements are referred to by segment and position: `PUR01`,
  `PUR02` …
- **Loops.** An object inside another object follows it as a child segment. A list of objects is a loop
  that repeats up to `maxItems` (`>1` when there is no limit), and a list of plain values is a segment of
  one element, repeated. The item's top-level objects sit directly in the transaction set, between the
  `ST` header and the `SE` trailer, and positions number the whole structure `0100`, `0200` …
- **Usage.** A required field is mandatory (`M`), any other optional (`O`).
- **Notes.** A rule an element type cannot enforce — a `pattern`, a `format` such as `email`, a minimum or
  maximum, a set of allowed values — is written as a note on the element (in the JSON, the CSV and the
  Markdown guide).
- **Codes.** An enum value is used as a code when it is upper-case letters and digits no longer than
  **max_code_length** (3). Any other value gets a code made from it — `ON-HOLD` becomes `ONH` — and the
  guide shows the value next to it.
- **Left out:** unions and maps (a segment holds flat values only), an object that contains itself,
  operations and channels. Each is listed in the export's losses.

| In the source | In the guide |
|---|---|
| Text | `AN`, `maxLength` (or the **default_element_length**, 80) as its maximum; a UUID `AN` 36/36 |
| An enumeration, a boolean | `ID` with a code list — the enum's values, or `Y`/`N` |
| An integer | `N0`, as many digits as its width allows (3, 5, 10 or 18) |
| A decimal | `N2` (implied decimal places) when `multipleOf` gives its scale (`0.01`), else `R` |
| A float | `R` |
| A date | `DT` (`CCYYMMDD`) |
| A time | `TM` (`HHMM` to `HHMMSSDD`) |
| A timestamp | Two elements: its date (`DT`) and its time (`TM`) |

An item imported from X12 keeps its segment IDs, its element references and the order of its
interchange, and a position the sample left empty is marked *not used* (`X`).

Options:

- **transaction_set** — the set's 3-digit ID (`850`, `810`, `837` …). By default an imported X12
  item's own, else `850`.
- **version** — the 6-digit X12 version (`005010`, `004010` …). By default an imported X12 item's own,
  else `005010`.
- **default_element_length** — the maximum of a text element whose source has no `maxLength` (80).
- **max_code_length** — the longest enum value used as a code as it is (3).

A model with no object at all is refused: there is nothing to lay out.

X12 is the most constrained target, so its fidelity report lists every change on the field it came
from, computed for the options you pick:

| In the source | In the report |
|---|---|
| A union, a map, an object that contains itself, more than 99 values in one object | Dropped (**critical**) |
| Operations, services and channels | Dropped (**critical**), with a **types-only** warning counting them |
| Text with no `maxLength` | Synthesized (warning): the default element length |
| An enum value that is not a valid code | Synthesized (warning): the code made for it |
| A segment ID made from a name, a marker element for an object with no plain value | Synthesized (note) |
| A list of lists | Approximated (warning): flattened into one list |
| A rule kept only as a guide note | Approximated (warning) |
| A decimal with no known scale | Approximated (warning): `R`, so its precision is not fixed |
| A decimal with implied places (`N2`), a float (`R`), a timestamp split into date and time | Approximated (note) |

**Critical losses need confirming.** When a type would lose a union, a map or other values
outright, the export is a *severe* conversion: the Export dialog, `POST …/dispatch` and export jobs
ask you to confirm before they run, and the warning names each construct and why (in the guard's
`reasons`, and in full in `critical_details`). An item with operations is warned that only its schemas
export, and still lists those constructs.

### WSDL and XSD from any source

Exporting to **WSDL** writes a SOAP 1.1 description in the WS-I document/literal style, whatever the
item was imported from. By default you get two files, downloaded together as a `.zip`:

- `<Name>.wsdl` holds the messages, port types, bindings and service, and
- `<Name>.xsd` holds the types. The WSDL imports it with `xsd:import`.

To get one file with the types inline, set the **layout** option to `single`.

- **Types.** An object becomes an XSD `complexType` with a `sequence`, an enumeration a `simpleType`
  with `enumeration` values, a `oneOf` (or another union) a `complexType` with an `xs:choice` of its
  variants, and a map a list of `entry` elements, each with a `key` and a `value`. A list repeats its
  element (`maxOccurs="unbounded"`, or the schema's `minItems`/`maxItems`). An optional or nullable
  field is `minOccurs="0" nillable="true"`. Descriptions become `xs:annotation` documentation.
- **Precision.** Scalars keep their width: `integer` is `xs:int` (`xs:long` with `format: int64`),
  `number` is `xs:double`, a string with `format: date-time` is `xs:dateTime`, and `decimal` stays
  `xs:decimal`.
- **Rules.** `minLength`, `maxLength`, `minimum`, `maximum`, the exclusive bounds, `pattern` and
  `enum` become XSD facets. A JSON Schema pattern is translated to XSD's dialect (`^[A-Z]{3}$` is
  written `[A-Z]{3}`, because an XSD pattern always matches the whole value). XSD has no facet for
  `multipleOf` or `uniqueItems`, nor for a pattern that uses lookahead, lazy quantifiers or `\b`;
  those rules are not written, and the fidelity report lists each one.
- **Operations.** Each operation becomes a SOAP operation with a request element named after it,
  carrying its path, query and header parameters and its request body, a `<operation>Response`
  element carrying the response body, and one element per error response (`getPetByIdStatus404Fault`).
  The HTTP method and path are not carried; the fidelity report says so for each operation.
- **Names.** Names must be valid XML names: `GET /pets/{petId}` is written `getPetsPetId`, and two
  names that end up the same get a number (`firstName2`). The fidelity report lists every rename.
- **Namespace.** Every type and operation lives in the WSDL's target namespace: the item's own
  namespace, or `http://example.com/service` when it has none (reported as synthesized).

An item imported from WSDL is written back as it was read: its messages, parts, bindings, SOAP
versions and XSD details round-trip unchanged.

Every WSDL export is checked before you can download it, the way it arrives once you unzip it:

- **Packaged.** The bundle holds exactly one WSDL, and every `xsd:import`, `xsd:include` and
  `wsdl:import` names a file inside the `.zip`. A link to a web address or outside the folder fails.
- **WS-I.** The description passes the WS-I Basic Profile checks: literal use, one binding style,
  document/literal parts, unique operation signatures and `soapAction`s.
- **Valid.** The WSDL validates against the WSDL 1.1 schema, every XSD type and facet is legal, and
  every message, part, port type, binding and port it names exists.
- **Re-imports.** The bundle imports into Apiome as a WSDL.

If a check fails, the export fails and lists each problem with its file and rule (`wsi.literal-use`,
`wsdl.bundle-reference`, `wsdl.structure`). An item imported from WSDL keeps its own bindings, so a
WS-I problem the original WSDL already had is not counted again; the item's lint report shows it.

### JSON Schema from any source

Exporting to **JSON Schema** writes the item's data types as a standalone JSON Schema, whatever it
was imported from — for validation pipelines, schema registries and contract tests. By default you
get one draft **2020-12** document, `<Name>.schema.json`, with every type under `$defs`; the
document itself refers (`$ref`) to the type named after the item, when there is one.

- **Types.** Scalars become JSON types, keeping their width as a `format`: a 32-bit integer is
  `{"type": "integer", "format": "int32"}`, a timestamp `{"type": "string", "format": "date-time"}`,
  bytes `{"type": "string", "contentEncoding": "base64"}`. A field that is not optional is listed in
  `required`; a list is an `array`, a union a `oneOf`, a map an object with `additionalProperties`.
  A type with no JSON form is written as `{}` (any value), and the fidelity report names it.
- **Rules.** `minLength`, `maxLength`, `pattern`, `minimum`, `maximum`, the exclusive bounds,
  `multipleOf` and the item counts are written as the same keywords.
- **Enumerations** are written as their JSON values: names for an Avro or Protobuf enum (their JSON
  encodings carry the name), numbers only for an enum of numbers.
- **Names.** Each type is a `$defs` entry named after it (`Order`); two types with the same name
  keep their full keys (`v1.Pet`, `v2.Pet`).

Options:

- **draft** — `2020-12` (default), `draft-07` or `draft-04`. An older draft gets `definitions` instead
  of `$defs`, a `$ref` with other keywords beside it wrapped in `allOf`, and drops what it has no
  keyword for (`deprecated`; in draft-04 also `contentEncoding` and `examples`). Draft-04 writes an
  exclusive bound as `minimum` / `maximum` with `exclusiveMinimum: true` and `$id` as `id`.
- **packaging** — `bundle` (default), or `per-type`: one `<Type>.schema.json` per type, which refer to
  each other by file name (`{"$ref": "Line.schema.json"}`), downloaded together as a `.zip` with a
  `manifest.json`.
- **id_base** — a base URI such as `https://example.com/schemas`: each document's `$id` becomes
  `https://example.com/schemas/<file name>`, so per-type files resolve each other wherever they are
  published.
- **mode** — `json-schema` (default), or `jtd` for a [JSON Type Definition](#json-type-definition-jtd-mode)
  document instead.

Each export is checked before you download it:

1. Every document validates against the metaschema of the draft it declares. A JTD document is
   checked against the RFC 8927 rules instead.
2. Every `$ref` into the export resolves: a `#/$defs/…` pointer must name a type in the document,
   and a `per-type` file's reference must name another file of the export. A reference to a schema
   published elsewhere (an absolute URL outside the export) is not checked.
3. Every document imports again as a JSON Schema.

If a check fails, the export fails and names the file, the JSON pointer and the rule
(`jsonschema.metaschema`, `jsonschema.unresolved-ref`, `jsonschema.reimport`). An item imported from
JSON Schema is re-exported exactly as it was imported unless you pick another draft, `per-type` or
an **id_base**.
Operations and channels are left out: JSON Schema describes data only.

The fidelity report is computed for the options you pick, so changing **draft** in the export dialog
updates it. It lists:

| In the source | In the JSON Schema export |
|---|---|
| Operations, services and channels | Dropped (critical). An item that has any also gets a **types-only** warning counting them — export it to OpenAPI or AsyncAPI as well to keep them |
| A document of another format | Approximated (note): written as JSON Schema, without what is specific to its format |
| A type whose key has a namespace (`com.example.Status`) | Approximated (note): written as `$defs/Status`, and read back under that name |
| A value with a `format` (`date-time`, `int64`, `email` …) | Approximated (note): `format` is an annotation — a validator checks it only when format assertion is switched on |
| `deprecated` (draft-07 and draft-04) | Dropped |
| `prefixItems` (draft-07 and draft-04) | Approximated: the tuple form of `items`, the other items as `additionalItems` |
| `unevaluatedProperties` (draft-07 and draft-04) | Approximated as `additionalProperties` when nothing else applies beside it, else dropped |
| `$dynamicRef`, `$dynamicAnchor`, `$anchor`, `unevaluatedItems` (draft-07 and draft-04) | Dropped |
| An exclusive bound, `const` (draft-04) | Approximated (note): `minimum` with `exclusiveMinimum: true`, a one-value `enum` |
| `examples`, `contentEncoding`, `readOnly`, `if` / `then` / `else` … (draft-04) | Dropped |

Each downgrade is listed on the type or field it happened in.

#### JSON Type Definition (JTD) mode

Set **mode** to `jtd` to get the same types as one [JSON Type Definition](https://www.rfc-editor.org/rfc/rfc8927)
(RFC 8927) document, `<Name>.jtd.json` — the strict, code-generation-friendly sibling of JSON Schema
that ajv and the `jtd-codegen` tools read. **draft**, **packaging** and **id_base** do not apply: leave
them unset, or the export is refused.

- **Types.** Each type is a `definitions` entry, and the document refers (`ref`) to the type named
  after the item. A record lists its required fields under `properties` and the others under
  `optionalProperties`; a list is `elements`, a map `values`, a string enumeration `enum`.
- **Scalars.** `string`, `boolean`, `int32`, `float32` and `float64` keep their JTD type; a timestamp is
  `timestamp`. A description is kept as `metadata.description`.
- Every exported document is checked against the schema rules of RFC 8927.

JTD states far less than JSON Schema, so the fidelity report lists every rule the document cannot
carry, on the type or field it is in:

| In the source | In the JTD export |
|---|---|
| `pattern`, `minimum` / `maximum`, the exclusive bounds, `multipleOf`, lengths, item counts, `uniqueItems` | Dropped |
| A `format` other than `date-time` (`uuid`, `email` …), `contentEncoding` | Dropped: written as a plain `string` |
| A 64-bit or unbounded integer (`int64`, `integer`) | Approximated: `float64`, which does not check that a value is whole or exact above 2^53 |
| A union (`oneOf`), or a value of several types | Approximated: `{}` (any value) — JTD only unions records tagged with a discriminator |
| An enumeration of numbers | Approximated: only the values' type is checked |
| `title`, `deprecated`, `default`, `examples` | Dropped (note) |
| Undeclared properties | Approximated (note): JTD rejects a property a record does not declare; the JSON Schema export allows it |

### XSD (XML Schema) on its own

Exporting to **XSD** writes just the data types as an XML Schema, without the WSDL around them — for
XML payloads, JAXB / JAXP code generation and standards that publish schemas (ISO 20022, UBL). The
types are written exactly as in a WSDL export (the section above; both exports share one mapping):
objects as `complexType`, a `oneOf` as `xs:choice`, a nullable field as `nillable="true"
minOccurs="0"`, a list as `maxOccurs="unbounded"`, enums as `xs:enumeration`, and `pattern`,
`minLength`/`maxLength` and `minimum`/`maximum` as facets. Each object also gets a global element of
the same name, so a document can start with it.

- **Version.** Set **xsd_version** to `1.0` (the default) or `1.1`. An XSD 1.1 schema is marked
  `vc:minVersion="1.1"` and writes `multipleOf: 5` as an assertion facet,
  `<xsd:assertion test="$value mod 5 = 0"/>`. XSD 1.0 has no facet for `multipleOf`, so the fidelity
  report lists it there.
- **Namespace.** The schema's `targetNamespace` is the item's own namespace; an item without one gets
  a no-namespace schema, whose types are referenced by plain name.
- **Several namespaces.** When the item's types live in different namespaces (URIs such as
  `http://example.com/common`), you get one `.xsd` per namespace, downloaded together as a `.zip`:
  `<Name>.xsd` is the main schema, `<Name>-common.xsd` the next, and each schema `xs:import`s the
  others it uses.
- **Operations.** XSD describes data only: operations and channels are left out. The fidelity report
  lists each one, and an item with operations carries a **types-only** advisory saying how many were
  left out — export it to WSDL, OpenAPI or AsyncAPI as well to keep them.

An item imported from XSD is written back with its own global elements, attributes, occurrences and
enumeration values.

Each export is checked before you download it, the way it arrives once you unzip it:

1. Every `.xsd` is safe, well-formed XML, and every `xs:import` and `xs:include` names a file inside
   the export. A link to a web address or outside the folder fails.
2. The schema is built by an XML Schema processor. An XSD 1.0 export must build under **both** the
   1.0 and the 1.1 processor; an XSD 1.1 export under the 1.1 processor. An unknown type, a broken
   facet or an XSD 1.1 construct in a 1.0 schema fails the export.
3. The export imports again as an XSD.

A failed check names the file and the rule (`xsd.bundle-reference`, `xsd.schema-1.0`,
`xsd.schema-1.1`, `xsd.reimport`). An item imported from WSDL is also checked through the WSDL
import: its XSD export, put in place of the WSDL's own schema, imports back unchanged.

The fidelity report lists, construct by construct, what XML Schema cannot say the way the source does:

| In the source | In the XSD export |
|---|---|
| An operation or channel | Dropped (types-only), with the advisory above |
| A free-form object (`additionalProperties: {}` or `{type: object}`, with no properties) | Approximated: `xs:any` — any child elements, named by their keys |
| A map with typed values | Approximated: a list of `entry` elements, each with a `key` and a `value` |
| A `oneOf` (or another union) | Approximated: an `xs:choice` of child elements, so a document wraps the value in the element of its alternative |
| A union with no alternatives | Dropped: an empty `complexType` |
| A nullable value | Approximated (note): `nillable="true" minOccurs="0"` — XML tells an absent element from one marked `xsi:nil`, JSON tells `null` from absent, and either form is accepted |
| A property's examples | Approximated (note): kept as `<xsd:documentation source="example">`, which a validator ignores |
| Properties of a non-XSD item | Synthesized (note): each is written as a child element, not an attribute |
| `multipleOf` (XSD 1.0), `uniqueItems`, a pattern XSD cannot express | Dropped: the rule is not written |
| A deprecated property | Dropped (note): XSD has no deprecation marker |
| A name that is not an XML name (`first name`) | Approximated (note): `firstName` |

### ASN.1 from any source

Exporting to **ASN.1** writes the item's data types as one ITU-T X.680 module, `<Module>.asn1`,
for telecom, PKI and aviation tool chains. The module compiles with `asn1tools`. Operations and
channels are left out: an ASN.1 module describes data only.

- **Types.** Objects become `SEQUENCE`s, unions `CHOICE`s (one alternative per member type), enums
  `ENUMERATED` (numbered when every value is a distinct integer), and lists `SEQUENCE OF`. A map
  becomes `SEQUENCE OF SEQUENCE { key …, value … }`, because ASN.1 has no map type.
- **Scalars.** Text is `UTF8String`, bytes `OCTET STRING`, a timestamp `GeneralizedTime`, a date
  `DATE`, a time `TIME-OF-DAY`, a real `REAL`. A sized integer keeps its width as a range: `uint8` is
  `INTEGER (0..255)`, `int32` `INTEGER (-2147483648..2147483647)`.
- **Optional fields.** A field with a default is written `DEFAULT <value>` (`TRUE`, `3`, `"hi"`, or an
  enum item); any other field that may be left out is `OPTIONAL`.
- **Names.** Type names start with a capital letter and field and enum names with a small one, using
  hyphens between words: `order_id` is written `order-id`, `OPEN` is `open`, and a type named like a
  reserved word (`END`) gets `-Type`. Each rename is in the fidelity report, and a clash gets a
  number (`line-no-2`).
- **Descriptions** are written as `--` comments. An ASN.1 import does not read comments, so the report
  notes each one.

Constraints are kept as ASN.1 subtype notation, so a validator such as `asn1tools` checks them when
encoding:

| In the source | In the ASN.1 export |
|---|---|
| `minLength` / `maxLength` | `UTF8String (SIZE (3..20))`, also on `OCTET STRING` |
| `minItems` / `maxItems` | `SEQUENCE (SIZE (1..50)) OF …` (other rules on a list apply to its items) |
| `minimum` / `maximum` | A value range, `INTEGER (1..100)`, within the integer's width |
| An exclusive bound on an integer | The same range, inclusive: `> 0` is written `1..` |
| An exclusive bound on a real | Approximated: written inclusive, because `asn1tools` cannot read `<` |
| An `enum` of integers | A value set, `INTEGER (1 \| 2 \| 5)` |
| A `pattern` that only lists the allowed characters, anchored at both ends (`^[A-Z0-9_]{3,8}$`, `^\d{4}$`) | A permitted alphabet with its length: `UTF8String (SIZE (3..8)) (FROM ("A".."Z" \| "0".."9" \| "_"))` |
| Any other `pattern` (`^[A-Z]{3}-\d+$`) | A `-- pattern: …` comment above the field — `asn1tools` does not check it |
| `multipleOf`, `uniqueItems`, an `enum` of strings, formats such as `email` | Dropped, and listed in the report |

Options:

- **module_name** — the module name, such as `Shop-Orders`. By default it is the imported module's
  name, else the item's namespace when that is already a valid module name, else the item's name.
- **oid** — the module's object identifier, dotted (`1.3.6.1.4.1.99999.1`) or as arcs in braces
  (`{ iso(1) identified-organization(3) 6 }`). It is written after the module name.
- **automatic_tags** — on by default (`AUTOMATIC TAGS`). Turn it off to keep an imported module's
  own tagging.
- **include_comments** — on by default; turn it off to leave out the header, description and pattern
  comments.

An item imported from ASN.1 exports back to an equivalent module that reads back unchanged, built-in
types such as `OBJECT IDENTIFIER` and `PrintableString` included. A type the module imports from
another module has no definition to write, so it is written as `UTF8String` and listed in the report.

The fidelity report lists, on each type or field:

| In the source | In the report |
|---|---|
| Operations, services and channels | Dropped (critical). An item that has any also gets a **types-only** warning counting them — export it to OpenAPI or AsyncAPI as well to keep them |
| A rule written as subtype notation (lengths, bounds, item counts, a set of integers) | Carried, naming the notation used (`minLength/maxLength → SIZE`) |
| A pattern written as a permitted alphabet | Approximated (note) |
| Any other pattern, `multipleOf`, `uniqueItems`, a set of strings, a default with no ASN.1 value | Dropped |
| An exclusive bound on a real, a map, a type with no ASN.1 form | Approximated |
| A name respelled to the ASN.1 rules (`order_id` → `order-id`) | Synthesized (note) |
| A type that refers to itself (`Node.next: Node`) | Carried |
| A description, a document of another format, types read back under the module name | Approximated (note) |

### WADL from any source

Exporting to **WADL** writes a description that validates against the W3C WADL schema, with its
types in an XSD grammar. By default you get two files, downloaded together as a `.zip`:

- `<Name>.wadl` holds the resources and methods, and
- `<Name>.xsd` holds the grammar. The WADL links it with `<grammars><include href="…"/>`.

To get one file with the grammar inline, set the **layout** option to `single`. A model with no types
and no request or response bodies has no grammar, so you get the `.wadl` alone.

- **Resources.** Each path segment becomes a `resource`, nested the way the paths are (`/pets/{petId}`
  is `pets` holding `{petId}`); an operation on `/` gets `<resource path="/">`.
- **Methods.** Each operation is a `method` with its HTTP verb, its description as `doc`, and its
  operation name as `id` when the source names it.
- **Parameters.** Path parameters are `template` params on the resource that names them; query and
  header parameters are request params, with their XSD type (`xsd:long` for a 64-bit integer),
  `required`, `default` and documentation. An array is a `repeating` param.
- **Bodies.** The request body and every response carry a `representation` with the body's media type
  and the grammar element of its type. A list or scalar body gets an element of its own in the grammar
  (`getPetsResponse200`). Each response keeps its status code.
- **Types.** The grammar is the same XSD a WSDL export writes (see the section above): types keep
  their precision, optional fields are `minOccurs="0"`, and constraints become facets.

WADL describes HTTP resources and nothing else, so the fidelity report lists what it cannot carry:

- operations with no HTTP method and path (from gRPC, GraphQL or WSDL sources), and event operations;
- cookie parameters, and status ranges such as `4XX`;
- every server but the first;
- the grouping into services, the version and the description;
- gateway details such as routes, backends and hosts.

When the source has no server, the base URI `https://api.example.com/` is used, and the report says so.

### RAML from any source

Exporting to **RAML** writes one `<Name>.raml` file in RAML 1.0, starting with the `#%RAML 1.0` header
line that RAML tools require.

- **Document.** The item's title, description and version, its first server as `baseUri` (server
  variables become `baseUriParameters`), and a `mediaType`: a RAML item keeps its own; otherwise it is
  the media type the bodies use most, or `application/json`. Set the **media_type** option to choose
  another default.
- **Types.** Objects keep their fields in order, and an optional field is written `name?`. Enums are
  `string` types with `enum`, unions are `Cat | Dog`, and maps are objects with a `//` property.
  Numbers keep their width (`integer` with `format: int64`) and dates their type (`datetime`,
  `date-only`). Lengths, ranges, patterns, list sizes, enums and defaults become RAML facets.
- **Resources.** Each path is one resource (`/pets/{petId}`), with its path parameters as
  `uriParameters`. Each operation is a method with its operation name as `displayName` (when the
  source names it), its description, query parameters, headers and body, and its responses by status
  code with their description, headers and body.

The fidelity report lists what RAML cannot carry:

- operations with no HTTP method and path (from gRPC, GraphQL or WSDL sources), a `TRACE` or `CONNECT`
  method, event operations and channels, and a second operation on the same method and path;
- cookie parameters, and status ranges such as `4XX`;
- every server but the first, and the grouping into services;
- exclusive bounds, string formats RAML has no type for (`email`, `uuid`), and a facet the type does
  not allow;
- deprecation flags, tags, and source details such as gateway routes;
- renamed types: RAML type names cannot contain dots or spaces, so `com.acme.Order` is written
  `Order` (or `Order2` when the name is taken).

An item imported from RAML is written back as it was read. Its resource types and traits are already
applied to each method when it is imported, so the export writes the methods in full, without `type:`
or `is:`, and the report says so.

Each export is checked before you download it:

1. **AMF** validates it against RAML 1.0 when the server has the AMF toolchain. A violation fails the
   export and names its rule, line and column (`example-validation-error`); warnings do not. Without
   AMF, the RAML importer reads the document instead, and a parse error fails the export.
2. The document is then imported again. If it does not import, the export fails (`raml.reimport`).

An item imported from RAML exports and re-imports unchanged. From any other source, the re-import
shows what RAML could not keep; the fidelity report names those losses.

An item imported from WADL is written back as it was read. Import now also reads a WADL root written
as `<wadl:application>`, the query and header params a method's request declares, and — when you
upload the WADL together with its `.xsd` in a `.zip` — the grammar it includes.

### Arazzo from any source

**Arazzo** describes workflows: sequences of API calls. It is not a description of the API itself,
so exporting a plain REST, RPC or event API to Arazzo gives you only the sequencing Apiome can make
of it. The fidelity report warns about this first: *this target captures workflows, not the full API
surface*.

- **An item imported from Arazzo** is written back as it was read, with its own workflows, steps,
  inputs and outputs.
- **Any other item** gets one workflow per service. The workflow's steps call that service's
  operations by id, in the order they are declared. The source declares no such workflow, so the
  report marks it **synthesized**. When an operation has no id of its own, the step uses the
  operation's key (`POST /orders`), and the report marks that synthesized too.
- **Each operation** becomes a step and is marked **approximated**. Its parameters, request and
  response schemas stay in the source description and are not written.
- **Types, servers and event channels** are not written. Types and channels are marked **dropped**.
- **An item with nothing to sequence**, such as a set of types or an event API, exports as a
  near-empty document with no workflow, marked **dropped**.

Every export from a non-Arazzo item shows the fidelity warning before you download.

### API Blueprint from any source

Exporting to **API Blueprint** writes one `<Name>.apib` file in API Blueprint 1A: Markdown, with
its data structures in MSON. It is meant to be read by people, as documentation of the API, so it
writes what a reader needs and leaves out validation rules MSON cannot express.

- **Document.** The `FORMAT: 1A` line and the first server as `HOST` come first, then the item's
  title and description.
- **Resources.** Each path is one resource (`## Pets [/pets/{petId}]`) with its path parameters.
  Each operation is an action with its name, method and description. Its query parameters go in the
  action's URI (`[GET /pets{?limit}]`) and are listed under **Parameters**. Its request and its
  responses, one per status code, name their media type and body (`+ Attributes (Pet)`). A body
  given as an inline JSON Schema is written as a `+ Schema` section.
- **Data structures.** Objects list their fields in order as MSON properties, such as
  `+ id (string, required) - Pet id.`. A default is a nested `+ Default:` line. Enums list their
  members, and an alias is a named type based on what it wraps.
- **Types.** MSON has three value types: `string`, `number` and `boolean`. A 64-bit integer becomes a
  `number`, and a date becomes a `string`.

The fidelity report lists what API Blueprint cannot carry:

- validation rules: lengths, ranges, patterns and formats are marked **dropped** wherever they sit (a
  field, a parameter, a named scalar, an alias or an object), next to anything else about how that
  part is written;
- operations with no HTTP method and path (from gRPC, GraphQL or WSDL sources), event operations and
  channels, and a second operation on the same method and path;
- header and cookie parameters, status ranges such as `4XX`, and response headers and descriptions;
- every server but the first, server variables, the version, and the grouping into services;
- types MSON writes differently: wider numbers and dates as `number` and `string`, aliases, named
  scalars and maps as named types (marked **approximated**), and unions, which MSON lacks (marked
  **dropped**);
- deprecation flags, tags, and source details such as gateway routes;
- renamed types: MSON type names here are letters, digits and `_`, so `com.acme.Order` is written
  `com_acme_Order`.

An item imported from API Blueprint is written back as it was read. Import now also reads an
action's description, query parameters from the URI (`{?limit}`), a data structure's description,
`+ Default:` values, and property names in backticks.

Each export is checked before you download it:

1. **drafter**, the API Blueprint parser, reads it when the server has it. A good blueprint has no
   warnings, so any drafter **error or warning** fails the export and names its code, line and
   column. Without drafter, the API Blueprint importer reads the document instead, and a parse error
   fails the export.
2. The document is then imported again. If it does not import, the export fails
   (`apiblueprint.reimport`).

An item imported from API Blueprint exports and re-imports unchanged. From any other source, the
re-import shows what API Blueprint could not keep; the fidelity report names those losses.

| Format | Kind | Exports from |
| --- | --- | --- |
| Apache Avro | Data schema | Any source |
| Apache Thrift | RPC | Any source |
| API Blueprint | REST | Any source |
| Apigee API proxy | REST | Any source |
| Arazzo | REST | Any source |
| ASN.1 | Data schema | Any source |
| AsyncAPI 3.1 | Events | Any source |
| AWS API Gateway | REST | Any source |
| Azure API Management | REST | Any source |
| Cap'n Proto | RPC | Any source |
| CDDL | Data schema | Any source |
| CloudEvents | Events | Any source |
| COBOL Copybook | Data schema | Any source |
| Connect RPC | RPC | Any source |
| CORBA IDL | RPC | Any source |
| EDI X12 | Data schema | A source imported as EDI X12 |
| Envoy xDS RouteConfiguration | REST | Any source |
| FHIR | REST | Any source |
| FIX | Data schema | A source imported as FIX |
| FlatBuffers | Data schema | Any source |
| Gateway API HTTPRoute | REST | Any source |
| GraphQL SDL | Graph | Any source |
| HL7 v2 | Data schema | A source imported as HL7 v2 |
| Hoppscotch | REST | Any source |
| HTTP Request File | REST | Any source |
| ISO 20022 | Data schema | A source imported as ISO 20022 |
| ISO 8583 | Data schema | A source imported as ISO 8583 |
| Istio VirtualService | REST | Any source |
| JSON Schema | Data schema | Any source |
| JSON Type Definition | Data schema | Any source |
| Kafka Connect Schema | Data schema | Any source |
| Kong Declarative Config | REST | Any source |
| Kubernetes CRD | Data schema | Any source |
| LLM Tool Definitions | Agent tools | Any source |
| OData | REST | Any source |
| ODCS Data Contract | Data schema | Any source |
| ONC RPC | RPC | Any source |
| OpenAPI 3.1 | REST | Any source |
| OpenRPC | RPC | Any source |
| Postman | REST | Any source |
| Protocol Buffers (proto3) | RPC | Any source |
| RAML | REST | Any source |
| SAP IDoc | Data schema | A source imported as SAP IDoc |
| Smithy | RPC | Any source |
| Thunder Client | REST | Any source |
| Traefik dynamic configuration | REST | Any source |
| TypeSpec | REST | Any source |
| WADL | REST | Any source |
| WIT (WebAssembly) | RPC | Any source |
| WSDL | REST | Any source |
| X12 implementation guide | Data schema | Any source with a record type |
| XML-RPC | RPC | A source with an RPC operation |
| XSD | Data schema | Any source |
| z/OS Connect | REST | A source imported as z/OS Connect |

---

## With the CLI

```bash
# OpenAPI (default), JSON, to a file
apiome spec export --project <id-or-slug> --version <id-or-label> --output petstore.json

# YAML
apiome spec export --project <id-or-slug> --version <id-or-label> --yaml -o petstore.yaml

# Exporting to another format (AsyncAPI, GraphQL, Proto3, Avro, …)? Check what will be
# preserved — and why anything changes — before you generate:
apiome export targets  --project <id-or-slug> --version <id-or-label>
apiome export evidence --project <id-or-slug> --version <id-or-label> --target avro

# Arazzo workflow document instead of OpenAPI
apiome spec export --project <id-or-slug> --version <id-or-label> --format arazzo -o flows.json
```

Use `-o -` to stream to stdout. `--format` accepts `openapi` (default) or `arazzo`.

### Download Arazzo or JSON Schema by slug

`apiome schema arazzo` and `apiome schema json` take the published version as one
`tenant/project/version` argument (slugs, as in the REST route) and write to stdout by default,
so they suit a redirect, a pipe or a build step. They share the same flags; only the default
`--format` differs — **yaml** for Arazzo, **json** for JSON Schema.

```bash
# JSON Schema (2020-12) bundle, every class
apiome schema json acme-corp/payments-api/2.1.0 > schema.json

# One class's schema, straight into a code generator
apiome schema json acme-corp/payments-api/2.1.0 --class Charge \
  | npx quicktype --src-lang schema --lang go > charge.go
```

The JSON Schema is streamed exactly as the server emits it (`$schema:
https://json-schema.org/draft/2020-12/schema`); the CLI does not transform it.

```bash
# Full Arazzo bundle
apiome schema arazzo acme-corp/payments-api/2.1.0 > workflows.arazzo.yaml

# One class's workflow (the per-class route)
apiome schema arazzo acme-corp/payments-api/2.1.0 --class Charge > charge.arazzo.yaml

# JSON instead of YAML, written to a file
apiome schema arazzo acme-corp/payments-api/2.1.0 --format json --output workflows.arazzo.json

# Pin the exact bytes in CI: exit 6, and nothing written, if the document changed
apiome schema arazzo acme-corp/payments-api/2.1.0 -o workflows.arazzo.yaml \
  --expect-sha256 <sha256-from-a-first-run>
```

| Flag | What it does |
|---|---|
| `--class NAME` | Download only that class's workflow or schema. An unknown class exits 2. |
| `--format json\|yaml` | Serialization. Default **yaml** for `schema arazzo` (the usual form for Arazzo), **json** for `schema json`. |
| `--output FILE`, `-o` | Write to a file. Default `-`, stdout. |
| `--expect-sha256 HEX` | Compare the document's SHA-256 first; on a mismatch print both digests, write nothing and exit **6**. A `sha256:` prefix is accepted. |

The document is written byte for byte as the server sent it. A summary — bytes written, format and
`Checksum: sha256:…` — goes to stderr, so copy the checksum from a first run into
`--expect-sha256`. With the global `--json`, the summary is one JSON object: on stdout when the
document goes to a file, on stderr when the document goes to stdout.

The version must be published. An unknown or unpublished version, or a private one without an API
key, exits 2; set `APIOME_API_KEY` for private versions. No tenant configuration is needed — the
tenant is in the argument.

## With the REST API

```http
GET /v1/schema/{tenant_slug}/{project_slug}/{version_slug}
Accept: application/json          # default; use application/yaml for YAML
```

Other representations of the same version:

| Format | Route |
|---|---|
| OpenAPI | `GET /v1/schema/{tenant}/{project}/{version}` |
| Arazzo | `GET /v1/arazzo/{tenant}/{project}/{version}` (one class: append `/{class}`) |
| JSON Schema | `GET /v1/json/{tenant}/{project}/{version}` (one class: append `/{class}`) |

For private versions, pass an in-scope API key via the `X-API-Key` header (or the `api_key` query
parameter).

### Export to several formats in one job

To publish a version in several formats at once, send one export job with a `targets` list instead
of a single `target`. Apiome emits the version to every listed format and hands back **one zip**.

```http
POST /v1/export/{tenant_slug}/jobs
{
  "artifact": "<project-id>",
  "version": "1.0.0",
  "targets": [
    { "target": "openapi" },
    { "target": "graphql" },
    { "target": "protobuf", "options": { "package": "acme.payments.v1" } }
  ]
}
```

1. The `202` response carries a `status_path`. Poll it until `state` is `completed` or `failed`.
2. Download the zip from `result.download_path`. Each format sits in its own folder, named after
   the resolved format key (`openapi-3.1/`, `graphql/`, …), and a root `manifest.json` lists
   every folder, its files, its fidelity tier and the version that produced it.
3. Read the fidelity on the job result:
   - `result.targets[]` has one entry per format, in the order you sent them: its full fidelity
     report, transcoding guard, validation report, delivery decision and the files it added to
     the zip.
   - `result.fidelity_rollup` sums them up: the worst tier, the lowest and average preserved
     share, how many formats landed in each tier, and which formats are lossy or need
     confirmation.

| Rule | Behavior |
|---|---|
| `target` vs `targets` | Send one or the other. Mixing them, or putting `options` / `acknowledged_snapshot` at the top level next to `targets`, is rejected with `422`. |
| Per-format settings | `options` and `acknowledged_snapshot` go on each `targets` entry. |
| How many | Up to 16 entries in `targets`. Two entries that resolve to the same format (`openapi` and `openapi-3.1`) are rejected with `400`. |
| `dry_run: true` | Every format's fidelity report and the rollup, no zip. |
| Severe conversions | If any format needs confirmation, the job fails with `TRANSCODE_CONFIRMATION_REQUIRED` before anything is generated. Resubmit with `"confirm": true`. |
| Failures | All or nothing: the first format that fails fails the job, and `error.context.target` names it. No zip is kept. |
| Attestation | Each format is attested separately against the zip. Fetch one with `GET …/jobs/{job_id}/attestation?target=<format key>`. |

The same rules for snapshots and acknowledgements apply to each format; see
[Understand export fidelity](./export-fidelity.md#snapshots-and-the-risk-acknowledgement).

### Export a whole project or several versions in one job

To export more than one version of a project, send one export job with a `versions` list (version
labels or revision ids) or `"all_versions": true` instead of `version`. Every version is exported
to every target you name, and you get back **one zip**.

```http
POST /v1/export/{tenant_slug}/jobs
{
  "artifact": "<project-id>",
  "versions": ["1.0.0", "1.1.0", "2.0.0"],
  "targets": [
    { "target": "openapi" },
    { "target": "graphql" }
  ]
}
```

Each version × format pair is an **item**. An item that fails does not stop the others.

1. The `202` response carries a `status_path`. Poll it until `state` is `completed` or `failed`.
2. Read `result.batch` on the completed job:
   - `completed_count` and `failed_count` say how many items made it into the zip.
   - `items[]` has one entry per item: its version, format, `state`, folder in the zip, fidelity
     tier and preserved share, delivery decision, files, and, for a failed item, an `error` with
     the same `code`, `message` and `remediation` a failed single export carries.
   - `result.fidelity_rollup` sums up the fidelity of the completed items.
3. Download the zip from `result.download_path`. Each completed item sits in a
   `<version>/<format>/` folder (`1.0.0/openapi-3.1/`, `1.0.0/graphql/`, …). The root
   `manifest.json` lists every item, including the failed ones and why they failed.

| Rule | Behavior |
|---|---|
| Choosing versions | Send `versions` (up to 50 distinct entries) or `"all_versions": true`, never together and never with `version`. `all_versions` takes every version of the project, newest first. |
| Formats | Use `target` (with `options`) for one format, or a `targets` list for several. |
| How many | Up to 100 items (versions × formats). A longer `versions` list is rejected with `422`; an `all_versions` job over a bigger project fails with `EXPORT_BATCH_TOO_LARGE`. |
| Snapshots | `acknowledged_snapshot` is not accepted: a snapshot describes one version. Preview a version on its own to acknowledge it. |
| Failures | Per item. A version that does not exist, a format that fails, a severe conversion without `"confirm": true` or a blocked delivery fails only that item, and the job still completes. The job fails with `EXPORT_BATCH_FAILED` only when every item failed; `error.context.items` lists each one. |
| Same version twice | A label and its own revision id count as one version; the second is skipped with a `BATCH_VERSION_DUPLICATE` warning. |
| `dry_run: true` | Every item's fidelity tier and the rollup, no zip. |
| Attestation | Each completed item is attested against the zip. Fetch one with `GET …/jobs/{job_id}/attestation?version=<version>&target=<format key>`. |

### Export several items in one job

To export several catalog items or projects at once, send `items` instead of `artifact`. Each entry
names an `artifact` and, optionally, a `version`; without one the item's latest version is exported.

```http
POST /v1/export/{tenant_slug}/jobs
{
  "items": [
    { "artifact": "<orders-item-id>" },
    { "artifact": "<pets-item-id>", "version": "1.0.0" }
  ],
  "targets": [{ "target": "openapi" }]
}
```

It runs as a batch, so everything above applies: each item × format pair succeeds or fails on its
own, `result.batch.items[]` reports each one (now with its `artifact`), and you get back one zip.

- Each item's files sit in a folder named after the item's slug: `orders-api/openapi-3.1/`. An item
  that names a version adds the version: `pets-api-1.0.0/openapi-3.1/`.
- The root `manifest.json` gives each item's `artifact`, and `artifact_count` says how many distinct
  items the job covered.
- `items` cannot be combined with `artifact`, `version`, `versions` or `all_versions`. Entries must be
  distinct, and the job runs at most 100 item × format pairs. A request that breaks a rule is
  rejected with `422`.

The Catalog's bulk **Export…** and `apiome export <format> --items` send this request for you.

### From the CLI: several formats or several items

`apiome export <format>` exports through the same job pipeline. Two flags turn it into one job that
writes one archive. They work for every format with no dedicated command; `openapi`, which has one,
can still be one of the `--targets`.

```bash
# One version to three formats: a folder per format
apiome export graphql payments-api --targets openapi,avro --out exports/

# Three catalog items, each at its latest version (or ITEM@VERSION), to one format
apiome export graphql --items orders-api,pets-api@1.0.0,events-bus --out exports.zip
```

| Flag | Behavior |
|---|---|
| `--targets FORMAT,…` | More formats after `<format>`, in one all-or-nothing job. `--option` applies to `<format>` only; the other formats use their defaults. |
| `--items ITEM[@VERSION],…` | Ids or slugs, instead of `ARTIFACT`. Runs a batch job; `--version` does not apply (use `@VERSION`). |
| `--out` | A directory to unpack into, or a `.zip` path. `-` (stdout) is refused. |

The command prints one row per item × format, with its state, fidelity tier and folder (or error).
It exits **0** when every item completed, **7** when the archive was written but some items failed,
and **1** when every item failed. `--min-grade` and `--fail-on` gate a single export, so they are
refused with these flags.

## Limits

Every export job runs inside these limits. A request that hits one is refused with a message naming
the limit, so you know what to change. An administrator can change each one with the setting shown;
`0` turns a limit off.

| Limit | Default | When it is hit | Setting |
|---|---|---|---|
| Jobs running at once, per workspace | 5 queued or running | A new job is refused with `429` until one finishes or is cancelled | `APIOME_EXPORT_MAX_CONCURRENT_JOBS_PER_TENANT` |
| How long one job may run | 30 minutes | The job stops and fails with `EXPORT_JOB_TIMED_OUT` | `APIOME_EXPORT_JOB_TIMEOUT_SECONDS` |
| Size of the download | 32 MiB | The job fails with `EXPORT_ARTIFACT_TOO_LARGE` | `APIOME_EXPORT_ARTIFACT_MAX_BYTES` |
| Items in one batch | 100 items × formats; 50 versions; 16 entries in `targets` | The request is refused with `422`, or an `all_versions` job fails with `EXPORT_BATCH_TOO_LARGE` | Fixed |
| How long a download is kept | 24 hours | The download answers `410 Gone`; run the export again | `APIOME_EXPORT_ARTIFACT_RETENTION_HOURS` |

Every member's jobs count toward the workspace's five. A download past its retention time is
deleted, not just hidden. The job itself stays in the job list (`GET /v1/export/{tenant_slug}/jobs`)
until it is cleared: 7 days after it finished or was cancelled, 30 days after it failed.

### File names in a download

File and folder names in a download come from your source: the API's title, a type's name, an Avro
namespace. Apiome keeps every name inside the download. A name that would leave the folder you
unpack into (one starting with `/` or a drive letter, or containing `..` or `\`) is rewritten to
stay inside it: an Avro namespace `com.acme` becomes the folders `com/acme`, and parts that are not
legal Avro names become `_`. A file name in any script, such as `注文-api.jtd.json`, keeps its
characters when you download it. Every download is sent as an attachment, and browsers are told not to guess its type.

## Verify

The exported document is valid OpenAPI and contains the classes and paths you edited. The
[Golden Path](https://github.com/apiome/apiome/blob/main/docs/GOLDEN_PATH.md) does exactly this — it exports via the real CLI and re-validates the
downloaded document with `openapi-spec-validator`.

## Test-drive it

For OpenAPI targets, the [Export studio](./export-studio.mdx)'s Review step can turn the artifact you just generated into
a **live mock** for a few minutes — a base URL you can `curl`, responses generated from
the document's own response schemas, and a log of everything it served. It is the strongest check
available: a document that cannot answer its own operations is a finding no static validation would
surface.

```http
POST /v1/export/{tenant_slug}/mock
{ "artifact": "<project-id>", "version": "1.0.0", "target": "openapi" }
```

The mock expires by itself, and servers without the Mock Server deployed report the capability as
unavailable rather than offering a button that cannot work. See
[export_mock_test_drive.md](https://github.com/apiome/apiome/blob/main/apiome-rest/docs/export_mock_test_drive.md) for the endpoints,
the lifetime rules and the configuration, and [Mock try-out](./mock-try-out.mdx#test-drive-an-export) for the panel.

## Related

- [Supported formats](../bring-in/supported-formats.md) — every format Apiome imports and exports,
  generated from the registries
- [Export studio](./export-studio.mdx) — the same export step by step, with verify and a job
- [Export catalog items](./export-catalog-items.mdx) — one item or many, every target's fidelity tier
- [Understand export fidelity](./export-fidelity.md) — cross-format exports: what is preserved,
  what is lost and why, and the risk acknowledgement
- [Export to an API gateway](./export-to-a-gateway.md) — Kong, Gateway API, Envoy, Istio, Traefik,
  AWS API Gateway, Azure API Management and Apigee configuration
- [Export to an API client](./export-to-an-api-client.md) — Hoppscotch and Thunder Client
  collections, with their environments
- [Browse published specs](./browse-published-specs.md) — view the same spec rendered
- [Compare published versions](./compare-published-versions.md) — diff two published versions
  with `apiome schema diff`
- [CLI quick-start](../reference/cli-quickstart.md) — full CLI reference
