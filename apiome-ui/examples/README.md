# Catalog import examples

Sample source documents for exercising the catalog **Import** flow (the
ImportDialog source cards → format auto-detection → catalog item). Each file is a
small, self-contained, valid document with a header comment explaining what it
demonstrates.

## How the catalog uses these

- **Format auto-detection** (`apiome-rest` `format_detection.py`) sniffs the
  content and names the format, so you do not have to pick it manually. The header
  comment in each file notes the marker that detection keys on (e.g. `#%RAML 1.0`,
  `syntax = "proto3"`, `<edmx:Edmx>`, top-level `asyncapi:`).
- **Catalog pills** (`apiome-ui` `catalog-format-registry.ts`) render the
  format, protocol/paradigm, and source-material badges off the imported item.

Importable today: **OpenAPI** (also reachable via File / URL / Clipboard). The
other formats are recognized and named by detection; full import adapters land in
their respective format epics. The examples are arranged so a new adapter has a
ready-made fixture the day it ships.

## Layout

### REST / HTTP

| Directory        | Format               | Paradigm   | Marker / shape                       |
| ---------------- | -------------------- | ---------- | ------------------------------------ |
| `openapi/`       | OpenAPI 3.x          | REST       | `openapi:` version                   |
| `swagger/`       | Swagger 2.0          | REST       | `swagger: "2.0"`                     |
| `raml/`          | RAML 1.0             | REST       | `#%RAML 1.0` header                  |
| `api-blueprint/` | API Blueprint        | REST       | `FORMAT: 1A`                         |
| `wadl/`          | WADL                 | REST       | `<application>` (WADL ns)            |
| `wsdl/`          | WSDL 1.1 (SOAP)      | REST/SOAP  | `<wsdl:definitions>` root            |
| `odata/`         | OData v4 (EDMX)      | REST/data  | `<edmx:Edmx>` root                   |
| `arazzo/`        | Arazzo workflows     | REST       | `arazzo:` version                    |
| `postman/`       | Postman v2.1         | REST       | collection `schema` URL              |
| `zos-connect/`   | z/OS Connect requester | REST     | API requester descriptor            |

### RPC

| Directory        | Format               | Paradigm   | Marker / shape                       |
| ---------------- | -------------------- | ---------- | ------------------------------------ |
| `protobuf/`      | Protobuf / gRPC      | RPC        | `syntax = "proto3"`                  |
| `connectrpc/`    | Connect-RPC          | RPC        | Protobuf `service` (Connect)         |
| `smithy/`        | Smithy 2.0           | RPC        | `$version` + shapes                  |
| `thrift/`        | Apache Thrift        | RPC        | `service` / `struct` shapes          |
| `typespec/`      | TypeSpec             | REST/RPC   | `import "@typespec/..."`             |
| `openrpc/`       | OpenRPC (JSON-RPC)   | RPC        | `openrpc:` version                   |
| `xml-rpc/`       | XML-RPC              | RPC        | `<methodCall>` / `<methodResponse>`  |
| `onc-rpc/`       | ONC RPC / XDR        | RPC        | `program {} = N` + XDR types         |
| `corba-idl/`     | CORBA / OMG IDL      | RPC        | `module` + `interface`               |

### Event / messaging

| Directory        | Format               | Paradigm   | Marker / shape                       |
| ---------------- | -------------------- | ---------- | ------------------------------------ |
| `asyncapi/`      | AsyncAPI 2.x/3.0     | Event      | top-level `asyncapi:`                |
| `cloudevents/`   | CloudEvents 1.0      | Event      | `specversion` envelope               |

### Graph

| Directory        | Format               | Paradigm   | Marker / shape                       |
| ---------------- | -------------------- | ---------- | ------------------------------------ |
| `graphql/`       | GraphQL SDL          | Graph      | root `type Query` / `schema {}`      |

### Data schema

| Directory        | Format               | Paradigm   | Marker / shape                       |
| ---------------- | -------------------- | ---------- | ------------------------------------ |
| `json-schema/`   | JSON Schema          | Data schema| `$schema` / `type` + `properties`    |
| `jtd/`           | JSON Type Definition | Data schema| `properties`/`optionalProperties`    |
| `avro/`          | Avro schema          | Data schema| `type: record` + `fields`            |
| `xsd/`           | XML Schema (XSD)      | Data schema| `xs:schema` root                     |
| `flatbuffers/`   | FlatBuffers          | Data schema| `table`/`struct` + `root_type`       |
| `capnproto/`     | Cap'n Proto          | Data schema| `@0x…;` file id + `struct`           |
| `asn1/`          | ASN.1                | Data schema| `DEFINITIONS ::= BEGIN … END`        |
| `cobol-copybook/`| COBOL copybook       | Data schema| level numbers + `PIC` clauses        |

### Industry / domain messaging

| Directory        | Format               | Domain     | Marker / shape                       |
| ---------------- | -------------------- | ---------- | ------------------------------------ |
| `fhir/`          | FHIR R4              | Healthcare | `resourceType` (+ StructureDefinition) |
| `hl7v2/`         | HL7 v2.x             | Healthcare | `MSH|^~\&|` header                   |
| `iso20022/`      | ISO 20022            | Finance    | `iso:20022` XML namespace            |
| `fix/`           | FIX / FIX Orchestra  | Finance    | `8=FIX.` tags / `<fixr:repository>`  |
| `iso8583/`       | ISO 8583             | Finance    | MTI + numbered data elements         |
| `edi-x12/`       | EDI ASC X12          | B2B/EDI    | `ISA`/`GS`/`ST` envelopes            |

## Trying an import

In the ADE dashboard, open **Import**, pick **File Upload** (or **Clipboard
Paste**), and drop one of these files. Detection names the format; an OpenAPI file
imports end-to-end into a catalog item.
